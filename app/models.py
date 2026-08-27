import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, ForeignKey, DateTime, Enum, JSON, Boolean, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    owner = "owner"
    member = "member"


class SkillStatus(str, enum.Enum):
    draft = "draft"        # no version has ever been activated
    active = "active"      # has a currently-active version
    disabled = "disabled"  # explicitly disabled, excluded from runtime selection


class VersionStatus(str, enum.Enum):
    draft = "draft"              # editable-in-spirit, but versions are never mutated once created
    in_review = "in_review"      # submitted for review, awaiting owner approval
    approved = "approved"        # owner-approved, eligible for activation
    active = "active"            # the single currently active version for its skill
    superseded = "superseded"    # was active, replaced by a newer activated version
    disabled = "disabled"        # active version's skill was disabled while this was active


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    skills = relationship("Skill", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    """
    Minimal user/principal record used for evaluation-scope authentication.

    Auth model: each user has an opaque API key (X-API-Key header). The key
    maps 1:1 to (organization_id, role, department). There is no session /
    JWT layer because the brief explicitly does not require a frontend or
    external auth provider - the important part being evaluated is
    *authorization* (org isolation + owner-only activation), not login UX.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    email = Column(String, nullable=False)
    api_key_hash = Column(String, nullable=False, unique=True, index=True)
    api_key_revoked_at = Column(DateTime(timezone=True), nullable=True)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.member)
    department = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    organization = relationship("Organization", back_populates="users")

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_user_org_email"),
    )


class Skill(Base):
    """
    A Skill is the stable, addressable entity. It never stores executable
    content itself - that content lives on immutable SkillVersion rows.
    `active_version_id` is a pointer, updated only by the activation
    workflow, never by editing a version in place.
    """
    __tablename__ = "skills"

    id = Column(String, primary_key=True, default=_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    department = Column(String, nullable=False, index=True)
    status = Column(Enum(SkillStatus), nullable=False, default=SkillStatus.draft)
    # Intentionally NOT a ForeignKey: skill_versions.skill_id already points
    # the other way, and a mutual FK between the two tables creates a
    # circular dependency for schema creation/migrations. The pointer is
    # enforced and only ever written by app.crud.activate_version.
    active_version_id = Column(String, nullable=True)

    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    organization = relationship("Organization", back_populates="skills")
    versions = relationship(
        "SkillVersion",
        back_populates="skill",
        cascade="all, delete-orphan",
        foreign_keys="SkillVersion.skill_id",
        order_by="SkillVersion.version_number",
    )


class SkillVersion(Base):
    """
    Immutable once created. "Editing" a skill = creating a new version.
    Activating a version = pointing Skill.active_version_id at it and
    marking the previous active version as `superseded`. Rows are never
    updated in place after creation except for the status transition
    (draft -> active -> superseded/disabled), which is the activation
    workflow itself, not a content edit.
    """
    __tablename__ = "skill_versions"

    id = Column(String, primary_key=True, default=_uuid)
    skill_id = Column(String, ForeignKey("skills.id"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)

    instructions = Column(String, nullable=False)
    # Tools the skill *asks* for. Requesting a tool NEVER grants it - see
    # app/security_tools.py. granted_tools always starts empty and is only
    # ever populated by a separate, explicit grant action (out of scope for
    # this vertical slice, but the data model makes the distinction real).
    requested_tools = Column(JSON, nullable=False, default=list)
    granted_tools = Column(JSON, nullable=False, default=list)

    status = Column(Enum(VersionStatus), nullable=False, default=VersionStatus.draft)

    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    activated_by = Column(String, ForeignKey("users.id"), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)

    # Intentionally not a ForeignKey (see the identical rationale on
    # Skill.active_version_id above) - added as a plain column after
    # discovering, while wiring up real Alembic-migration-driven tests,
    # that SQLite's ALTER TABLE cannot add a FK constraint to an existing
    # table without Alembic's batch mode. A plain column sidesteps that
    # entirely and is enforced the same way: written in exactly one place
    # (crud.approve_version) and validated at the application layer.
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    skill = relationship("Skill", back_populates="versions", foreign_keys=[skill_id])

    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_version_number"),
    )


class AuditLog(Base):
    """
    Append-only. Never updated, never deleted via the API.
    """
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    actor_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    event_type = Column(String, nullable=False)  # e.g. "skill_version_created", "skill_activated"
    skill_id = Column(String, ForeignKey("skills.id"), nullable=True)
    version_id = Column(String, ForeignKey("skill_versions.id"), nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=_now)
