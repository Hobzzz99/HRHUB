"""Shared test configuration.

Sets environment BEFORE any app import so settings, the DB engine, and auth pick
up test-friendly values (SQLite, disabled auth, eager Celery, a valid Fernet key).
"""

from __future__ import annotations

import os
import pathlib

from cryptography.fernet import Fernet

_TEST_DB = pathlib.Path(__file__).parent / "_test_app.db"

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_TEST_DB.as_posix()}")
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("PROVIDER", "mock")
os.environ.setdefault("AI_MATCHING", "off")
os.environ.setdefault("CREDENTIAL_ENC_KEY", Fernet.generate_key().decode())

import pytest  # noqa: E402

from app.db import models  # noqa: E402,F401  (registers tables on Base.metadata)
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402

# Run Celery tasks inline (no broker) so the end-to-end flow completes in-process.
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    Base.metadata.create_all(engine)
    yield
    # Dispose so SQLite releases the file lock before we delete it (Windows).
    engine.dispose()
    if _TEST_DB.exists():
        _TEST_DB.unlink()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all tables between tests for isolation."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
