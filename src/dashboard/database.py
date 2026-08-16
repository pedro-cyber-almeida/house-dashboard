"""Engine and session helpers backed by SQLite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (register tables on metadata)
from .config import DATA_DIR, get_settings

# (table, column) -> ALTER statement. Additive-only upgrade path for
# databases created before the column, which still carry it under its
# original Portuguese name; `create_all` never alters existing tables.
_COLUMN_UPGRADES = {
    ("services", "categoria"): "ALTER TABLE services ADD COLUMN categoria VARCHAR(64)",
    ("user_services", "ordem"): "ALTER TABLE user_services ADD COLUMN ordem INTEGER",
}

# One-time Portuguese -> English column renames. Applied only while the old
# column still exists and the new one does not, so fresh databases
# (already created with the English names) and migrated ones are untouched.
_COLUMN_RENAMES = [
    ("services", "nome", "name"),
    ("services", "descricao", "description"),
    ("services", "icone", "icon"),
    ("services", "categoria", "category"),
    ("user_services", "ordem", "position"),
    ("users", "ativo", "active"),
]


def _build_engine():
    db_url = get_settings().database_url
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    # check_same_thread is safe here: each request opens its own Session.
    return create_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )


engine = _build_engine()


def _ensure_columns() -> None:
    """Bring long-lived databases up to the current schema (idempotent).

    Historical steps, each a no-op once applied:
    1. ADD COLUMN for databases that predate a column (original spelling);
    2. the one-time Portuguese -> English column renames;
    3. the category index (recreated under its current name) and the
       legacy-role cleanup.
    """
    with engine.begin() as conn:
        for (table, column), statement in _COLUMN_UPGRADES.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if column not in existing:
                conn.execute(text(statement))
        for table, old, new in _COLUMN_RENAMES:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if old in existing and new not in existing:
                conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))
        # Renamed from its Portuguese spelling; DROP/CREATE keeps one index
        # under the current name no matter how the table arrived here.
        conn.execute(text("DROP INDEX IF EXISTS ix_services_categoria"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_services_category ON services (category)"))
        # The "guest" role no longer exists; fold any legacy rows into "user"
        # so the strict Role enum stays valid on old databases.
        conn.execute(text("UPDATE users SET role='user' WHERE role NOT IN ('admin','user')"))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
