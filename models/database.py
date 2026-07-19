"""
SQLAlchemy declarative data layer for the Cyber Range platform.

This module defines the engine, session factory, declarative base, and the
two foundational tables required for Phase 1:

    - Users:             account records, role-based access, 2FA state,
                          and soft-deletion metadata for audit trails.
    - ActiveContainers:   live mapping of running student sandbox
                          containers to their owning user and host port.
"""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Boolean,
    Integer,
    ForeignKey,
    DateTime,
    Enum as SqlEnum,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
import enum

# ---------------------------------------------------------------------------
# Engine / Session configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://cyberrange_admin:changeme_in_prod@db:5432/cyberrange_db",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # verifies dead connections are recycled, not reused
    pool_size=10,
    max_overflow=20,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a scoped DB session and guarantees closure."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates all tables. Idempotent — safe to call on every boot."""
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    admin = "admin"
    student = "student"


# ---------------------------------------------------------------------------
# Table 1: Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    pass_hash = Column(String(255), nullable=False)

    role = Column(
        SqlEnum(UserRole, name="user_role_enum"),
        nullable=False,
        default=UserRole.student,
    )

    profile_bio = Column(Text, nullable=True)

    active_2fa_secret = Column(String(64), nullable=True)
    is_2fa_enabled = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    containers = relationship(
        "ActiveContainer",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User username={self.username} role={self.role.value}>"


# ---------------------------------------------------------------------------
# Table 2: ActiveContainers
# ---------------------------------------------------------------------------

class ActiveContainer(Base):
    __tablename__ = "active_containers"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    container_name = Column(String(128), unique=True, nullable=False, index=True)
    host_port = Column(Integer, nullable=False)
    spawned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    owner = relationship("User", back_populates="containers")

    def __repr__(self) -> str:
        return f"<ActiveContainer name={self.container_name} port={self.host_port}>"
