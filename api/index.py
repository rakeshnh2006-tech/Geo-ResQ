"""
api/index.py
Vercel serverless entry point.
Vercel's Python runtime looks for a WSGI app in api/index.py exposed as `app`.
"""
import os
import shutil
import sys
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

app = create_app("production")

# Auto-initialize and seed database on cold start if needed
with app.app_context():
    try:
        db.create_all()
        from scripts.seed_db import seed
        seed()
    except Exception as exc:
        print(f"Startup DB init notice: {exc}")
