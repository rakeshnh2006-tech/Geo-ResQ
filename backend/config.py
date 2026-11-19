import os
from dotenv import load_dotenv

load_dotenv()

# Render.com gives DATABASE_URL as postgres:// but SQLAlchemy 2.x needs postgresql://
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    os.environ["DATABASE_URL"] = _db_url


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    WTF_CSRF_ENABLED = True

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///georesq_dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # IBM watsonx.ai
    WATSONX_API_KEY = os.environ.get("WATSONX_API_KEY", "")
    WATSONX_URL = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    WATSONX_PROJECT_ID = os.environ.get("WATSONX_PROJECT_ID", "")
    WATSONX_MODEL_ID = os.environ.get("WATSONX_MODEL_ID", "ibm/granite-13b-instruct-v2")

    # Rate limiting
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = "200 per hour"

    # Google Maps
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

    # Upload folder — on Vercel/serverless only /tmp is writable
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        "/tmp/uploads" if os.environ.get("VERCEL") else "frontend/static/uploads",
    )
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB max request

    # PDF output dir — on Vercel only /tmp is writable
    PDF_DIR = os.environ.get(
        "PDF_DIR",
        "/tmp/briefings" if os.environ.get("VERCEL") else "instance/briefings",
    )


class DevelopmentConfig(Config):
    DEBUG = True
    WTF_CSRF_ENABLED = False  # disabled for easier API testing in dev


class TestingConfig(Config):
    TESTING = True
    # StaticPool keeps a single connection for the entire test so that all
    # nested app-context pushes share the same in-memory SQLite DB.
    # Without this, Flask-SQLAlchemy's teardown_appcontext removes the session
    # on every inner context pop, and the next request opens a fresh blank DB.
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": __import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    }
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret-key"
    WATSONX_API_KEY = "test-key"
    WATSONX_PROJECT_ID = "test-project"


class ProductionConfig(Config):
    DEBUG = False
    # In production, DATABASE_URL must be set as an environment variable
    # (Render, Railway, Heroku all inject it automatically)


config_map = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
