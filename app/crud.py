from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app import models
from app.security_tools import validate_requested_tools, InvalidToolError


def _write_audit(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str,
    event_type: str,
    skill_id: str | None = None,
    version_id: str | None = None,
    details: dict | None = None,
) -> models.AuditLog:
    entry = models.AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        skill_id=skill_id,
        version_id=version_id,
        details=details or {},
    )
    db.add(entry)
    return entry


def _validate_tools_or_400(tools: list[str]) -> list[str]:
    try:
        return validate_requested_tools(tools)
    except InvalidToolError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def create_skill_draft(
    db: Session,
    *,
    user: models.User,
    name: str,
    department: str,
    instructions: str,
    requested_tools: list[str],
) -> models.Skill:
    clean_tools = _validate_tools_or_400(requested_tools)

    skill = models.Skill(
        organization_id=user.organization_id,
        name=name,
        department=department,
        status=models.SkillStatus.draft,
        created_by=user.id,
    )
    db.add(skill)
    db.flush()  # get skill.id

    version = models.SkillVersion(
        skill_id=skill.id,
        organization_id=user.organization_id,
        version_number=1,
        instructions=instructions,
        requested_tools=clean_tools,
        granted_tools=[],
        status=models.VersionStatus.draft,
        created_by=user.id,
    )
    db.add(version)
    db.flush()

    _write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        event_type="skill_draft_created",
        skill_id=skill.id,
        version_id=version.id,
        details={"name": name, "department": department, "version_number": 1},
    )

    db.commit()
    db.refresh(skill)
    return skill


def list_skills_for_org(db: Session, *, organization_id: str) -> list[models.Skill]:
    return (
        db.query(models.Skill)
        .filter(models.Skill.organization_id == organization_id)
        .order_by(models.Skill.created_at.desc())
        .all()
    )


def get_skill_scoped_or_404(db: Session, *, skill_id: str, organization_id: str) -> models.Skill:
    """
    Fetch a skill, scoped to the caller's organization. A skill that exists
    but belongs to a different org is treated identically to one that does
    not exist at all (404), so cross-tenant probing cannot distinguish
    "not found" from "not yours" — this is the tenant-isolation boundary.
    """
    skill = (
        db.query(models.Skill)
        .options(joinedload(models.Skill.versions))
        .filter(models.Skill.id == skill_id)
        .first()
    )
    if skill is None or skill.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
    return skill


def create_new_version(
    db: Session,
    *,
    user: models.User,
    skill: models.Skill,
    instructions: str,
    requested_tools: list[str],
) -> models.SkillVersion:
    if skill.status == models.SkillStatus.disabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot create a new version for a disabled skill.",
        )

    clean_tools = _validate_tools_or_400(requested_tools)

    latest = (
        db.query(models.SkillVersion)
        .filter(models.SkillVersion.skill_id == skill.id)
        .order_by(models.SkillVersion.version_number.desc())
        .first()
    )
    next_number = (latest.version_number + 1) if latest else 1

    version = models.SkillVersion(
        skill_id=skill.id,
        organization_id=skill.organization_id,
        version_number=next_number,
        instructions=instructions,
        requested_tools=clean_tools,
        granted_tools=[],
        status=models.VersionStatus.draft,
        created_by=user.id,
    )
    db.add(version)
    db.flush()

    _write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        event_type="skill_version_created",
        skill_id=skill.id,
        version_id=version.id,
        details={"version_number": next_number},
    )

    db.commit()
    db.refresh(version)
    return version


def submit_version_for_review(
    db: Session,
    *,
    user: models.User,
    skill: models.Skill,
    version_id: str,
) -> models.SkillVersion:
    version = (
        db.query(models.SkillVersion)
        .filter(models.SkillVersion.id == version_id, models.SkillVersion.skill_id == skill.id)
        .first()
    )
    if version is None or version.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    if version.status != models.VersionStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot submit a version with status '{version.status.value}' for review.",
        )

    version.status = models.VersionStatus.in_review

    _write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        event_type="skill_version_submitted_for_review",
        skill_id=skill.id,
        version_id=version.id,
        details={"version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def approve_version(
    db: Session,
    *,
    user: models.User,
    skill: models.Skill,
    version_id: str,
) -> models.SkillVersion:
    """Owner-only. A version must be approved before it can be activated."""
    version = (
        db.query(models.SkillVersion)
        .filter(models.SkillVersion.id == version_id, models.SkillVersion.skill_id == skill.id)
        .first()
    )
    if version is None or version.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    if version.status != models.VersionStatus.in_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot approve a version with status '{version.status.value}'. "
                   f"It must be submitted for review first.",
        )

    from datetime import datetime, timezone
    version.status = models.VersionStatus.approved
    version.reviewed_by = user.id
    version.reviewed_at = datetime.now(timezone.utc)

    _write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        event_type="skill_version_approved",
        skill_id=skill.id,
        version_id=version.id,
        details={"version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def activate_version(
    db: Session,
    *,
    user: models.User,
    skill: models.Skill,
    version_id: str,
) -> models.SkillVersion:
    """
    Owner-only. Idempotent: activating an already-active version again is a
    safe no-op that returns the existing state (and logs an
    'activation_noop' audit event) rather than erroring or double-applying
    side effects.
    """
    version = (
        db.query(models.SkillVersion)
        .filter(
            models.SkillVersion.id == version_id,
            models.SkillVersion.skill_id == skill.id,
        )
        .first()
    )
    if version is None or version.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    # Idempotency: already the active version -> no-op, same response.
    if skill.active_version_id == version.id and version.status == models.VersionStatus.active:
        _write_audit(
            db,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="skill_activation_noop",
            skill_id=skill.id,
            version_id=version.id,
            details={"version_number": version.version_number, "reason": "already_active"},
        )
        db.commit()
        db.refresh(version)
        return version

    if version.status == models.VersionStatus.superseded:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot activate a superseded version. Create a new version instead.",
        )
    if version.status == models.VersionStatus.disabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot activate a version belonging to a disabled skill state.",
        )
    if version.status in (models.VersionStatus.draft, models.VersionStatus.in_review):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version must be approved before activation (current status: "
                   f"'{version.status.value}'). Submit it for review and have an owner "
                   f"approve it first.",
        )
    if skill.status == models.SkillStatus.disabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Skill is disabled; re-enable is not supported in this vertical slice.",
        )

    # Supersede the currently-active version, if any.
    if skill.active_version_id:
        previous = (
            db.query(models.SkillVersion)
            .filter(models.SkillVersion.id == skill.active_version_id)
            .first()
        )
        if previous and previous.status == models.VersionStatus.active:
            previous.status = models.VersionStatus.superseded

    version.status = models.VersionStatus.active
    version.activated_by = user.id
    from datetime import datetime, timezone
    version.activated_at = datetime.now(timezone.utc)

    skill.active_version_id = version.id
    skill.status = models.SkillStatus.active

    _write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        event_type="skill_activated",
        skill_id=skill.id,
        version_id=version.id,
        details={"version_number": version.version_number},
    )

    db.commit()
    db.refresh(version)
    return version


def disable_skill(db: Session, *, user: models.User, skill: models.Skill) -> models.Skill:
    if skill.status == models.SkillStatus.disabled:
        # idempotent no-op
        return skill

    skill.status = models.SkillStatus.disabled

    _write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        event_type="skill_disabled",
        skill_id=skill.id,
        version_id=skill.active_version_id,
        details={},
    )

    db.commit()
    db.refresh(skill)
    return skill


def get_active_skills_for_department(
    db: Session, *, organization_id: str, department: str
) -> list[models.Skill]:
    return (
        db.query(models.Skill)
        .filter(
            models.Skill.organization_id == organization_id,
            models.Skill.department == department,
            models.Skill.status == models.SkillStatus.active,
        )
        .all()
    )
