from flask import Flask

from app.config import Config
from app.extensions import csrf, db, migrate


def create_app(config: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Register models with db.metadata. The clients blueprint loads Client
    # transitively; ObligationInstance has no blueprint yet, so import it explicitly.
    from app.models import obligation  # noqa: F401

    from app.clients.routes import bp as clients_bp

    app.register_blueprint(clients_bp)

    @app.get("/")
    def index() -> tuple[str, int]:
        return "DJ Meyer PMS — ok", 200

    return app
