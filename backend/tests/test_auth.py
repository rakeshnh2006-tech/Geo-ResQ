"""
backend/tests/test_auth.py
Tests for ST-04 — Authentication & User Management.
All tests use the in-memory SQLite testing config; no real DB needed.
"""
from __future__ import annotations

import os
import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.app import create_app, db
from backend.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Fixtures — function scope so each test gets a clean DB + fresh client
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        import backend.models  # register all models
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _register(client, email="user@test.dev", password="Password1!",
              name="Test User"):
    return client.post("/auth/register", data={
        "full_name": name,
        "email": email,
        "password": password,
        "confirm_password": password,
    }, follow_redirects=True)


def _login(client, email, password="Password1!"):
    return client.post("/auth/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=True)


def _add_user(app, email, password="Password1!", name="U",
               role=UserRole.citizen, is_active=True):
    with app.app_context():
        u = User(email=email, full_name=name, role=role, is_active=is_active)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u.id


# ---------------------------------------------------------------------------
# User model — password helpers
# ---------------------------------------------------------------------------

class TestUserModel:
    def test_set_and_check_password(self, app):
        with app.app_context():
            u = User(email="x@x.dev", full_name="X", role=UserRole.citizen)
            u.set_password("Secret99!")
            assert u.check_password("Secret99!")
            assert not u.check_password("wrong")

    def test_is_coordinator_flag(self, app):
        with app.app_context():
            citizen = User(email="c@c.dev", full_name="C", role=UserRole.citizen)
            coord   = User(email="k@k.dev", full_name="K", role=UserRole.coordinator)
            assert not citizen.is_coordinator
            assert coord.is_coordinator


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_success(self, client, app):
        resp = _register(client)
        assert resp.status_code == 200
        with app.app_context():
            u = db.session.query(User).filter_by(email="user@test.dev").first()
            assert u is not None
            assert u.role == UserRole.citizen

    def test_register_duplicate_email(self, client, app):
        # Pre-insert a user directly so the DB record is definitely committed
        _add_user(app, email="dup@test.dev")
        resp = client.post("/auth/register", data={
            "full_name": "Another User", "email": "dup@test.dev",
            "password": "Password1!", "confirm_password": "Password1!",
        }, follow_redirects=True)
        assert b"already exists" in resp.data

    def test_register_password_mismatch(self, client):
        resp = client.post("/auth/register", data={
            "full_name": "A", "email": "mismatch@test.dev",
            "password": "Password1!", "confirm_password": "Different1!",
        }, follow_redirects=True)
        assert b"must match" in resp.data

    def test_register_weak_password(self, client):
        resp = client.post("/auth/register", data={
            "full_name": "A", "email": "weak@test.dev",
            "password": "alllower1!", "confirm_password": "alllower1!",
        }, follow_redirects=True)
        assert b"uppercase" in resp.data


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_success(self, client, app):
        _add_user(app, "login@test.dev")
        resp = _login(client, "login@test.dev")
        assert resp.status_code == 200
        assert b"Welcome back" in resp.data

    def test_login_wrong_password(self, client, app):
        _add_user(app, "wp@test.dev")
        resp = _login(client, "wp@test.dev", password="Wrong1!")
        assert b"Invalid" in resp.data

    def test_login_inactive_user(self, client, app):
        _add_user(app, "inactive@test.dev", is_active=False)
        resp = _login(client, "inactive@test.dev")
        assert b"Invalid" in resp.data


# ---------------------------------------------------------------------------
# coordinator_required decorator
# ---------------------------------------------------------------------------

class TestCoordinatorRequired:
    def test_citizen_cannot_access_admin(self, client, app):
        _add_user(app, "cit@test.dev", role=UserRole.citizen)
        _login(client, "cit@test.dev")
        resp = client.get("/auth/admin/users")
        assert resp.status_code == 403

    def test_coordinator_can_access_admin(self, client, app):
        _add_user(app, "coord@test.dev", role=UserRole.coordinator)
        _login(client, "coord@test.dev")
        resp = client.get("/auth/admin/users")
        assert resp.status_code == 200

    def test_anonymous_redirected_to_login(self, client):
        resp = client.get("/auth/admin/users")
        assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Toggle user active/inactive
# ---------------------------------------------------------------------------

class TestToggleUser:
    def test_coordinator_can_toggle_citizen(self, client, app):
        _add_user(app, "tc@test.dev", role=UserRole.coordinator)
        cit_id = _add_user(app, "tu@test.dev", role=UserRole.citizen)
        _login(client, "tc@test.dev")
        resp = client.post(f"/auth/admin/users/{cit_id}/toggle",
                           follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            updated = db.session.get(User, cit_id)
            assert updated.is_active is False

    def test_coordinator_cannot_deactivate_self(self, client, app):
        coord_id = _add_user(app, "self@test.dev", role=UserRole.coordinator)
        _login(client, "self@test.dev")
        resp = client.post(f"/auth/admin/users/{coord_id}/toggle")
        assert resp.status_code == 403
