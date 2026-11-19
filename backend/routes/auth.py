"""
backend/routes/auth.py
Flask-Login authentication routes:
  GET/POST /auth/register  — citizen self-registration
  GET/POST /auth/login     — all users
  POST     /auth/logout    — authenticated users
  GET      /admin/users    — coordinator: list users
  POST     /admin/users/<id>/toggle  — coordinator: activate/deactivate
  POST     /admin/users/invite       — coordinator: create coordinator account
"""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from backend.app import db
from backend.models.user import User, UserRole
from backend.utils.decorators import coordinator_required
from backend.utils.forms import InviteCoordinatorForm, LoginForm, RegisterForm

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------------------------
# Self-registration (citizens only)
# ---------------------------------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(_next_safe())

    form = RegisterForm()
    if form.validate_on_submit():
        if db.session.scalar(select(User).where(User.email == form.email.data)):
            flash("An account with that email already exists.", "warning")
            return render_template("auth/register.html", form=form)

        user = User(
            email=form.email.data.lower().strip(),
            full_name=form.full_name.data.strip(),
            role=UserRole.citizen,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Account created. Welcome!", "success")
        return redirect(url_for("public.index"))

    return render_template("auth/register.html", form=form)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_next_safe())

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            select(User).where(User.email == form.email.data.lower().strip())
        )
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            flash(f"Welcome back, {user.full_name}.", "success")
            return redirect(_next_safe())

        flash("Invalid email or password.", "danger")

    return render_template("auth/login.html", form=form)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Admin — user management (coordinators only)
# ---------------------------------------------------------------------------

@auth_bp.route("/admin/users", methods=["GET"])
@login_required
@coordinator_required
def admin_users():
    users = db.session.scalars(select(User).order_by(User.created_at.desc())).all()
    invite_form = InviteCoordinatorForm()
    return render_template("auth/admin_users.html", users=users, invite_form=invite_form)


@auth_bp.post("/admin/users/<int:user_id>/toggle")
@login_required
@coordinator_required
def admin_toggle_user(user_id: int):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        return jsonify({"error": {"code": "FORBIDDEN", "message": "Cannot deactivate yourself."}}), 403
    user.is_active = not user.is_active
    db.session.commit()
    state = "activated" if user.is_active else "deactivated"
    flash(f"User {user.email} has been {state}.", "success")
    return redirect(url_for("auth.admin_users"))


@auth_bp.post("/admin/users/invite")
@login_required
@coordinator_required
def admin_invite_coordinator():
    form = InviteCoordinatorForm()
    if form.validate_on_submit():
        if db.session.scalar(select(User).where(User.email == form.email.data)):
            flash("An account with that email already exists.", "warning")
            return redirect(url_for("auth.admin_users"))

        user = User(
            email=form.email.data.lower().strip(),
            full_name=form.full_name.data.strip(),
            role=UserRole.coordinator,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f"Coordinator account created for {user.email}.", "success")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                flash(err, "danger")

    return redirect(url_for("auth.admin_users"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_safe() -> str:
    """Return `next` query param only if it's a safe relative URL."""
    next_url = request.args.get("next", "")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    if current_user.is_coordinator:
        return url_for("coordinator.dashboard")
    return url_for("public.index")
