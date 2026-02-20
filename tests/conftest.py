"""Shared test fixtures."""

from __future__ import annotations

import os
import tempfile

import pytest

# Override DATABASE_PATH before importing modules
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_PATH"] = _tmp_db.name
_tmp_db.close()

from database import init_db, get_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset database before each test."""
    os.environ["DATABASE_PATH"] = _tmp_db.name
    # Drop all tables and recreate
    import database
    database.DATABASE_PATH = _tmp_db.name
    with get_db() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS sync_log;
            DROP TABLE IF EXISTS site_daily;
            DROP TABLE IF EXISTS keyword_data;
            DROP TABLE IF EXISTS sites;
        """)
    init_db()
    yield
    # Cleanup handled by autouse


@pytest.fixture
def app_client():
    """Flask test client."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def logged_in_client(app_client):
    """Flask test client that's already logged in."""
    from config import DASHBOARD_PASSWORD
    app_client.post("/login", data={"password": DASHBOARD_PASSWORD})
    return app_client
