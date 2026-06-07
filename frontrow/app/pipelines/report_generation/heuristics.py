"""Heuristic scoring functions for report generation.

These are the original keyword-based and quality-enum-based scoring functions.
They serve as the fallback when Gemini-backed scoring is unavailable.
"""

from app.models.report import SoftLayerSection
from app.models.state import InterviewState
from app.models.turn import AnswerQuality


def dimension_scores_4(state: InterviewState, skill_scores_4: dict[str, float]) -> dict[str, float]:
    field_skills = [skill for skill in state.skill_map.skills.values() if skill.attempts > 0]
    total_importance = sum(skill.importance for skill in field_skills) or 1.0
    field_score = sum(skill_scores_4[skill.skill_id] * skill.importance for skill in field_skills) / total_importance
    quality_values = [
        quality_score_4(turn.answer_analysis.quality)
        for turn in state.turns
        if turn.answer_analysis is not None
    ]
    evidence_depth = [
        answer_depth_score(
            turn.candidate_answer.transcript if turn.candidate_answer else "",
            turn.answer_analysis.summary,
            turn.answer_analysis.quality,
        )
        for turn in state.turns
        if turn.answer_analysis is not None
    ]
    return {
        "field_expertise": round(field_score, 2) if field_skills else 0.0,
        "experience_depth": round(sum(evidence_depth) / len(evidence_depth), 2) if evidence_depth else 0.0,
        "communication": round(sum(quality_values) / len(quality_values), 2) if quality_values else 0.0,
        "behavioral_ownership": round(ownership_score(state), 2),
    }


def quality_score_4(quality: AnswerQuality) -> float:
    return {
        AnswerQuality.STRONG: 4.0,
        AnswerQuality.CONCRETE_EXPERIENCE: 3.5,
        AnswerQuality.PARTIAL: 2.5,
        AnswerQuality.SHALLOW_EXPERIENCE: 2.0,
        AnswerQuality.WEAK: 1.75,
        AnswerQuality.UNCLEAR: 1.5,
        AnswerQuality.UNSUPPORTED_CLAIM: 1.5,
        AnswerQuality.REFUSAL: 1.0,
        AnswerQuality.OFF_TOPIC: 1.0,
    }.get(quality, 2.0)


def answer_depth_score(transcript: str, summary: str, quality: AnswerQuality) -> float:
    if quality in {AnswerQuality.REFUSAL, AnswerQuality.OFF_TOPIC, AnswerQuality.UNCLEAR}:
        return 1.0
    if quality in {AnswerQuality.WEAK, AnswerQuality.UNSUPPORTED_CLAIM}:
        return 1.25
    if quality == AnswerQuality.SHALLOW_EXPERIENCE:
        return 1.5
    if quality == AnswerQuality.PARTIAL:
        base = 1.75
    elif quality == AnswerQuality.CONCRETE_EXPERIENCE:
        base = 2.75
    elif quality == AnswerQuality.STRONG:
        base = 3.0
    else:
        base = 1.5
    text = f"{transcript} {summary}".lower()
    if contains_interview_criticism(text):
        return 1.0
    signal_words = [
        "owned", "measured", "tradeoff", "result", "outcome",
        "handled", "resolved", "improved", "decided", "led",
        "case", "patient", "customer", "client", "site",
        "shift", "repair", "procedure", "incident", "designed",
    ]
    score = base + min(sum(1 for word in signal_words if word in text) * 0.18, 0.75)
    return max(1.0, min(4.0, score))


def ownership_score(state: InterviewState) -> float:
    if not state.turns:
        return 0.0
    ownership_words = [
        "owned", "led", "designed", "measured", "decided",
        "implemented", "handled", "resolved", "coordinated",
        "trained", "improved", "managed", "delivered", "followed up",
    ]
    positive_turns = [
        turn
        for turn in state.turns
        if turn.answer_analysis is not None
        and turn.answer_analysis.quality
        in {AnswerQuality.PARTIAL, AnswerQuality.STRONG, AnswerQuality.CONCRETE_EXPERIENCE}
    ]
    if not positive_turns:
        return 1.0
    text = " ".join(
        f"{turn.candidate_answer.transcript if turn.candidate_answer else ''} "
        f"{turn.answer_analysis.summary if turn.answer_analysis else ''}"
        for turn in positive_turns
    ).lower()
    if contains_interview_criticism(text):
        return 1.0
    ownership_hits = sum(1 for word in ownership_words if word in text)
    if ownership_hits == 0:
        return 1.25
    return max(1.0, min(4.0, 1.25 + ownership_hits * 0.3))


def contains_interview_criticism(text: str) -> bool:
    criticism_phrases = [
        "templated", "impersonal", "not human", "robotic",
        "questioning the interviewer", "criticizes the interview",
        "criticizes the interviewer", "why the interviewer repeated",
    ]
    return any(phrase in text for phrase in criticism_phrases)


def report_rationale(
    state: InterviewState,
    *,
    fit_score: int,
    strengths: list,
    risks: list,
) -> str:
    if fit_score >= 75:
        base = f"Candidate clears the role bar for {state.role.title} based on captured evidence."
    elif fit_score >= 60:
        base = f"Candidate is close to the role bar for {state.role.title}, but the next round should resolve gaps."
    else:
        base = f"Candidate does not yet clear the role bar for {state.role.title} based on this interview."
    if strengths:
        base += f" Strongest signal: {strengths[0].summary}"
    if risks:
        base += f" Main concern: {risks[0].summary}"
    return base


def soft_layer(state: InterviewState, dimension_scores: dict[str, float]) -> list[SoftLayerSection]:
    communication = dimension_scores.get("communication", 0.0)
    ownership = dimension_scores.get("behavioral_ownership", 0.0)
    return [
        SoftLayerSection(
            label="Communication",
            score_4=communication,
            facets={
                "clarity_structure": min(4.0, communication + 0.25),
                "use_of_examples": communication,
                "conciseness": max(1.0, communication - 0.25),
            },
            note="Scored from answer content and structure, not accent, pace, tone, or fluency.",
        ),
        SoftLayerSection(
            label="Behavioural and ownership",
            score_4=ownership,
            facets={
                "ownership_of_outcomes": ownership,
                "initiative_beyond_scope": min(4.0, ownership + 0.25),
                "accountability": max(1.0, ownership - 0.25),
            },
            note="STAR-style evidence inferred from concrete ownership, decisions, and measured outcomes.",
        ),
    ]
