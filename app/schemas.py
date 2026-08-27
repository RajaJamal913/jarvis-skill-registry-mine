from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------- Skill / Version input ----------

class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=20000)
    requested_tools: list[str] = Field(default_factory=list)

    @field_validator("name", "department", "instructions")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class SkillVersionCreateRequest(BaseModel):
    instructions: str = Field(min_length=1, max_length=20000)
    requested_tools: list[str] = Field(default_factory=list)

    @field_validator("instructions")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


# ---------- Output ----------

class SkillVersionOut(BaseModel):
    id: str
    skill_id: str
    version_number: int
    instructions: str
    requested_tools: list[str]
    granted_tools: list[str]
    status: str
    created_by: str
    created_at: datetime
    activated_by: Optional[str] = None
    activated_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SkillOut(BaseModel):
    id: str
    organization_id: str
    name: str
    department: str
    status: str
    active_version_id: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillDetailOut(SkillOut):
    versions: list[SkillVersionOut] = Field(default_factory=list)


class AuditLogOut(BaseModel):
    id: str
    organization_id: str
    actor_user_id: str
    event_type: str
    skill_id: Optional[str] = None
    version_id: Optional[str] = None
    details: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    detail: str
