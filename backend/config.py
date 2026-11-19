import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    WTF_CSRF_ENABLED = True

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "")
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


config_map = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
