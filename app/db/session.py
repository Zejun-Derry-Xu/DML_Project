from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, **kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def database_is_ready(session: Session) -> bool:
    # A reachable but unmigrated database cannot serve return workflows.
    from app.db import models  # noqa: F401

    session.execute(text("SELECT 1"))
    inspector = inspect(session.connection())
    if not set(Base.metadata.tables) <= set(inspector.get_table_names()):
        raise SQLAlchemyError("Required application tables are missing")
    for name, table in Base.metadata.tables.items():
        existing = {column["name"] for column in inspector.get_columns(name)}
        if not set(table.columns.keys()) <= existing:
            raise SQLAlchemyError(f"Required columns are missing from {name}")
    return True
