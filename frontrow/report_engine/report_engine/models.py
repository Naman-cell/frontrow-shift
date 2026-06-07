"""All models for the report engine — public inputs, internal state, and report outputs.

Zero imports from app.*. Self-contained.
"""

import re
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────


class InterviewStatus(StrEnum):
    SCHEDULED = "Scheduled"
    ONGOING = "Ongoing"
    COMPLETED = "Completed"
    INCOMPLETE = "Incomplete"


class InterviewQuestionMode(StrEnum):
    AI = "AI"
    HYBRID = "HYBRID"
    MANUAL = "MANUAL"


class SkillStatus(StrEnum):
    UNTOUCHED = "untouched"
    IN_PROGRESS = "in_progress"
    SUFFICIENT = "sufficient"
    NEEDS_VALIDATION = "needs_validation"
    LOW_CONFIDENCE = "low_confidence"


class EvidenceSignalType(StrEnum):
    STRONG_EVIDENCE = "strong_evidence"
    PARTIAL_UNDERSTANDING = "partial_understanding"
    REFUSAL = "refusal"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONCRETE_EXPERIENCE = "concrete_experience"
    LOW_CONFIDENCE = "low_confidence"


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


class MoveType(StrEnum):
    OPEN_TOPIC = "open_topic"
    DRILL_DOWN = "drill_down"
    SCAFFOLD_RETRY = "scaffold_retry"
    ASK_FOR_EXAMPLE = "ask_for_example"
    VALIDATE_RESUME_CLAIM = "validate_resume_claim"
    SWITCH_ADJACENT_TOPIC = "switch_adjacent_topic"
    CLARIFY_AND_REASK = "clarify_and_reask"
    REPEAT_QUESTION = "repeat_question"
    REPAIR_AND_REDIRECT = "repair_and_redirect"
    MOVE_TO_BEHAVIORAL = "move_to_behavioral"
    CLOSE_TOPIC = "close_topic"
    CANDIDATE_QUESTIONS = "candidate_questions"
    TIME_BOXED_COVERAGE = "time_boxed_coverage"
    WRAP_UP = "wrap_up"


# ── Public input models ──────────────────────────────────────────────


class TurnInput(BaseModel):
    """Single Q&A turn from SkillBrew's interview."""

    question_text: str
    answer_text: str = ""
    answer_audio_base64: str | None = None
    audio_mime_type: str = "audio/webm"


class ReportEngineConfig(BaseModel):
    """Configuration for the report engine."""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    use_gemini: bool = True  # False = heuristic-only fallback


class ReportInput(BaseModel):
    """What SkillBrew provides to generate a report."""

    job_title: str
    seniority: str = "mid"  # Fresher/Junior/Mid/Senior/Staff/Lead
    industry: str = ""
    job_description: str = ""
    resume_json: dict = Field(default_factory=dict)  # free-form resume data
    experience_range: str = ""  # e.g. "3-5 years"
    interview_type: str = "Standard"  # Standard / Deep
    required_skills: list[str] = Field(default_factory=list)
    turns: list[TurnInput] = Field(min_length=1)


# ── Internal role/rubric/skill models ────────────────────────────────


class RoleContext(BaseModel):
    """required_skills must be pre-extracted clean skill names (e.g. ["Python", "SQL"]), not raw JD text."""

    role_id: str = "role_poc"
    title: str = "Backend Engineer"
    seniority: str = "mid"
    job_description_summary: str = ""
    resume_summary: str = ""
    resume_claims: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)

    @field_validator("required_skills", mode="after")
    @classmethod
    def cap_skills(cls, skills: list[str]) -> list[str]:
        return skills[:20]


class RubricDimension(BaseModel):
    dimension_id: str
    label: str
    weight: float = Field(ge=0.0, le=1.0)


class Rubric(BaseModel):
    dimensions: list[RubricDimension] = Field(
        default_factory=lambda: [
            RubricDimension(dimension_id="field_expertise", label="Field expertise", weight=0.4),
            RubricDimension(dimension_id="experience_depth", label="Experience depth", weight=0.25),
            RubricDimension(dimension_id="communication", label="Communication", weight=0.2),
            RubricDimension(
                dimension_id="behavioral_ownership",
                label="Behavioral and ownership",
                weight=0.15,
            ),
        ]
    )

    @classmethod
    def for_seniority(cls, seniority: str) -> "Rubric":
        """Create role-weighting that adapts without assuming a field.

        The same four top-level dimensions work across software, healthcare,
        trades, operations, sales, and other roles. What changes is emphasis:
        early-career roles usually need more communication/coachability signal,
        while senior roles need stronger depth and ownership signal.
        """
        seniority_key = seniority.lower()
        if seniority_key in {"fresher", "entry", "junior", "trainee", "apprentice"}:
            weights = {
                "field_expertise": 0.30,
                "experience_depth": 0.15,
                "communication": 0.30,
                "behavioral_ownership": 0.25,
            }
        elif seniority_key in {"senior", "lead", "principal", "staff", "manager"}:
            weights = {
                "field_expertise": 0.35,
                "experience_depth": 0.35,
                "communication": 0.15,
                "behavioral_ownership": 0.15,
            }
        else:
            weights = {
                "field_expertise": 0.40,
                "experience_depth": 0.25,
                "communication": 0.20,
                "behavioral_ownership": 0.15,
            }
        return cls(
            dimensions=[
                RubricDimension(
                    dimension_id="field_expertise",
                    label="Field expertise",
                    weight=weights["field_expertise"],
                ),
                RubricDimension(
                    dimension_id="experience_depth",
                    label="Experience depth",
                    weight=weights["experience_depth"],
                ),
                RubricDimension(
                    dimension_id="communication",
                    label="Communication",
                    weight=weights["communication"],
                ),
                RubricDimension(
                    dimension_id="behavioral_ownership",
                    label="Behavioral and ownership",
                    weight=weights["behavioral_ownership"],
                ),
            ]
        )


class SkillNode(BaseModel):
    skill_id: str
    label: str
    dimension: str = "field_expertise"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    target_depth: str = "medium"
    current_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    attempts: int = 0
    scaffold_attempts: int = 0
    status: SkillStatus = SkillStatus.UNTOUCHED
    evidence_ids: list[str] = Field(default_factory=list)
    related_resume_claims: list[str] = Field(default_factory=list)
    related_jd_requirements: list[str] = Field(default_factory=list)


class SkillMap(BaseModel):
    skills: dict[str, SkillNode] = Field(default_factory=dict)

    def highest_priority_uncovered(self, exclude_skill_ids: set[str] | None = None) -> SkillNode | None:
        excluded = exclude_skill_ids or set()
        candidates = [
            skill
            for skill in self.skills.values()
            if skill.skill_id not in excluded and skill.status != SkillStatus.SUFFICIENT
        ]
        return max(candidates, key=lambda skill: (skill.importance, -skill.attempts), default=None)

    def next_coverage_target(self, exclude_skill_ids: set[str] | None = None) -> SkillNode | None:
        """Prefer untouched skills before revisiting partially-tested high-priority skills."""
        excluded = exclude_skill_ids or set()
        candidates = [
            skill
            for skill in self.skills.values()
            if skill.skill_id not in excluded and skill.status != SkillStatus.SUFFICIENT
        ]
        return max(
            candidates,
            key=lambda skill: (
                skill.attempts == 0,
                -skill.attempts,
                skill.importance,
            ),
            default=None,
        )

    def get_or_create(self, skill_id: str, label: str | None = None) -> SkillNode:
        if skill_id not in self.skills:
            self.skills[skill_id] = SkillNode(skill_id=skill_id, label=label or skill_id.replace("_", " "))
        return self.skills[skill_id]

    @property
    def covered_skill_ids(self) -> set[str]:
        return {
            skill.skill_id
            for skill in self.skills.values()
            if skill.status == SkillStatus.SUFFICIENT or skill.attempts > 0
        }


# ── Evidence models ──────────────────────────────────────────────────


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


# ── Turn/answer models ───────────────────────────────────────────────


class NextMoveDecision(BaseModel):
    move_type: MoveType
    target_skill_id: str
    target_skill_label: str
    reason: str
    evidence_used: list[str] = Field(default_factory=list)
    alternatives_avoided: list[str] = Field(default_factory=list)
    time_consideration: str | None = None
    interviewer_response: str = ""
    should_end_interview: bool = False
    prompt_version: str = "next-move-planner-v1"


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


# ── Interview state ──────────────────────────────────────────────────


class InterviewState(BaseModel):
    interview_id: str
    status: InterviewStatus = InterviewStatus.SCHEDULED
    role: RoleContext
    question_mode: InterviewQuestionMode = InterviewQuestionMode.AI
    duration_minutes: int = 30
    started_at: datetime | None = None
    time_remaining_seconds: int = 1800
    rubric: Rubric = Field(default_factory=Rubric)
    skill_map: SkillMap = Field(default_factory=SkillMap)
    conversation_summary: str = ""
    turns: list[InterviewTurn] = Field(default_factory=list)
    evidence_ledger: EvidenceLedger = Field(default_factory=EvidenceLedger)
    covered_topics: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    closing_question_sent: bool = False
    runtime_metrics: dict[str, int] = Field(default_factory=dict)
    last_question: str | None = None
    next_question: str | None = None
    last_next_move: NextMoveDecision | None = None
    plan_position: int = 0
    planned_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def seed_skills_from_role(self) -> None:
        for index, skill_label in enumerate(self.role.required_skills):
            # Strip characters that produce noisy skill_ids before slugifying
            slug = re.sub(r"[:\(\)\[\]{}'\".,!?@#$%^&*+=|\\<>]", "", skill_label)
            skill_id = re.sub(r"\s+", "_", slug.strip().lower()).replace("/", "_")[:60]
            # Remove any double underscores and trailing underscores
            skill_id = re.sub(r"_+", "_", skill_id).strip("_")
            if not skill_id:
                continue
            importance = max(0.95 - (index * 0.08), 0.45)
            self.skill_map.skills.setdefault(
                skill_id,
                SkillNode(
                    skill_id=skill_id,
                    label=skill_label,
                    importance=importance,
                    related_jd_requirements=[skill_label],
                ),
            )


# ── Report models ────────────────────────────────────────────────────


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
