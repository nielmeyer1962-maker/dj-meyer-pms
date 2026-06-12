import os

from dotenv import load_dotenv

load_dotenv()

# The default SECRET_KEY — a deliberately obvious placeholder. validate_secret_key()
# refuses to start with this (or an empty key) outside TESTING / FLASK_DEBUG, so a real
# deployment can never run on a guessable session-signing key.
PLACEHOLDER_SECRET_KEY = "change-me-in-production"


def _is_debug_env() -> bool:
    return os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def validate_secret_key(app) -> None:
    """Fail hard at startup if SECRET_KEY is unset or still the placeholder, unless we are
    testing or running in debug. Called from create_app after the config is loaded."""
    if app.config.get("TESTING") or _is_debug_env():
        return
    secret = app.config.get("SECRET_KEY")
    if not secret or secret == PLACEHOLDER_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is unset or still the placeholder "
            f"{PLACEHOLDER_SECRET_KEY!r}. Set a strong, unique SECRET_KEY in the "
            "environment before running outside TESTING / FLASK_DEBUG."
        )


class Config:
    SECRET_KEY: str = os.environ.get("SECRET_KEY", PLACEHOLDER_SECRET_KEY)
    # Default matches the local dev Postgres on :5433 (see CLAUDE.md). Overridden by
    # DATABASE_URL in every real environment; this fallback just shouldn't be wrong.
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "postgresql://localhost:5433/djmeyer_pms"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    MAIL_SERVER: str = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT: int = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS: bool = True
    MAIL_USERNAME: str | None = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD: str | None = os.environ.get("MAIL_PASSWORD")
