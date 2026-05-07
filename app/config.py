import os


class Config:
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "postgresql://localhost/djmeyer_pms"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    MAIL_SERVER: str = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT: int = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS: bool = True
    MAIL_USERNAME: str | None = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD: str | None = os.environ.get("MAIL_PASSWORD")
