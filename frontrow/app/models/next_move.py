from enum import StrEnum

from pydantic import BaseModel, Field


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
