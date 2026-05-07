from flask import Flask

from app.config import Config


def create_app(config: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    @app.get("/")
    def index() -> tuple[str, int]:
        return "DJ Meyer PMS — ok", 200

    return app
