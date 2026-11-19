from flask import Blueprint, render_template
from flask_login import login_required

from backend.utils.decorators import coordinator_required

coordinator_bp = Blueprint("coordinator", __name__)


@coordinator_bp.get("/dashboard")
@login_required
@coordinator_required
def dashboard():
    return render_template("coordinator/dashboard.html")

# Full implementation in ST-11
