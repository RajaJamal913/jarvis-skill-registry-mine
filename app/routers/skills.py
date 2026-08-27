from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.auth import get_current_user, require_owner
from app.database import get_db

router = APIRouter(prefix="/skills", tags=["skills"])


@router.post("", response_model=schemas.SkillDetailOut, status_code=201)
def create_skill(
    payload: schemas.SkillCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    skill = crud.create_skill_draft(
        db,
        user=user,
        name=payload.name,
        department=payload.department,
        instructions=payload.instructions,
        requested_tools=payload.requested_tools,
    )
    return crud.get_skill_scoped_or_404(db, skill_id=skill.id, organization_id=user.organization_id)


@router.get("", response_model=list[schemas.SkillOut])
def list_skills(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return crud.list_skills_for_org(db, organization_id=user.organization_id)


@router.get("/{skill_id}", response_model=schemas.SkillDetailOut)
def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return crud.get_skill_scoped_or_404(db, skill_id=skill_id, organization_id=user.organization_id)


@router.post("/{skill_id}/versions", response_model=schemas.SkillVersionOut, status_code=201)
def create_version(
    skill_id: str,
    payload: schemas.SkillVersionCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    skill = crud.get_skill_scoped_or_404(db, skill_id=skill_id, organization_id=user.organization_id)
    return crud.create_new_version(
        db,
        user=user,
        skill=skill,
        instructions=payload.instructions,
        requested_tools=payload.requested_tools,
    )


@router.post("/{skill_id}/versions/{version_id}/submit-for-review", response_model=schemas.SkillVersionOut)
def submit_version_for_review(
    skill_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    skill = crud.get_skill_scoped_or_404(db, skill_id=skill_id, organization_id=user.organization_id)
    return crud.submit_version_for_review(db, user=user, skill=skill, version_id=version_id)


@router.post("/{skill_id}/versions/{version_id}/approve", response_model=schemas.SkillVersionOut)
def approve_version(
    skill_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    skill = crud.get_skill_scoped_or_404(db, skill_id=skill_id, organization_id=user.organization_id)
    return crud.approve_version(db, user=user, skill=skill, version_id=version_id)


@router.post("/{skill_id}/versions/{version_id}/activate", response_model=schemas.SkillVersionOut)
def activate_version(
    skill_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    skill = crud.get_skill_scoped_or_404(db, skill_id=skill_id, organization_id=user.organization_id)
    return crud.activate_version(db, user=user, skill=skill, version_id=version_id)


@router.post("/{skill_id}/disable", response_model=schemas.SkillOut)
def disable_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    skill = crud.get_skill_scoped_or_404(db, skill_id=skill_id, organization_id=user.organization_id)
    return crud.disable_skill(db, user=user, skill=skill)
