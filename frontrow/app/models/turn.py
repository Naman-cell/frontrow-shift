from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.evidence import EvidenceRecord
from app.models.next_move import NextMoveDecision


class AnswerQuality(StrEnum):
    STRONG = "strong"
    PARTIAL = "partial"
    WEAK = "weak"
    UNCLEAR = "unclear"
    REFUSAL = "refusal"
    OFF_TOPIC = "off_topic"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONCRETE_EXPERIENCE = "concrete_experience"
    SHALLOW_EXPERIENCE = "shallow_experience"


class CandidateIntent(StrEnum):
    ANSWERED = "answered"
    CANDIDATE_QUESTION = "candidate_question"
    REFUSAL = "refusal"
    PIVOT_REQUEST = "pivot_request"
    CLARIFICATION_REQUEST = "clarification_request"
    REPEAT_REQUEST = "repeat_request"
    OFF_TOPIC = "off_topic"
    SILENCE_OR_NOISE = "silence_or_noise"
    DISENGAGED = "disengaged"
    FRUSTRATED = "frustrated"
    UNKNOWN = "unknown"


class CandidateAnswer(BaseModel):
    audio_ref: str | None = None
    audio_base64: str | None = None
    audio_mime_type: str | None = None
    transcript: str = ""
    analysis_summary: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AnswerAnalysis(BaseModel):
    quality: AnswerQuality
    intent: CandidateIntent = CandidateIntent.UNKNOWN
    transcript: str = ""
    summary: str
    target_skill_id: str
    target_skill_label: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    resume_claim_detected: bool = False
    extracted_claim: str | None = None
    suggested_interviewer_response: str = ""
    suggested_next_question: str = ""
    preferred_topics: list[str] = Field(default_factory=list)
    preferred_relevant_skill_id: str | None = None
    missing_expected_points: list[str] = Field(default_factory=list)


class InterviewTurn(BaseModel):
    turn_id: str
    interview_id: str
    turn_index: int
    question: str
    candidate_answer: CandidateAnswer | None = None
    answer_analysis: AnswerAnalysis | None = None
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    next_move: NextMoveDecision | None = None
    next_question: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    answered_at: datetime | None = None
