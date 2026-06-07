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
        # JD section headers to strip — these are not skills themselves
        _JD_CRUFT = re.compile(
            r"^(technical requirements?|preferred qualifications?|required skills?|"
            r"basic qualifications?|key responsibilities?|nice to have|"
            r"minimum qualifications?|responsibilities)\s*:?\s*",
            re.IGNORECASE,
        )

        def _extract_label(segment: str) -> str:
            """If segment looks like 'Label: long description', return Label only."""
            segment = segment.strip().rstrip(".")
            # Colon-split: take the part before the first colon if it's short
            if ":" in segment:
                label, _, rest = segment.partition(":")
                label = label.strip()
                # Only use label when it's a plausible skill name (2-60 chars, not a URL)
                if (
                    2 <= len(label) <= 60
                    and "http" not in label
                    and (" " not in label or len(label.split()) <= 6)
                ):
                    return label
            return segment

        def _split_one(raw: str) -> list[str]:
            raw = raw.strip()
            if not raw:
                return []
            # Remove leading JD section cruft
            raw = _JD_CRUFT.sub("", raw).strip()
            if not raw:
                return []
            # Short enough — keep as-is (no length filter; short names like "AWS" are valid)
            if len(raw) <= 80:
                label = _extract_label(raw)
                return [label] if label else [raw]
            # Split on: semicolons, newlines, period-then-capital (with or without space)
            parts = re.split(r"[;\n]|(?<=\.)\s*(?=[A-Z])", raw)
            expanded: list[str] = []
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                part = _JD_CRUFT.sub("", part).strip()
                label = _extract_label(part)
                if len(label) > 80:
                    # Still too long — split on comma boundaries
                    sub = [s.strip().rstrip(".") for s in label.split(",") if len(s.strip()) >= 8]
                    expanded.extend(sub[:4])
                elif len(label) >= 8:
                    expanded.append(label)
            return expanded or [raw[:80]]

        result: list[str] = []
        for skill in skills:
            result.extend(_split_one(skill))

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
