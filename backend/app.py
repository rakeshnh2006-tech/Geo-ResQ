import os
import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pythonjsonlogger import jsonlogger

from backend.config import config_map

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def create_app(env: str | None = None) -> Flask:
    env = env or os.environ.get("FLASK_ENV", "production")
    cfg = config_map[env]

    base_dir = os.path.abspath(os.path.dirname(__file__))
    template_dir = os.path.abspath(os.path.join(base_dir, "..", "frontend", "templates"))
    static_dir = os.path.abspath(os.path.join(base_dir, "..", "frontend", "static"))

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
    )
    app.config.from_object(cfg)

    @app.route("/static/uploads/<path:filename>")
    def _serve_uploaded_file(filename):
        from flask import send_from_directory
        for d in ["/tmp/uploads", os.path.join(static_dir, "uploads")]:
            if os.path.exists(os.path.join(d, filename)):
                return send_from_directory(d, filename)
        return send_from_directory(os.path.join(static_dir, "uploads"), filename)

    _configure_logging(app)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    with app.app_context():
        _register_blueprints(app)

    return app


def _configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO if not app.debug else logging.DEBUG)


def _register_blueprints(app: Flask) -> None:
    from backend.routes.auth import auth_bp
    from backend.routes.public import public_bp
    from backend.routes.api_incidents import incidents_bp
    from backend.routes.api_relief import relief_bp
    from backend.routes.api_prioritization import prioritization_bp
    from backend.routes.api_briefings import briefings_bp
    from backend.routes.api_roads import roads_bp
    from backend.routes.api_photos import photos_bp
    from backend.routes.coordinator import coordinator_bp
    from backend.routes.health import health_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(incidents_bp, url_prefix="/api")
    app.register_blueprint(relief_bp, url_prefix="/api")
    app.register_blueprint(prioritization_bp, url_prefix="/api")
    app.register_blueprint(briefings_bp, url_prefix="/api")
    app.register_blueprint(roads_bp, url_prefix="/api")
    app.register_blueprint(photos_bp, url_prefix="/api")
    app.register_blueprint(coordinator_bp, url_prefix="/coordinator")

    # Exempt multipart photo uploads from CSRF (JS fetch sends X-CSRFToken header)
    csrf.exempt(photos_bp)

    _register_error_handlers(app)


def _register_error_handlers(app: Flask) -> None:
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": {"code": "BAD_REQUEST", "message": str(e)}}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": {"code": "UNAUTHORIZED", "message": str(e)}}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": {"code": "FORBIDDEN", "message": str(e)}}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": {"code": "NOT_FOUND", "message": str(e)}}), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": {"code": "RATE_LIMITED", "message": str(e)}}), 429

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}}), 500
