"""Chunk 4 (H1): config fails hard on a placeholder/empty SECRET_KEY, unless TESTING or
FLASK_DEBUG."""

from __future__ import annotations

import pytest

from app import create_app
from app.config import PLACEHOLDER_SECRET_KEY, Config


class _PlaceholderConfig(Config):
    # No TESTING flag; force the placeholder regardless of the ambient environment.
    SECRET_KEY = PLACEHOLDER_SECRET_KEY


class _EmptyConfig(Config):
    SECRET_KEY = ""


class _TestingPlaceholderConfig(Config):
    TESTING = True
    SECRET_KEY = PLACEHOLDER_SECRET_KEY


def test_create_app_raises_on_placeholder_secret(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    with pytest.raises(RuntimeError):
        create_app(_PlaceholderConfig)


def test_create_app_raises_on_empty_secret(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    with pytest.raises(RuntimeError):
        create_app(_EmptyConfig)


def test_create_app_ok_when_testing_even_with_placeholder(monkeypatch):
    """TESTING configs (like the suite's TestConfig) are exempt — the placeholder is fine."""
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    app = create_app(_TestingPlaceholderConfig)
    assert app is not None


def test_create_app_ok_in_debug_even_with_placeholder(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "1")
    app = create_app(_PlaceholderConfig)
    assert app is not None


def test_create_app_ok_with_real_secret(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)

    class RealSecretConfig(Config):
        SECRET_KEY = "a-real-strong-unique-key"

    app = create_app(RealSecretConfig)
    assert app is not None
