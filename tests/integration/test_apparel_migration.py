"""Migration on a real SQLite file (not a substitute for PostgreSQL/cloud verification)."""

import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).parents[2]


def test_additive_migration_preserves_old_records_and_schema(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    env = {**os.environ, "DATABASE_URL": url}
    python = str(ROOT / ".venv/bin/python")
    subprocess.run(
        [python, "-m", "alembic", "upgrade", "0002"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO return_cases (id, session_id, status, version) "
                "VALUES (:id, :session, 'closed', 1)"
            ),
            {"id": "a" * 32, "session": "b" * 32},
        )
    subprocess.run(
        [python, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, stained, tags_attached, policy_version FROM return_cases")
        ).one()
        assert tuple(row) == ("closed", None, None, "mvp-1.0.0")
    assert "category" in {column["name"] for column in inspect(engine).get_columns("order_items")}
    checked = subprocess.run(
        [python, "-m", "alembic", "check"], cwd=ROOT, env=env, text=True, capture_output=True
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
