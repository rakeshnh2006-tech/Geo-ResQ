# Import all models here so SQLAlchemy's metadata is fully populated before
# create_all() or Alembic migrations are run. Order follows FK dependencies.
from backend.models.user import User, UserRole  # noqa: F401
from backend.models.incident import Incident, IncidentType, IncidentStatus  # noqa: F401
from backend.models.incident_photo import IncidentPhoto  # noqa: F401
from backend.models.verification import Verification, VerificationStatus  # noqa: F401
from backend.models.road_segment import RoadSegment  # noqa: F401
from backend.models.village import Village  # noqa: F401
from backend.models.accessibility_result import AccessibilityResult  # noqa: F401
from backend.models.relief_request import ReliefRequest, NeedCategory  # noqa: F401
from backend.models.prioritization_score import PrioritizationScore  # noqa: F401
from backend.models.briefing import Briefing  # noqa: F401
from backend.models.audit_log import AuditLog  # noqa: F401

__all__ = [
    "User",
    "UserRole",
    "Incident",
    "IncidentType",
    "IncidentStatus",
    "IncidentPhoto",
    "Verification",
    "VerificationStatus",
    "RoadSegment",
    "Village",
    "AccessibilityResult",
    "ReliefRequest",
    "NeedCategory",
    "PrioritizationScore",
    "Briefing",
    "AuditLog",
]
