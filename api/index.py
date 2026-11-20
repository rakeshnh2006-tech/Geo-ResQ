"""
api/index.py
Vercel serverless entry point.
Vercel's Python runtime looks for a WSGI app in api/index.py exposed as `app`.
"""
import os
import shutil
import sys
import urllib.parse
from pathlib import Path

# Add repo root to path so `backend` package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

# Set Vercel & production environment markers
os.environ.setdefault("VERCEL", "1")
os.environ.setdefault("FLASK_ENV", "production")

# Ensure writable temporary directories on serverless filesystem
for d in ["/tmp/uploads", "/tmp/briefings"]:
    os.makedirs(d, exist_ok=True)

# If no remote DATABASE_URL provided, copy pre-seeded SQLite DB to /tmp so it's writable
current_db_url = os.environ.get("DATABASE_URL", "")
if not current_db_url or current_db_url.startswith("sqlite:///georesq"):
    tmp_db = Path("/tmp/georesq_dev.db")
    bundled_db = repo_root / "instance" / "georesq_dev.db"
    if not tmp_db.exists():
        if bundled_db.exists():
            shutil.copy2(bundled_db, tmp_db)
        else:
            tmp_db.touch()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"

from backend.app import create_app, db

flask_app = create_app("production")

# Auto-initialize and seed database on cold start if needed
with flask_app.app_context():
    try:
        db.create_all()
        from scripts.seed_db import seed
        seed()
    except Exception as exc:
        print(f"Startup DB init notice: {exc}")


class VercelGatewayMiddleware:
    """
    WSGI middleware for Vercel Serverless Python deployments.
    Restores the client-requested PATH_INFO and cleans QUERY_STRING
    when Vercel rewrite rules route incoming traffic to /api/index.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __getattr__(self, name):
        return getattr(self.wsgi_app, name)

    def __call__(self, environ, start_response):
        qs = environ.get("QUERY_STRING", "")
        parsed = urllib.parse.parse_qs(qs, keep_blank_values=True)

        if "__vercel_path" in parsed:
            target_path = parsed.pop("__vercel_path")[0]
            if not target_path or target_path == "/":
                environ["PATH_INFO"] = "/"
            else:
                environ["PATH_INFO"] = ("/" + target_path.lstrip("/")).split("?")[0]

            clean_pairs = []
            for k, vals in parsed.items():
                for v in vals:
                    clean_pairs.append(f"{urllib.parse.quote(k)}={urllib.parse.quote(v)}")
            environ["QUERY_STRING"] = "&".join(clean_pairs)
        else:
            path = environ.get("PATH_INFO", "")
            if path in ("/api/index", "/api/index.py", "/api", ""):
                orig = (
                    environ.get("HTTP_X_FORWARDED_URI")
                    or environ.get("HTTP_X_MATCHED_PATH")
                    or environ.get("HTTP_X_ORIGINAL_URI")
                )
                if orig and orig not in ("/api/index", "/api/index.py", "/api"):
                    environ["PATH_INFO"] = ("/" + orig.lstrip("/")).split("?")[0]
                elif environ.get("HTTP_X_NOW_ROUTE_MATCHES"):
                    matches = urllib.parse.parse_qs(environ["HTTP_X_NOW_ROUTE_MATCHES"])
                    if "1" in matches and matches["1"]:
                        environ["PATH_INFO"] = "/" + matches["1"][0].lstrip("/")
                    else:
                        environ["PATH_INFO"] = "/"
                else:
                    environ["PATH_INFO"] = "/"
            elif path.startswith("/api/index/"):
                environ["PATH_INFO"] = path[len("/api/index"):]
            elif path.startswith("/api/index.py/"):
                environ["PATH_INFO"] = path[len("/api/index.py"):]

        if not environ.get("PATH_INFO", "").startswith("/"):
            environ["PATH_INFO"] = "/" + environ.get("PATH_INFO", "")

        return self.wsgi_app(environ, start_response)


# Expose `app` for Vercel's Python runtime
app = VercelGatewayMiddleware(flask_app)
