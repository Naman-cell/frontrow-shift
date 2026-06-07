"""Phase 0: verify turn-latency instrumentation without behavior change."""

import json
import logging

import pytest

from app.managers.interview_session_manager import InterviewSessionManager
from app.models.interview import RoleContext
from app.models.skill_map import SkillMap, SkillNode
from app.models.state import InterviewState
from app.models.turn import CandidateAnswer
from app.models.websocket import WebSocketInboundPayload
from app.pipelines.turn_processing.pipeline import (
    TurnProcessingInput,
    TurnProcessingPipeline,
)


@pytest.mark.asyncio
async def test_runtime_metrics_populated_after_turn() -> None:
    """Every pipeline component should record a _ms metric."""
    state = InterviewState(
        interview_id="int_latency_test",
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python", "API design"],
        ),
        last_question="Tell me about Python.",
        skill_map=SkillMap(
            skills={
                "python": SkillNode(skill_id="python", label="Python", importance=0.9),
                "api_design": SkillNode(skill_id="api_design", label="API design", importance=0.8),
            }
        ),
    )
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="I used asyncio for concurrent tasks."),
        )
    )
    metrics = output.state.runtime_metrics
    expected_keys = {
        "target_skill_selector_ms",
        "answer_understanding_ms",
        "evidence_extractor_ms",
        "skill_state_updater_ms",
        "next_move_planner_ms",
        "question_generator_ms",
        "turn_aggregator_ms",
    }
    assert expected_keys.issubset(set(metrics.keys())), (
        f"Missing metric keys: {expected_keys - set(metrics.keys())}"
    )
    for key in expected_keys:
        assert isinstance(metrics[key], int), f"{key} should be int, got {type(metrics[key])}"
        assert metrics[key] >= 0, f"{key} should be non-negative"


@pytest.mark.asyncio
async def test_structured_turn_latency_log_emitted(caplog: pytest.LogCaptureFixture) -> None:
    """process_turn should emit a structured turn_latency log line."""
    manager = InterviewSessionManager()
    session = await manager.create_interview(
        _make_session_create(),
    )
    await manager.start_interview(session.interview_id)

    with caplog.at_level(logging.INFO, logger="app.managers.interview_session_manager"):
        await manager.process_turn(
            session.interview_id,
            WebSocketInboundPayload(
                message_type="answer",
                text="I built a REST API with FastAPI for a production service.",
            ),
        )

    turn_latency_lines = [
        r.message for r in caplog.records if "turn_latency" in r.message
    ]
    assert len(turn_latency_lines) == 1, (
        f"Expected 1 turn_latency log, got {len(turn_latency_lines)}"
    )
    # Extract the JSON from the log message
    log_msg = turn_latency_lines[0]
    json_str = log_msg.split("turn_latency ", 1)[1]
    data = json.loads(json_str)
    assert data["event"] == "turn_latency"
    assert data["interview_id"] == session.interview_id
    assert data["turn_index"] == 1
    assert data["backend_total_ms"] >= 0
    assert data["answer_understanding_ms"] >= 0


@pytest.mark.asyncio
async def test_pipeline_output_unchanged_with_instrumentation() -> None:
    """Instrumentation must not change the pipeline's question/move output."""
    state = InterviewState(
        interview_id="int_no_change",
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python concurrency", "API design"],
        ),
        last_question="What is the GIL in Python?",
        skill_map=SkillMap(
            skills={
                "python_concurrency": SkillNode(
                    skill_id="python_concurrency", label="Python concurrency", importance=0.9,
                ),
                "api_design": SkillNode(
                    skill_id="api_design", label="API design", importance=0.8,
                ),
            }
        ),
    )
    pipeline = TurnProcessingPipeline()
    output = await pipeline.run(
        TurnProcessingInput(
            state=state,
            answer=CandidateAnswer(transcript="I am not sure, I do not know that topic well."),
        )
    )
    # Same assertions as the existing test — behavior is unchanged
    assert output.turn.turn_id == "turn_001"
    assert output.next_move.move_type.value == "scaffold_retry"
    assert output.turn.answer_analysis.intent.value == "refusal"
    assert output.state.next_question


def _make_session_create():
    from app.models.interview import InterviewSessionCreate

    return InterviewSessionCreate(
        tenant_id="tenant_test",
        candidate_id="cand_test",
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python", "API design"],
        ),
    )
