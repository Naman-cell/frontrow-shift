from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class InterviewStatus(StrEnum):
    SCHEDULED = "Scheduled"
    ONGOING = "Ongoing"
    COMPLETED = "Completed"
    INCOMPLETE = "Incomplete"


class InterviewQuestionMode(StrEnum):
    AI = "AI"
    HYBRID = "HYBRID"
    MANUAL = "MANUAL"


class RoleContext(BaseModel):
    role_id: str = "role_poc"
    title: str = "Backend Engineer"
    seniority: str = "mid"
    job_description_summary: str = ""
    resume_summary: str = ""
    resume_claims: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)


class InterviewSessionCreate(BaseModel):
    tenant_id: str = "tenant_poc"
    candidate_id: str
    role: RoleContext = Field(default_factory=RoleContext)
    duration_minutes: int = Field(default=30, ge=2, le=180)
    question_mode: InterviewQuestionMode = InterviewQuestionMode.AI
    planned_questions: list[str] = Field(default_factory=list)


class InterviewSession(BaseModel):
    interview_id: str
    tenant_id: str
    candidate_id: str
    role: RoleContext
    duration_minutes: int
    question_mode: InterviewQuestionMode = InterviewQuestionMode.AI
    planned_questions: list[str] = Field(default_factory=list)
    plan_position: int = 0
    status: InterviewStatus = InterviewStatus.SCHEDULED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
