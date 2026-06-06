from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.evidence import EvidenceLedger
from app.models.interview import InterviewQuestionMode, InterviewStatus, RoleContext
from app.models.next_move import NextMoveDecision
from app.models.rubric import Rubric
from app.models.skill_map import SkillMap, SkillNode
from app.models.turn import InterviewTurn


class ReconnectState(BaseModel):
    current_question: str | None = None
    current_stage: str = "initialized"
    remaining_seconds: int
    first_question_sent: bool = False
    question_mode: InterviewQuestionMode = InterviewQuestionMode.AI
    plan_position: int = 0
    generation: int = 0


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
    last_question: str | None = None
    next_question: str | None = None
    last_next_move: NextMoveDecision | None = None
    plan_position: int = 0
    planned_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def reconnect_state(self) -> ReconnectState:
        return ReconnectState(
            current_question=self.next_question or self.last_question,
            remaining_seconds=self.time_remaining_seconds,
            first_question_sent=bool(self.last_question or self.next_question),
            question_mode=self.question_mode,
            plan_position=self.plan_position,
            current_stage=self.status.value,
        )

    def seed_skills_from_role(self) -> None:
        for index, skill_label in enumerate(self.role.required_skills):
            skill_id = skill_label.lower().replace(" ", "_").replace("/", "_")
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
