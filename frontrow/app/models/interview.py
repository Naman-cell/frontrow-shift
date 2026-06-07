import re
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("required_skills", mode="after")
    @classmethod
    def split_long_skills(cls, skills: list[str]) -> list[str]:
        """Split oversized skill strings and cap the list."""
        result: list[str] = []
        for skill in skills:
            skill = skill.strip()
            if not skill:
                continue
            if len(skill) <= 80:
                result.append(skill)
            else:
                parts = re.split(r"[;\n]|(?<=[.])\s+(?=[A-Z])", skill)
                parts = [p.strip().rstrip(".") for p in parts if len(p.strip()) >= 8]
                result.extend(parts if parts else [skill[:80]])
        seen: set[str] = set()
        deduped: list[str] = []
        for s in result:
            key = s.lower().strip()
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        return deduped[:20]


class InterviewSessionCreate(BaseModel):
    tenant_id: str = "tenant_poc"
    candidate_id: str
    role: RoleContext = Field(default_factory=RoleContext)
    duration_minutes: int = Field(default=30, ge=2, le=180)
    question_mode: InterviewQuestionMode = InterviewQuestionMode.AI
    planned_questions: list[str] = Field(default_factory=list)


class TranscriptTurn(BaseModel):
    question: str
    answer: str


class ReportFromTranscriptRequest(BaseModel):
    role: RoleContext
    turns: list[TranscriptTurn] = Field(min_length=1)
    duration_minutes: int = Field(default=30, ge=2, le=180)


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
