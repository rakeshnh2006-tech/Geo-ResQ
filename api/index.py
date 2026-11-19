"""
api/index.py
Vercel serverless entry point.
Vercel's Python runtime looks for a WSGI app in api/index.py exposed as `app`.
"""
import os
import sys

# Add repo root to path so `backend` package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import create_app

app = create_app("production")
