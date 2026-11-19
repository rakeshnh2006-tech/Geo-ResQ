import os
os.environ["FLASK_ENV"] = "testing"
from backend.app import create_app, db
from backend.models.user import User, UserRole
from sqlalchemy import select
import pytest

# Exactly replicate what pytest does for the test
# app fixture → client fixture → coordinator_client fixture → test method

app_instance = create_app("testing")

# -- app fixture --
app_ctx = app_instance.app_context()
app_ctx.push()
import backend.models
db.create_all()
print("After create_all, tables:", db.engine.table_names() if hasattr(db.engine, 'table_names') else "N/A")

# -- client fixture --
test_client = app_instance.test_client()

# -- coordinator_client fixture --
inner_ctx = app_instance.app_context()
inner_ctx.push()
user = User(full_name="Coord", email="c@t.dev", role=UserRole.coordinator)
user.set_password("Password1!")
db.session.add(user)
db.session.commit()
print("User committed in inner ctx, id:", user.id)
inner_ctx.pop()  # This calls teardown which calls db.session.remove()
print("Inner context popped")

# Check if user is still visible in outer session
u2 = db.session.scalar(select(User).where(User.email == "c@t.dev"))
print("User visible in outer session after inner pop:", u2)

# Now login
r = test_client.post("/auth/login", data={"email": "c@t.dev", "password": "Password1!"})
print("Login status:", r.status_code, "Location:", r.headers.get("Location"))

# Try coordinator endpoint
r2 = test_client.post("/api/briefings")
print("Briefings (expects 201 if logged in, 302 if not):", r2.status_code)

# Cleanup
app_ctx.pop()
