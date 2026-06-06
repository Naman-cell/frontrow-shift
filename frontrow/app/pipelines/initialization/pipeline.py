from pydantic import BaseModel

from app.models.interview import InterviewSession
from app.models.next_move import MoveType, NextMoveDecision
from app.models.rubric import Rubric
from app.models.state import InterviewState


class InterviewInitializationInput(BaseModel):
    session: InterviewSession


class InterviewInitializationOutput(BaseModel):
    state: InterviewState
    first_question: str


class InterviewInitializationPipeline:
    async def run(self, payload: InterviewInitializationInput) -> InterviewInitializationOutput:
        session = payload.session
        state = InterviewState(
            interview_id=session.interview_id,
            status=session.status,
            role=session.role,
            question_mode=session.question_mode,
            duration_minutes=session.duration_minutes,
            time_remaining_seconds=session.duration_minutes * 60,
            rubric=Rubric.for_seniority(session.role.seniority),
            planned_questions=session.planned_questions,
        )
        state.seed_skills_from_role()

        first_question = self._build_first_question(state)
        state.next_question = first_question
        priority_skill = state.skill_map.highest_priority_uncovered()
        if priority_skill is not None:
            state.last_next_move = NextMoveDecision(
                move_type=MoveType.OPEN_TOPIC,
                target_skill_id=priority_skill.skill_id,
                target_skill_label=priority_skill.label,
                reason="Opening question is anchored to the highest priority role skill.",
            )
        return InterviewInitializationOutput(state=state, first_question=first_question)

    def _build_first_question(self, state: InterviewState) -> str:
        if state.question_mode in {"HYBRID", "MANUAL"} and state.planned_questions:
            return state.planned_questions[0]

        priority_skill = state.skill_map.highest_priority_uncovered()
        if priority_skill is None:
            return f"Hi, thanks for joining. Could you walk me through work that best represents your fit for {state.role.title}?"

        return (
            f"Hi, thanks for joining. Could you start with a real work situation "
            f"where {priority_skill.label} mattered for the outcome?"
        )
