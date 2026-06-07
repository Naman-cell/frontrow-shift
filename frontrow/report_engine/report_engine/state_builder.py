"""Translate ReportInput (SkillBrew's flat format) into InterviewState."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from report_engine.models import (
    AnswerAnalysis,
    AnswerQuality,
    CandidateAnswer,
    CandidateIntent,
    InterviewState,
    InterviewStatus,
    InterviewTurn,
    ReportInput,
    RoleContext,
    Rubric,
)

if TYPE_CHECKING:
    from report_engine.audio_analyzer import GeminiAudioAnalyzer


async def build_state(
    report_input: ReportInput,
    audio_analyzer: "GeminiAudioAnalyzer | None" = None,
) -> InterviewState:
    """Convert SkillBrew's ReportInput into an InterviewState for the pipeline.

    When *audio_analyzer* is provided and a turn carries ``answer_audio_base64``,
    the answer is analyzed by Gemini multimodal audio.  Otherwise the existing
    text heuristic is used as a fallback.
    """
    interview_id = f"int_{uuid.uuid4().hex[:16]}"

    # Build resume summary from resume_json
    resume_summary = _extract_resume_summary(report_input.resume_json)

    role = RoleContext(
        role_id=f"role_{uuid.uuid4().hex[:8]}",
        title=report_input.job_title,
        seniority=report_input.seniority,
        job_description_summary=report_input.job_description,
        resume_summary=resume_summary,
        required_skills=report_input.required_skills,
    )

    rubric = Rubric.for_seniority(report_input.seniority)

    state = InterviewState(
        interview_id=interview_id,
        status=InterviewStatus.COMPLETED,
        role=role,
        rubric=rubric,
    )
    state.seed_skills_from_role()

    # Build turns from input
    for idx, turn_input in enumerate(report_input.turns):
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)

        candidate_answer = CandidateAnswer(
            transcript=turn_input.answer_text,
            audio_base64=turn_input.answer_audio_base64,
            audio_mime_type=turn_input.audio_mime_type,
        )

        # Pick the most likely skill for this turn (round-robin through skills)
        skill_ids = list(state.skill_map.skills.keys())
        target_skill_id = skill_ids[idx % len(skill_ids)] if skill_ids else "general"
        target_skill_label = (
            state.skill_map.skills[target_skill_id].label
            if target_skill_id in state.skill_map.skills
            else "General"
        )

        # Use Gemini audio analysis when audio is present and analyzer is available;
        # fall back to the text heuristic otherwise.
        if turn_input.answer_audio_base64 and audio_analyzer is not None:
            analysis = await audio_analyzer.analyze_answer(
                audio_base64=turn_input.answer_audio_base64,
                audio_mime_type=turn_input.audio_mime_type or "audio/webm",
                question=turn_input.question_text,
                target_skill_id=target_skill_id,
                target_skill_label=target_skill_label,
                transcript=turn_input.answer_text,
                state=state,
            )
            # Gemini may redirect attribution to a different skill.
            target_skill_id = analysis.target_skill_id
            target_skill_label = analysis.target_skill_label
        else:
            quality = _assess_quality(turn_input.answer_text)
            analysis = AnswerAnalysis(
                quality=quality,
                intent=CandidateIntent.ANSWERED,
                transcript=turn_input.answer_text,
                summary=turn_input.answer_text[:200] if turn_input.answer_text else "",
                target_skill_id=target_skill_id,
                target_skill_label=target_skill_label,
                confidence=0.6,
            )

        turn = InterviewTurn(
            turn_id=turn_id,
            interview_id=interview_id,
            turn_index=idx,
            question=turn_input.question_text,
            candidate_answer=candidate_answer,
            answer_analysis=analysis,
            created_at=now,
            answered_at=now,
        )
        state.turns.append(turn)

        # Update skill map
        if target_skill_id in state.skill_map.skills:
            skill_node = state.skill_map.skills[target_skill_id]
            skill_node.attempts += 1
            skill_node.current_score = max(skill_node.current_score, _quality_to_score(analysis.quality))
            skill_node.confidence = min(1.0, skill_node.confidence + 0.2)

    return state


def _extract_resume_summary(resume_json: dict) -> str:
    """Build a text summary from SkillBrew's resume JSON."""
    if not resume_json:
        return ""
    parts = []
    for key in ["summary", "experience", "skills", "education"]:
        val = resume_json.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
        elif isinstance(val, list):
            parts.append("; ".join(str(item) for item in val[:5]))
    return " | ".join(parts)[:1000]


def _assess_quality(answer_text: str) -> AnswerQuality:
    """Simple heuristic to assess answer quality from text."""
    if not answer_text or len(answer_text.strip()) < 10:
        return AnswerQuality.UNCLEAR
    word_count = len(answer_text.split())
    if word_count < 15:
        return AnswerQuality.WEAK
    if word_count < 40:
        return AnswerQuality.PARTIAL
    # Check for concrete signal words
    text_lower = answer_text.lower()
    concrete_signals = [
        "implemented", "built", "designed", "led", "measured", "resolved", "handled", "owned"
    ]
    signal_count = sum(1 for w in concrete_signals if w in text_lower)
    if signal_count >= 3:
        return AnswerQuality.STRONG
    if signal_count >= 1:
        return AnswerQuality.CONCRETE_EXPERIENCE
    return AnswerQuality.PARTIAL


def _quality_to_score(quality: AnswerQuality) -> float:
    """Map quality to a -1..1 raw score for the skill map."""
    return {
        AnswerQuality.STRONG: 0.8,
        AnswerQuality.CONCRETE_EXPERIENCE: 0.6,
        AnswerQuality.PARTIAL: 0.2,
        AnswerQuality.SHALLOW_EXPERIENCE: 0.0,
        AnswerQuality.WEAK: -0.2,
        AnswerQuality.UNCLEAR: -0.4,
        AnswerQuality.REFUSAL: -0.6,
        AnswerQuality.OFF_TOPIC: -0.5,
        AnswerQuality.UNSUPPORTED_CLAIM: -0.3,
    }.get(quality, 0.0)
