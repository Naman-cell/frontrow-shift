"""Tests for the four bugs found in interview int_f1e38b060db3."""

import pytest

from app.models.interview import RoleContext
from app.models.next_move import MoveType, NextMoveDecision
from app.models.skill_map import SkillMap, SkillNode
from app.models.state import InterviewState
from app.models.turn import (
    AnswerAnalysis,
    AnswerQuality,
    CandidateAnswer,
    CandidateIntent,
    InterviewTurn,
)
from app.pipelines.turn_processing.pipeline import (
    TurnProcessingInput,
    TurnProcessingPipeline,
)


def _base_state(
    *,
    interview_id: str = "int_test",
    last_question: str = "Tell me about Python.",
) -> InterviewState:
    return InterviewState(
        interview_id=interview_id,
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python concurrency", "API design"],
        ),
        last_question=last_question,
        skill_map=SkillMap(
            skills={
                "python_concurrency": SkillNode(
                    skill_id="python_concurrency",
                    label="Python concurrency",
                    importance=0.9,
                ),
                "api_design": SkillNode(
                    skill_id="api_design",
                    label="API design",
                    importance=0.8,
                ),
            }
        ),
    )


# ── Bug 1: Stop detection ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_detection_from_transcript() -> None:
    """'can we stop this interview' should end the interview."""
    state = _base_state()
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(
                transcript="can we stop this interview, I dont feel like giving the interview",
            ),
        )
    )
    assert output.next_move.should_end_interview is True
    assert output.next_move.move_type == MoveType.WRAP_UP


@pytest.mark.asyncio
async def test_stop_detection_i_want_to_stop() -> None:
    state = _base_state()
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="i want to stop, please end this"),
        )
    )
    assert output.next_move.should_end_interview is True


@pytest.mark.asyncio
async def test_stop_detection_disengaged_intent() -> None:
    """Mock detects 'stop' as DISENGAGED; planner should treat as stop."""
    state = _base_state()
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="please stop, leave me alone"),
        )
    )
    assert output.next_move.should_end_interview is True


# ── Bug 2: Planner repair_and_redirect loop ──────────────────────────


def _state_with_role_fit_loop(num_role_fit_turns: int) -> InterviewState:
    """Build a state that has already looped on role_fit repair_and_redirect."""
    state = _base_state(last_question="Could you tell me what connects you to this role?")
    for i in range(num_role_fit_turns):
        state.turns.append(
            InterviewTurn(
                turn_id=f"turn_{i + 1:03d}",
                interview_id=state.interview_id,
                turn_index=i + 1,
                question="Could you tell me what connects you to this role?",
                candidate_answer=CandidateAnswer(transcript="I am not sure."),
                answer_analysis=AnswerAnalysis(
                    quality=AnswerQuality.REFUSAL,
                    intent=CandidateIntent.REFUSAL,
                    transcript="I am not sure.",
                    summary="Candidate could not answer.",
                    target_skill_id="role_fit",
                    target_skill_label="Role fit",
                    confidence=0.3,
                ),
                next_move=NextMoveDecision(
                    move_type=MoveType.REPAIR_AND_REDIRECT,
                    target_skill_id="role_fit",
                    target_skill_label="Role fit",
                    reason="Multiple low-signal turns.",
                    evidence_used=[],
                    interviewer_response="No problem.",
                ),
            )
        )
    return state


@pytest.mark.asyncio
async def test_planner_escalates_after_repeated_role_fit() -> None:
    """After 2 consecutive role_fit repair_and_redirect, planner must NOT loop again."""
    state = _state_with_role_fit_loop(2)
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="I am not sure, I do not know."),
        )
    )
    # Should escalate to candidate_questions or wrap_up, NOT another repair_and_redirect to role_fit
    assert not (
        output.next_move.move_type == MoveType.REPAIR_AND_REDIRECT
        and output.next_move.target_skill_id == "role_fit"
    ), f"Planner looped on role_fit again: {output.next_move.move_type} -> {output.next_move.target_skill_id}"


@pytest.mark.asyncio
async def test_planner_escalates_to_candidate_questions_or_wrap_up() -> None:
    """After role_fit loop, planner should choose candidate_questions or wrap_up."""
    state = _state_with_role_fit_loop(3)
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="I do not know."),
        )
    )
    assert output.next_move.move_type in {
        MoveType.CANDIDATE_QUESTIONS,
        MoveType.WRAP_UP,
    }


# ── Bug 3: Question dedup ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_verbatim_question_repetition() -> None:
    """If the same question was asked in a recent turn, it must not repeat verbatim."""
    repeated_q = "Could you tell me what experience, training, or interest connects you to this role?"
    state = _base_state(last_question=repeated_q)
    state.turns.append(
        InterviewTurn(
            turn_id="turn_001",
            interview_id=state.interview_id,
            turn_index=1,
            question=repeated_q,
            candidate_answer=CandidateAnswer(transcript="I am not sure."),
            answer_analysis=AnswerAnalysis(
                quality=AnswerQuality.REFUSAL,
                intent=CandidateIntent.REFUSAL,
                transcript="I am not sure.",
                summary="Candidate could not answer.",
                target_skill_id="python_concurrency",
                target_skill_label="Python concurrency",
                confidence=0.3,
            ),
        )
    )
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="I am not sure, I do not know."),
        )
    )
    # The new question must not be identical to the one just asked
    if not output.next_move.should_end_interview:
        assert output.state.next_question.strip().lower() != repeated_q.strip().lower(), (
            f"Question repeated verbatim: {output.state.next_question}"
        )
