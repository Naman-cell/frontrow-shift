from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ReportFinding(BaseModel):
    title: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class SkillBreakdown(BaseModel):
    skill_id: str
    label: str
    dimension: str
    score: float
    confidence: float
    attempts: int
    status: str
    evidence_ids: list[str] = Field(default_factory=list)


class SkillScoreDetail(BaseModel):
    skill_id: str
    label: str
    score_4: float
    score_label: str = ""
    target_4: float
    band: str
    weight_in_dimension: float
    evidence_ids: list[str] = Field(default_factory=list)


class ScoreCompositionItem(BaseModel):
    dimension: str
    label: str
    weight: float
    score_4: float
    target_4: float
    points: float
    rationale: str
    skill_details: list[SkillScoreDetail] = Field(default_factory=list)


class CompetencyScorecardItem(BaseModel):
    dimension: str
    label: str
    weight: float
    score_4: float
    target_4: float
    band: str
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class SkillRoleMatchItem(BaseModel):
    skill_id: str
    label: str
    candidate_level_4: float | None = None
    required_level_4: float
    band: str
    assessed: bool = True
    evidence_ids: list[str] = Field(default_factory=list)


class AdvisorySignal(BaseModel):
    label: str
    level: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class SoftLayerSection(BaseModel):
    label: str
    score_4: float
    facets: dict[str, float] = Field(default_factory=dict)
    note: str


class EvidenceByQuestion(BaseModel):
    turn_id: str
    turn_index: int
    dimension: str
    skill_id: str
    question: str
    answer_excerpt: str
    score_4: float
    score_label: str = ""
    band: str
    ai_judgement: str
    evidence_ids: list[str] = Field(default_factory=list)


class InterviewReport(BaseModel):
    interview_id: str
    overall_score: float = 0.0
    fit_score: int = 0
    role_bar: int = 100
    verdict: str = "needs_review"
    rationale: str = ""
    tags: list[str] = Field(default_factory=list)
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    score_composition: list[ScoreCompositionItem] = Field(default_factory=list)
    skill_breakdown: list[SkillBreakdown] = Field(default_factory=list)
    skill_role_match: list[SkillRoleMatchItem] = Field(default_factory=list)
    competency_scorecard: list[CompetencyScorecardItem] = Field(default_factory=list)
    ai_native_signals: list[AdvisorySignal] = Field(default_factory=list)
    soft_layer: list[SoftLayerSection] = Field(default_factory=list)
    worry_areas: list[ReportFinding] = Field(default_factory=list)
    recommended_next_steps: list[ReportFinding] = Field(default_factory=list)
    evidence_by_question: list[EvidenceByQuestion] = Field(default_factory=list)
    question_count: int = 0
    evidence_count: int = 0
    strengths: list[ReportFinding] = Field(default_factory=list)
    risks: list[ReportFinding] = Field(default_factory=list)
    recommendation: str = "needs_review"
    caveats: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
