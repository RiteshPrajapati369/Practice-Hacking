"""
Cyber Range backend entrypoint (Phase 1).

Auth routes, WebSocket terminal streaming, and sandbox-management
endpoints are intentionally deferred to subsequent phases. This module
only wires up the FastAPI app, initializes the database schema on boot,
and exposes a /health endpoint for the docker-compose healthcheck.
"""

from fastapi import FastAPI

from models.database import init_db

app = FastAPI(title="Cyber Range API", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
