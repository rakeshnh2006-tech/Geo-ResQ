"""
backend/utils/decorators.py
Custom Flask route decorators for role-based access control.
"""
from __future__ import annotations

import functools

from flask import abort
from flask_login import current_user


def coordinator_required(fn):
    """Restrict a view to authenticated coordinators.

    Must be applied *after* @login_required so current_user is already
    populated when this decorator runs.

    Usage::

        @coordinator_bp.get("/dashboard")
        @login_required
        @coordinator_required
        def dashboard(): ...
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_coordinator:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper
