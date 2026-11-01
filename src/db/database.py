"""Database engine, session factory, declarative base, and SQLite pragma configuration.

Provides connection pragmas for SQLite (foreign keys, WAL mode, synchronous normal)
and exports session management utilities.
"""

import sqlite3
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from src.core.config import settings


def register_sqlite_pragmas(target_engine: Engine) -> None:
    """Attach connection listeners to enforce SQLite foreign keys, WAL mode, and normal sync.

    Applies safely to sqlite3.Connection instances only. Setting journal_mode=WAL on an
    already-WAL database is a safe no-op that returns 'wal'.
    """
    @event.listens_for(target_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")
            finally:
                cursor.close()


# Resolve connect_args based on database dialect
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Primary application engine
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=getattr(settings, "debug", False),
)

# Apply SQLite pragmas if the active configuration uses SQLite
if settings.database_url.startswith("sqlite"):
    register_sqlite_pragmas(engine)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.0 ORM entities."""
    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency provider yielding transactional database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()