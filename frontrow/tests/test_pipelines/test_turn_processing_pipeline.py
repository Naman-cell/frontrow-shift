import pytest

from app.models.interview import RoleContext
from app.models.next_move import MoveType
from app.models.skill_map import SkillMap, SkillNode
from app.models.state import InterviewState
from app.models.turn import CandidateAnswer
from app.pipelines.turn_processing.pipeline import (
    TurnProcessingInput,
    TurnProcessingPipeline,
)


@pytest.mark.asyncio
async def test_turn_processing_pipeline_runs_haystack_graph_end_to_end() -> None:
    state = InterviewState(
        interview_id="int_pipeline",
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python concurrency", "API design"],
        ),
        last_question="What is the GIL in Python?",
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
    pipeline = TurnProcessingPipeline()

    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(
                transcript="I am not sure, I do not know that topic well."
            ),
        )
    )

    assert output.turn.turn_id == "turn_001"
    assert output.next_move.move_type == MoveType.SCAFFOLD_RETRY
    assert output.turn.answer_analysis.intent == "refusal"
    assert output.next_move.target_skill_id == "python_concurrency"
    assert output.evidence_created
    assert output.state.turns[0].answer_analysis is not None
    assert output.state.next_question


@pytest.mark.asyncio
async def test_turn_processing_acknowledges_refusal_before_switching_topic() -> None:
    state = InterviewState(
        interview_id="int_pipeline_switch",
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python concurrency", "API design"],
        ),
        last_question="How have you handled Python concurrency in practice?",
        skill_map=SkillMap(
            skills={
                "python_concurrency": SkillNode(
                    skill_id="python_concurrency",
                    label="Python concurrency",
                    importance=0.9,
                    attempts=2,
                ),
                "api_design": SkillNode(
                    skill_id="api_design",
                    label="API design",
                    importance=0.8,
                ),
            }
        ),
    )
    pipeline = TurnProcessingPipeline()

    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(
                transcript="I am not sure, I do not know that topic well."
            ),
        )
    )

    assert output.next_move.move_type == MoveType.SWITCH_ADJACENT_TOPIC
    assert output.next_move.target_skill_id == "api_design"
    assert output.next_question.lower().startswith("no problem")
