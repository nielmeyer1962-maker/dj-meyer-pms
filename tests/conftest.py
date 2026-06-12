import os

import pytest
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.config import Config
from app.extensions import db as _db


class TestConfig(Config):
    TESTING = True
    # Default to an in-memory SQLite DB for fast local runs; CI sets TEST_DATABASE_URL to a
    # Postgres URL so the suite also runs against the production database engine.
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    WTF_CSRF_ENABLED = False


# SQLite ignores foreign-key constraints unless explicitly enabled per connection.
# Without this, ON DELETE SET NULL and ON DELETE RESTRICT are schema-only and
# never fire at runtime — exactly what we need to assert in tests. CI uses
# Postgres, which enforces FKs unconditionally; the dialect check keeps the
# PRAGMA from being issued to psycopg2.
@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # pragma: no cover
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture
def client(app) -> FlaskClient:
    return app.test_client()
