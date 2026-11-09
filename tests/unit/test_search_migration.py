from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from services.common.config import get_settings


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_postgres_web_search_migration_uses_in_place_alter(monkeypatch, direction):
    root = Path(__file__).resolve().parents[2]
    output = io.StringIO()
    config = Config(str(root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/migration_test")
    get_settings.cache_clear()

    if direction == "upgrade":
        command.upgrade(config, "20261027_0002:20261109_0003", sql=True)
    else:
        command.downgrade(config, "20261109_0003:20261027_0002", sql=True)

    sql = output.getvalue()
    assert "ALTER TABLE search_jobs" in sql
    assert "ALTER TABLE candidates" in sql
    assert "DROP TABLE search_jobs" not in sql
    assert "DROP TABLE candidates" not in sql
    assert "DROP CONSTRAINT search_jobs_pkey" not in sql
    assert "DROP CONSTRAINT candidates_pkey" not in sql
    assert "_alembic_tmp" not in sql


def test_sqlite_web_search_migration_round_trip(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'migration.db'}")
    get_settings.cache_clear()
    application_logger = logging.getLogger("services.common.storage")
    assert not application_logger.disabled

    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "20261027_0002")
    command.upgrade(config, "head")
    command.check(config)
    assert not application_logger.disabled
