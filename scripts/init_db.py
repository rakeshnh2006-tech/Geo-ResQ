#!/usr/bin/env python3
"""
scripts/init_db.py
Run once on deployment to create all tables.
Usage: python scripts/init_db.py
"""
import os
import sys

# Ensure production config
os.environ.setdefault("FLASK_ENV", "production")

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import create_app, db
import backend.models  # noqa: F401 — registers all models with metadata

app = create_app("production")
with app.app_context():
    db.create_all()
    print("✅ Database tables created successfully.")
