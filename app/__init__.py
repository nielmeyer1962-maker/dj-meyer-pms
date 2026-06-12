from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user

from app.config import Config, validate_secret_key
from app.extensions import csrf, db, login_manager, migrate

# Endpoints reachable without logging in: the login view, static assets, and the bare
# "/" health line. Everything else is gated.
_PUBLIC_ENDPOINTS = frozenset({"auth.login", "static", "index"})


def _register_login_wall(app: Flask) -> None:
    """App-wide gate: any request to a non-public endpoint must be authenticated, else it
    redirects to the login page carrying a safe `next`."""

    @app.before_request
    def _require_login():  # noqa: ANN202
        if request.endpoint is None or request.endpoint in _PUBLIC_ENDPOINTS:
            return None
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
        return None


def _register_error_handlers(app: Flask) -> None:
    """Friendly 404/500 pages. The 500 handler rolls the session back (so a poisoned
    transaction doesn't bleed into the next request) and renders a static template — it
    never echoes the exception, so no stack trace can leak to a user even if DEBUG is on."""

    @app.errorhandler(404)
    def not_found(error):  # noqa: ANN001, ANN202
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(error):  # noqa: ANN001, ANN202
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def internal_error(error):  # noqa: ANN001, ANN202
        db.session.rollback()
        return render_template("errors/500.html"), 500


def create_app(config: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    validate_secret_key(app)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    # Models without blueprints are imported here so they register with db.metadata.
    from app.auth.routes import bp as auth_bp
    from app.clients.routes import bp as clients_bp
    from app.dashboard.routes import bp as dashboard_bp
    from app.models import (  # noqa: F401
        app_setting,
        cipc,
        cipc_ar_fee,
        obligation,
        staff,
        status_event,
    )
    from app.settings.routes import bp as settings_bp
    from app.tasks.routes import bp as tasks_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(settings_bp)

    _register_error_handlers(app)
    _register_login_wall(app)

    from app.cli import staff_cli

    app.cli.add_command(staff_cli)

    @app.get("/")
    def index() -> tuple[str, int]:
        return "DJ Meyer PMS — ok", 200

    return app
