import pytest

from app.models.interview import InterviewSession, RoleContext
from app.models.next_move import MoveType
from app.pipelines.initialization.pipeline import InterviewInitializationInput, InterviewInitializationPipeline


@pytest.mark.asyncio
async def test_initialization_uses_field_agnostic_opening_for_non_software_role() -> None:
    pipeline = InterviewInitializationPipeline()
    session = InterviewSession(
        interview_id="int_field_agnostic",
        tenant_id="tenant_demo",
        candidate_id="candidate_demo",
        duration_minutes=20,
        role=RoleContext(
            title="Emergency Room Nurse",
            seniority="junior",
            job_description_summary="Provide safe patient care in a busy emergency department.",
            resume_summary="Candidate has clinical rotations and patient triage exposure.",
            required_skills=["Patient triage", "Medication safety", "Communication"],
        ),
    )

    output = await pipeline.run(InterviewInitializationInput(session=session))

    assert output.first_question.startswith("Hi, thanks for joining.")
    assert "project" not in output.first_question.lower()
    assert output.state.rubric.dimensions[2].weight == 0.30
    assert output.state.last_next_move is not None
    assert output.state.last_next_move.move_type == MoveType.OPEN_TOPIC
    assert output.state.last_next_move.target_skill_id == "patient_triage"


@pytest.mark.asyncio
async def test_initialization_stays_field_agnostic_for_blue_collar_role() -> None:
    pipeline = InterviewInitializationPipeline()
    session = InterviewSession(
        interview_id="int_blue_collar",
        tenant_id="tenant_demo",
        candidate_id="candidate_demo",
        duration_minutes=5,
        role=RoleContext(
            title="Warehouse Forklift Operator",
            seniority="entry",
            job_description_summary="Move inventory safely, follow site procedures, and support shift operations.",
            resume_summary="Candidate has warehouse shift experience and basic equipment handling.",
            required_skills=["Forklift safety", "Inventory handling", "Shift communication"],
        ),
    )

    output = await pipeline.run(InterviewInitializationInput(session=session))
    question = output.first_question.lower()

    assert "forklift safety" in question
    assert "api" not in question
    assert "software" not in question
    assert "project" not in question
    assert output.state.last_next_move is not None
    assert output.state.last_next_move.target_skill_id == "forklift_safety"
