import pytest
from flask.testing import FlaskClient

from app import create_app
from app.config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture
def app():
    return create_app(TestConfig)


@pytest.fixture
def client(app) -> FlaskClient:
    return app.test_client()
