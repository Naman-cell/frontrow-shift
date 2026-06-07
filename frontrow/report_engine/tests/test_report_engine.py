import pytest
from report_engine.models import ReportEngineConfig, ReportInput, TurnInput
from report_engine.engine import generate_report
from report_engine.state_builder import build_state


@pytest.mark.asyncio
async def test_generate_report_heuristic():
    """Test full report generation with heuristic scoring (no Gemini)."""
    report_input = ReportInput(
        job_title="Backend Engineer",
        seniority="Mid",
        industry="Technology",
        job_description="Build scalable APIs",
        required_skills=["Python", "SQL", "System Design"],
        turns=[
            TurnInput(
                question_text="Tell me about your experience with Python.",
                answer_text="I have been working with Python for 5 years. I built a microservices platform handling 10k requests per second using FastAPI. I designed the async pipeline and measured latency improvements of 40%.",
            ),
            TurnInput(
                question_text="How do you approach database design?",
                answer_text="I led the migration from a monolithic PostgreSQL database to a sharded architecture. I owned the data modeling, implemented connection pooling, and resolved deadlock issues in production.",
            ),
            TurnInput(
                question_text="Describe a system design challenge you faced.",
                answer_text="I designed a real-time notification system that handled 1M concurrent WebSocket connections. I chose Redis pub/sub for message fanout and measured the p99 latency at under 50ms.",
            ),
        ],
    )
    config = ReportEngineConfig(use_gemini=False)
    report = await generate_report(report_input, config)

    assert report.interview_id.startswith("int_")
    assert report.role_bar == 100
    assert report.fit_score >= 0
    assert report.fit_score <= 100
    assert report.verdict in {"advance", "hold", "needs_review"}
    assert len(report.score_composition) == 4
    assert len(report.skill_role_match) >= 3
    assert report.question_count == 3
    assert report.evidence_count >= 0


def test_build_state():
    """Test that ReportInput is correctly converted to InterviewState."""
    report_input = ReportInput(
        job_title="Data Scientist",
        seniority="Senior",
        required_skills=["Machine Learning", "Python", "Statistics"],
        turns=[
            TurnInput(
                question_text="What ML models have you deployed?",
                answer_text="I deployed a recommendation engine using collaborative filtering at scale.",
            ),
        ],
    )
    state = build_state(report_input)

    assert state.role.title == "Data Scientist"
    assert state.role.seniority == "Senior"
    assert len(state.skill_map.skills) == 3
    assert len(state.turns) == 1
    assert state.turns[0].question == "What ML models have you deployed?"
    assert state.turns[0].candidate_answer is not None
    assert state.turns[0].answer_analysis is not None


def test_report_input_validation():
    """Test that ReportInput requires at least one turn."""
    with pytest.raises(Exception):
        ReportInput(
            job_title="Engineer",
            turns=[],
        )
