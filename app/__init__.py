from flask import Flask

from app.config import Config
from app.extensions import csrf, db, migrate


def create_app(config: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Models without blueprints are imported here so they register with db.metadata.
    from app.clients.routes import bp as clients_bp
    from app.dashboard.routes import bp as dashboard_bp
    from app.models import obligation, staff  # noqa: F401

    app.register_blueprint(clients_bp)
    app.register_blueprint(dashboard_bp)

    @app.get("/")
    def index() -> tuple[str, int]:
        return "DJ Meyer PMS — ok", 200

    return app
