"""
Docker control-plane utility for the Cyber Range platform.

Wraps the synchronous `docker` SDK in asyncio-compatible functions (via
run_in_executor) so FastAPI route handlers can `await` container lifecycle
operations without blocking the event loop.

Safety posture for every spawned sandbox:
    - network_mode="none"   -> fully internet-isolated, no lateral egress
    - mem_limit="512m"      -> hard memory ceiling, prevents host exhaustion
    - nano_cpus=500000000   -> 0.5 vCPU constraint, prevents CPU starvation
    - remove=True           -> ephemeral filesystem, wiped instantly on stop
    - tty=True / stdin_open=True -> interactive bash TTY for the student
"""

import asyncio
import logging
import uuid
from functools import partial
from typing import Optional

import docker
from docker.errors import APIError, NotFound

logger = logging.getLogger("cyberrange.docker_controller")
logging.basicConfig(level=logging.INFO)

# Single shared client bound to the host's Docker daemon socket
# (mounted read/write into this container via docker-compose.yml).
client = docker.from_env()

SANDBOX_IMAGE = "ubuntu:latest"
CONTAINER_PREFIX = "cyberrange-sandbox"


class SandboxError(Exception):
    """Raised for any failure during sandbox provisioning or teardown."""


def _boot_sandbox_sync(username: str) -> dict:
    """
    Synchronous worker: creates and starts an isolated, interactive
    Ubuntu sandbox for the given student and returns its identity/port.
    """
    container_name = f"{CONTAINER_PREFIX}-{username}-{uuid.uuid4().hex[:8]}"

    try:
        container = client.containers.run(
            image=SANDBOX_IMAGE,
            name=container_name,
            command="/bin/bash",
            detach=True,
            tty=True,
            stdin_open=True,
            network_mode="none",
            mem_limit="512m",
            nano_cpus=500_000_000,
            remove=True,
            ports={"22/tcp": None},  # dynamic host port allocation
            labels={
                "cyberrange.owner": username,
                "cyberrange.role": "student-sandbox",
            },
        )
    except APIError as exc:
        logger.error("Docker API error while booting sandbox for %s: %s", username, exc)
        raise SandboxError(f"Failed to boot sandbox for '{username}': {exc}") from exc

    # Refresh container attributes so port bindings (assigned at start time)
    # are populated before we try to read them.
    container.reload()

    host_port: Optional[int] = None
    port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})
    tcp_binding = port_bindings.get("22/tcp")

    if tcp_binding:
        host_port = int(tcp_binding[0]["HostPort"])

    if host_port is None:
        # network_mode="none" strips all port publishing at the network
        # layer, so no host port will ever be allocated in that mode.
        # This is expected/by-design for a fully isolated sandbox — the
        # caller should treat access as exec-based (docker exec), not
        # network-based (ssh). host_port is returned as None in that case.
        logger.info(
            "Sandbox '%s' started with network_mode='none' — no host port "
            "was allocated (network isolation is intentional).",
            container_name,
        )

    return {
        "container_name": container_name,
        "container_id": container.id,
        "host_port": host_port,
        "status": container.status,
    }


def _terminate_sandbox_sync(container_name: str) -> dict:
    """
    Synchronous worker: force-stops and removes the target sandbox.
    Because containers are booted with remove=True, stopping them also
    triggers Docker's automatic cleanup of the writable layer.
    """
    try:
        container = client.containers.get(container_name)
    except NotFound as exc:
        logger.warning("Terminate requested for unknown container '%s'", container_name)
        raise SandboxError(f"Container '{container_name}' not found") from exc

    try:
        container.stop(timeout=2)
    except APIError as exc:
        logger.error("Docker API error while stopping '%s': %s", container_name, exc)
        raise SandboxError(f"Failed to terminate '{container_name}': {exc}") from exc

    return {"container_name": container_name, "status": "terminated"}


async def boot_student_sandbox(username: str) -> dict:
    """
    Async-compatible entrypoint: spawns an isolated, interactive
    'ubuntu:latest' sandbox for `username` and returns its metadata,
    including the auto-allocated host port (if any).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_boot_sandbox_sync, username))


async def terminate_student_sandbox(container_name: str) -> dict:
    """
    Async-compatible entrypoint: force-stops and erases the targeted
    sandbox container by name.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_terminate_sandbox_sync, container_name))
