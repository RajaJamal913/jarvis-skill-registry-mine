from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.database import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[schemas.AuditLogOut])
def list_audit_logs(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Read-only, org-scoped audit trail. Never exposes other orgs' events."""
    return (
        db.query(models.AuditLog)
        .filter(models.AuditLog.organization_id == user.organization_id)
        .order_by(models.AuditLog.created_at.desc())
        .all()
    )
