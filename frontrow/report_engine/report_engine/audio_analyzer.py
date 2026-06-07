"""Gemini multimodal audio analysis for the report engine."""

import base64
import json
import logging
from asyncio import Semaphore
from time import perf_counter
from typing import Any

from report_engine.models import (
    AnswerAnalysis,
    AnswerQuality,
    CandidateIntent,
    InterviewState,
)

LOGGER = logging.getLogger(__name__)


class GeminiAudioAnalyzer:
    """Analyzes interview answers using Gemini multimodal (audio + text)."""

    def __init__(self, *, api_key: str, model: str = "gemini-2.5-flash") -> None:
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.semaphore = Semaphore(4)

    async def analyze_answer(
        self,
        *,
        audio_base64: str,
        audio_mime_type: str = "audio/webm",
        question: str,
        target_skill_id: str,
        target_skill_label: str,
        transcript: str = "",
        state: InterviewState | None = None,
    ) -> AnswerAnalysis:
        """Analyze an answer using Gemini multimodal audio understanding."""
        prompt = _analysis_prompt(
            question=question,
            transcript=transcript,
            target_skill_label=target_skill_label,
            state=state,
        )

        from google.genai import types

        audio_bytes = base64.b64decode(audio_base64)
        contents: list[Any] = [prompt]
        if audio_bytes:
            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime_type))

        try:
            gemini_start = perf_counter()
            async with self.semaphore:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                )
            LOGGER.info(
                "gemini_audio_analyzer interview=%s gemini_ms=%d",
                state.interview_id if state else "unknown",
                int((perf_counter() - gemini_start) * 1000),
            )
        except Exception:
            LOGGER.exception("GeminiAudioAnalyzer.analyze_answer failed; falling back")
            return AnswerAnalysis(
                quality=AnswerQuality.PARTIAL,
                intent=CandidateIntent.UNKNOWN,
                transcript=transcript,
                summary="Gemini analysis unavailable.",
                target_skill_id=target_skill_id,
                target_skill_label=target_skill_label,
            )

        parsed = _parse_json_response(getattr(response, "text", "") or "")

        quality = _coerce_quality(parsed.get("answer_quality"))
        intent = _coerce_intent(parsed.get("candidate_intent"))

        # Resolve preferred skill
        preferred_skill = _coerce_optional_text(parsed.get("preferred_relevant_skill_id"))
        effective_skill_id = target_skill_id
        effective_skill_label = target_skill_label
        if preferred_skill and state and state.skill_map.skills.get(preferred_skill):
            effective_skill_id = preferred_skill
            effective_skill_label = state.skill_map.skills[preferred_skill].label

        return AnswerAnalysis(
            quality=quality,
            intent=intent,
            transcript=(
                _coerce_optional_text(parsed.get("answer_transcript"))
                or _coerce_optional_text(parsed.get("transcript"))
                or transcript
            ),
            summary=(
                parsed.get("answer_summary")
                or parsed.get("summary")
                or "Candidate answer analyzed by Gemini."
            ),
            target_skill_id=effective_skill_id,
            target_skill_label=effective_skill_label,
            confidence=_coerce_float(parsed.get("confidence"), 0.5),
            resume_claim_detected=bool(parsed.get("resume_claim_detected", False)),
            extracted_claim=_coerce_optional_text(parsed.get("extracted_claim")),
            suggested_interviewer_response=parsed.get("suggested_interviewer_response") or "",
            suggested_next_question=parsed.get("suggested_next_question") or "",
            preferred_topics=_coerce_str_list(
                parsed.get("preferred_topics")
                or parsed.get("preferred_topics_or_domains")
                or parsed.get("preferred_domain")
            ),
            preferred_relevant_skill_id=_coerce_optional_text(parsed.get("preferred_relevant_skill_id")),
            missing_expected_points=_coerce_str_list(parsed.get("missing_expected_points")),
        )


def _analysis_prompt(
    *,
    question: str,
    transcript: str,
    target_skill_label: str,
    state: InterviewState | None = None,
) -> str:
    required_skills = ", ".join(state.role.required_skills) if state else ""
    recent_context = state.conversation_summary if state else ""
    open_threads = "; ".join(state.open_threads) if state else ""
    return f"""
You are analyzing one answer in a hiring interview.

Return only valid JSON with:
- answer_transcript: best-effort transcript of what the candidate actually said.
  If the audio is unclear, return the most likely utterance and lower confidence.
- answer_quality: one of strong, partial, weak, unclear, refusal, off_topic,
  unsupported_claim, concrete_experience, shallow_experience
- candidate_intent: one of answered, refusal, clarification_request,
  candidate_question, pivot_request, repeat_request, off_topic,
  silence_or_noise, disengaged, frustrated, unknown
- answer_summary
- observed_signals
- missing_expected_points: always an array of short strings
- resume_claim_detected
- extracted_claim
- suggested_interviewer_response: one short humane phrase, not a full question
- suggested_next_question: one natural next question that responds to this answer,
  or an empty string if the planner should choose
- preferred_topics: array of topics/domains the candidate says they are stronger in
- preferred_relevant_skill_id: if a preferred topic maps to a required skill, use
  that skill id from the required skills list; otherwise null
- confidence between 0 and 1

Field-agnostic rules:
- Do not assume the role is software, healthcare, office work, or any specific industry.
- Evaluate the answer against the role, required skills, seniority, and evidence.
- Use the role's own vocabulary. For a doctor, think patient/case/clinical judgement.
  For blue-collar work, think task/site/safety/tools/customer. For software, think
  system/project/service only when that is actually relevant.
- A good answer may describe a case, shift, customer interaction, repair, procedure,
  incident, sale, project, lesson, or decision depending on the role.
- If this is the closing candidate-question phase and the candidate asks about
  the role, process, feedback, expectations, next steps, or raises a concern,
  set candidate_intent to candidate_question.
- For candidate_question, suggested_interviewer_response must answer or
  acknowledge the specific question/concern in one or two concise sentences,
  then close politely. Do not use generic lines like "that gives me what I need".
- Never include bracketed placeholders or instructions to the interviewer such
  as "[briefly mention...]" or "e.g.". If exact team details are unknown, say
  what is available from the role brief and that the hiring team can confirm.
- If the candidate adds final evidence instead of asking a question, acknowledge
  the specific added evidence before closing.

Required skill ids and labels:
{_required_skill_lines(state) if state else required_skills}

Recent sliding-window context:
{recent_context or "none"}

Open threads:
{open_threads or "none"}

Closing candidate-question phase:
{"yes" if state and state.closing_question_sent else "no"}

Question:
{question}

Target skill:
{target_skill_label}

Candidate answer transcript/audio-derived text:
{transcript}
""".strip()


def _required_skill_lines(state: InterviewState | None) -> str:
    if state is None:
        return ""
    return "\n".join(
        f"- {skill.skill_id}: {skill.label}"
        for skill in state.skill_map.skills.values()
    )


def _parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"answer_quality": "partial", "answer_summary": cleaned[:500]}


def _coerce_quality(value: Any) -> AnswerQuality:
    try:
        return AnswerQuality(str(value))
    except Exception:
        return AnswerQuality.PARTIAL


def _coerce_intent(value: Any) -> CandidateIntent:
    try:
        return CandidateIntent(str(value))
    except Exception:
        return CandidateIntent.UNKNOWN


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a"}:
        return None
    return text


def _coerce_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default
