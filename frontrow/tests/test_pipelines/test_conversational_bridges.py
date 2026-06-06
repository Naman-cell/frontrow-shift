from app.models.next_move import MoveType, NextMoveDecision
from app.models.turn import AnswerAnalysis, AnswerQuality, CandidateIntent
from app.services.audio_understanding_service import _ensure_conversational_bridge


def test_off_topic_bridge_does_not_praise_irrelevant_project() -> None:
    analysis = AnswerAnalysis(
        quality=AnswerQuality.OFF_TOPIC,
        intent=CandidateIntent.OFF_TOPIC,
        summary="Candidate gave a software example in a nurse interview.",
        target_skill_id="patient_triage",
        target_skill_label="Patient triage",
    )
    next_move = NextMoveDecision(
        move_type=MoveType.REPAIR_AND_REDIRECT,
        target_skill_id="medication_safety",
        target_skill_label="Medication safety",
        reason="Bring candidate back to role context.",
        interviewer_response="I hear you, but that example seems outside this role context.",
    )

    bridged = _ensure_conversational_bridge(
        question=(
            "Thanks for sharing that project. Let's shift back to the ED setting: "
            "How do you ensure medication safety?"
        ),
        analysis=analysis,
        next_move=next_move,
    )

    assert bridged.startswith("I hear you, but that example seems outside this role context.")
    assert "thanks for sharing" not in bridged.lower()


def test_bridge_dedupes_repeated_acknowledgement() -> None:
    analysis = AnswerAnalysis(
        quality=AnswerQuality.REFUSAL,
        intent=CandidateIntent.REFUSAL,
        summary="Candidate did not know.",
        target_skill_id="product_explanation",
        target_skill_label="Product explanation",
        suggested_interviewer_response="No worries, let's try a different angle.",
    )
    next_move = NextMoveDecision(
        move_type=MoveType.SWITCH_ADJACENT_TOPIC,
        target_skill_id="product_explanation",
        target_skill_label="Product explanation",
        reason="Switch gently.",
    )

    bridged = _ensure_conversational_bridge(
        question=(
            "No worries, let's try a different angle. "
            "No worries, let's try a different angle. How do you explain a product?"
        ),
        analysis=analysis,
        next_move=next_move,
    )

    assert bridged.lower().count("no worries, let's try a different angle") == 1
