from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.auth import get_current_user
from app.database import get_db

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("/{department}/active-skills", response_model=list[schemas.SkillOut])
def active_skills_for_department(
    department: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Runtime selection endpoint: only skills that are org-scoped, in the
    given department, AND currently `active` are returned. Draft and
    disabled skills are never eligible, regardless of department match.
    """
    return crud.get_active_skills_for_department(
        db, organization_id=user.organization_id, department=department
    )
