from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceSignalType(StrEnum):
    STRONG_EVIDENCE = "strong_evidence"
    PARTIAL_UNDERSTANDING = "partial_understanding"
    REFUSAL = "refusal"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONCRETE_EXPERIENCE = "concrete_experience"
    LOW_CONFIDENCE = "low_confidence"


class EvidenceRecord(BaseModel):
    evidence_id: str
    interview_id: str
    turn_id: str
    skill_id: str
    dimension: str
    signal_type: EvidenceSignalType
    summary: str
    score_delta: float = 0.0
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    quote_or_audio_ref: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceLedger(BaseModel):
    records: list[EvidenceRecord] = Field(default_factory=list)

    def append(self, record: EvidenceRecord) -> None:
        self.records.append(record)

    def ids_for_skill(self, skill_id: str) -> list[str]:
        return [record.evidence_id for record in self.records if record.skill_id == skill_id]
