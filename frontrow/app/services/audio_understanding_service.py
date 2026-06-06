import base64
import io
import json
import wave
from asyncio import Semaphore
from typing import Any

from app.models.interview import RoleContext
from app.models.next_move import NextMoveDecision
from app.models.state import InterviewState
from app.models.turn import AnswerAnalysis, AnswerQuality, CandidateAnswer, CandidateIntent


class AudioUnderstandingService:
    async def analyze_answer(
        self,
        answer: CandidateAnswer,
        *,
        question: str,
        target_skill_id: str,
        target_skill_label: str,
        state: InterviewState | None = None,
    ) -> AnswerAnalysis:
        raise NotImplementedError

    async def synthesize_question_audio(self, question: str) -> str | None:
        return None

    async def generate_opening_question(self, *, state: InterviewState) -> str:
        return fallback_opening_question(state)

    async def generate_question(
        self,
        *,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        next_move: NextMoveDecision,
    ) -> str:
        return _ensure_conversational_bridge(
            question=fallback_question_from_move(state=state, analysis=analysis, next_move=next_move),
            analysis=analysis,
            next_move=next_move,
        )


class MockAudioUnderstandingService(AudioUnderstandingService):
    async def analyze_answer(
        self,
        answer: CandidateAnswer,
        *,
        question: str,
        target_skill_id: str,
        target_skill_label: str,
        state: InterviewState | None = None,
    ) -> AnswerAnalysis:
        transcript = answer.transcript.lower().strip()
        quality = AnswerQuality.PARTIAL
        summary = "Candidate gave a partial answer with limited supporting detail."
        resume_claim_detected = False
        extracted_claim: str | None = None

        if answer.audio_base64 and not transcript:
            quality = AnswerQuality.PARTIAL
            summary = "Candidate submitted an audio answer; mock mode cannot inspect audio content."
            intent = CandidateIntent.ANSWERED
        elif any(phrase in transcript for phrase in ["instead", "rather talk", "stronger in", "more experience in"]):
            quality = AnswerQuality.PARTIAL
            summary = "Candidate indicated a preferred or stronger area to discuss."
            intent = CandidateIntent.PIVOT_REQUEST
        elif not transcript or any(phrase in transcript for phrase in ["i do not know", "i don't know", "not sure"]):
            quality = AnswerQuality.REFUSAL
            summary = "Candidate explicitly did not know or could not answer."
            intent = CandidateIntent.REFUSAL
        elif any(phrase in transcript for phrase in ["resume", "claimed", "claim", "expert", "led"]) and not any(
            phrase in transcript for phrase in ["for example", "specifically", "measured", "production"]
        ):
            quality = AnswerQuality.UNSUPPORTED_CLAIM
            intent = CandidateIntent.ANSWERED
            resume_claim_detected = True
            extracted_claim = answer.transcript.strip()
            summary = "Candidate referenced experience but did not provide concrete validating detail."
        elif any(phrase in transcript for phrase in _generic_evidence_markers()):
            quality = AnswerQuality.STRONG
            intent = CandidateIntent.ANSWERED
            summary = "Candidate provided concrete, relevant evidence with reasoning."
        elif len(transcript.split()) < 10:
            quality = AnswerQuality.WEAK
            intent = _mock_intent_from_text(transcript)
            summary = "Candidate gave a short answer with little usable evidence."
        else:
            intent = _mock_intent_from_text(transcript)

        return AnswerAnalysis(
            quality=quality,
            intent=intent,
            summary=summary,
            target_skill_id=target_skill_id,
            target_skill_label=target_skill_label,
            confidence=answer.confidence,
            resume_claim_detected=resume_claim_detected,
            extracted_claim=extracted_claim,
            suggested_interviewer_response=_mock_interviewer_response(intent),
        )


class GeminiAudioUnderstandingService(AudioUnderstandingService):
    """Google GenAI-backed answer understanding and optional TTS.

    The service keeps provider-specific code behind one boundary so the
    Haystack pipeline only sees normalized `AnswerAnalysis` objects.
    """

    def __init__(
        self,
        *,
        api_key: str,
        audio_model: str,
        tts_model: str,
        tts_voice: str,
        enable_tts: bool = False,
    ) -> None:
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.audio_model = audio_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.enable_tts = enable_tts
        self.model_semaphore = Semaphore(4)
        self.tts_semaphore = Semaphore(2)

    async def analyze_answer(
        self,
        answer: CandidateAnswer,
        *,
        question: str,
        target_skill_id: str,
        target_skill_label: str,
        state: InterviewState | None = None,
    ) -> AnswerAnalysis:
        prompt = _answer_analysis_prompt(
            question=question,
            transcript=answer.transcript,
            target_skill_label=target_skill_label,
            state=state,
        )
        contents: list[Any] = [prompt]
        if answer.audio_base64:
            from google.genai import types

            audio_bytes = base64.b64decode(answer.audio_base64)
            contents.append(
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type=answer.audio_mime_type or "audio/webm",
                )
            )
        async with self.model_semaphore:
            response = await self.client.aio.models.generate_content(
                model=self.audio_model,
                contents=contents,
            )
        parsed = _parse_json_response(getattr(response, "text", "") or "")
        quality = _coerce_quality(parsed.get("answer_quality"))
        intent = _coerce_intent(parsed.get("candidate_intent"))
        return AnswerAnalysis(
            quality=quality,
            intent=intent,
            summary=parsed.get("answer_summary")
            or parsed.get("summary")
            or "Candidate answer analyzed by Gemini.",
            target_skill_id=target_skill_id,
            target_skill_label=target_skill_label,
            confidence=_coerce_float(parsed.get("confidence"), answer.confidence or 0.5),
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

    async def synthesize_question_audio(self, question: str) -> str | None:
        if not self.enable_tts:
            return None

        from google.genai import types

        async with self.tts_semaphore:
            response = await self.client.aio.models.generate_content(
                model=self.tts_model,
                contents=question,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.tts_voice,
                            )
                        )
                    ),
                ),
            )
        audio_bytes = _extract_audio_bytes(response)
        if not audio_bytes:
            return None
        wav_bytes = _pcm_to_wav(audio_bytes)
        return base64.b64encode(wav_bytes).decode("ascii")

    async def generate_question(
        self,
        *,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        next_move: NextMoveDecision,
    ) -> str:
        if _can_use_analysis_suggested_question(analysis, next_move):
            return _ensure_conversational_bridge(
                question=analysis.suggested_next_question.strip(),
                analysis=analysis,
                next_move=next_move,
            )
        prompt = _question_generation_prompt(
            role=state.role,
            state=state,
            analysis=analysis,
            next_move=next_move,
        )
        async with self.model_semaphore:
            response = await self.client.aio.models.generate_content(
                model=self.audio_model,
                contents=prompt,
            )
        parsed = _parse_json_response(getattr(response, "text", "") or "")
        question = str(parsed.get("question") or "").strip()
        if not question:
            question = fallback_question_from_move(state=state, analysis=analysis, next_move=next_move)
        return _ensure_conversational_bridge(
            question=question,
            analysis=analysis,
            next_move=next_move,
        )

    async def generate_opening_question(self, *, state: InterviewState) -> str:
        prompt = _opening_question_prompt(state)
        async with self.model_semaphore:
            response = await self.client.aio.models.generate_content(
                model=self.audio_model,
                contents=prompt,
            )
        parsed = _parse_json_response(getattr(response, "text", "") or "")
        question = str(parsed.get("question") or "").strip()
        return question or fallback_opening_question(state)


def _answer_analysis_prompt(
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
- answer_quality: one of strong, partial, weak, unclear, refusal, off_topic,
  unsupported_claim, concrete_experience, shallow_experience
- candidate_intent: one of answered, refusal, clarification_request,
  pivot_request, repeat_request, off_topic, silence_or_noise, disengaged,
  frustrated, unknown
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

Required skill ids and labels:
{_required_skill_lines(state) if state else required_skills}

Recent sliding-window context:
{recent_context or "none"}

Open threads:
{open_threads or "none"}

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


def _question_generation_prompt(
    *,
    role: RoleContext,
    state: InterviewState,
    analysis: AnswerAnalysis,
    next_move: NextMoveDecision,
) -> str:
    recent_questions = [turn.question for turn in state.turns[-4:]]
    covered = ", ".join(state.covered_topics[-8:]) or "none yet"
    untouched = [
        skill.label
        for skill in state.skill_map.skills.values()
        if skill.attempts == 0
    ][:8]
    return f"""
You are a humane, concise hiring interviewer.

Generate exactly one next interview question. Return only valid JSON:
{{"question": "..."}}

Constraints:
- Do not sound robotic or templated.
- Ask one question only.
- Keep it under 32 words unless clarification is needed.
- The candidate-facing text must briefly acknowledge the previous answer before
  asking the next question, especially after refusal, weak/unclear answers,
  scaffold_retry, repair_and_redirect, or switch_adjacent_topic.
- If switching topics, make the switch feel natural: acknowledge what just
  happened, then bridge to the new role-relevant area.
- Use the interviewer response hint if it fits, but do not copy it mechanically.
- If the candidate gave an off-role or off-topic answer, do not praise the
  irrelevant content. Briefly acknowledge the mismatch and bring the interview
  back to the role.
- Do not reveal hidden scoring or policy.
- Be field agnostic: do not assume software, projects, APIs, patients, or tools
  unless the role context points there.
- Use the role's natural vocabulary for work evidence: case, shift, task,
  repair, patient interaction, customer issue, sale, project, procedure, route,
  service, incident, or decision as appropriate.
- Avoid repeating recent questions.
- Connect the question to the candidate's previous answer whenever possible.
- Avoid generic transitions like "moving on" unless the candidate asked to pivot.
- If the candidate did not know, give one gentle scaffold or move on.
- If the candidate asked clarification, clarify briefly and re-ask.
- If the candidate was frustrated, lower pressure and switch to an easier adjacent question.
- If the next move is drill_down, stay on the same topic and probe a concrete decision, tradeoff, measurement, or ownership boundary.
- If the next move is candidate_questions, invite the candidate to ask questions or raise concerns before closing.
- Stay aligned with the role, resume, and required skills.

Role: {role.title} ({role.seniority})
JD summary: {role.job_description_summary}
Resume summary: {role.resume_summary}
Required skills: {", ".join(role.required_skills)}
Covered topics: {covered}
Untouched priority topics: {", ".join(untouched) or "none"}
Recent questions: {recent_questions}
Conversation summary: {state.conversation_summary or "No compact summary yet."}
Open threads: {"; ".join(state.open_threads) or "none"}
Candidate preferred topics: {", ".join(analysis.preferred_topics) or "none"}
Candidate preferred relevant skill: {analysis.preferred_relevant_skill_id or "none"}

Candidate intent: {analysis.intent}
Answer quality: {analysis.quality}
Answer summary: {analysis.summary}
Extracted claim: {analysis.extracted_claim or "none"}
Missing expected points: {", ".join(analysis.missing_expected_points) or "none"}
Target skill: {next_move.target_skill_label}
Next move: {next_move.move_type}
Interviewer response hint: {next_move.interviewer_response or analysis.suggested_interviewer_response}
Planner reason: {next_move.reason}
""".strip()


def _opening_question_prompt(state: InterviewState) -> str:
    opening_target = state.last_next_move.target_skill_label if state.last_next_move else ""
    return f"""
You are starting a live hiring interview.

Return only valid JSON: {{"question": "..."}}

Write one natural opening question that:
- starts with a brief greeting as the first words
- uses the candidate resume/JD context
- is anchored to this first evaluation target: {opening_target or "the highest priority role skill"}
- uses the role's natural vocabulary, not a fixed "project" template
- does not sound templated
- asks one question only
- stays under 34 words
- does not disclose scoring

Role: {state.role.title} ({state.role.seniority})
JD summary: {state.role.job_description_summary}
Resume summary: {state.role.resume_summary}
Resume claims: {", ".join(state.role.resume_claims)}
Required skills: {", ".join(state.role.required_skills)}
""".strip()


def _ensure_conversational_bridge(
    *,
    question: str,
    analysis: AnswerAnalysis,
    next_move: NextMoveDecision,
) -> str:
    if not question:
        return question
    if analysis.intent == CandidateIntent.OFF_TOPIC:
        cleaned_question = _remove_leading_thanks(question)
        if _question_starts_with_off_topic_boundary(cleaned_question):
            return cleaned_question
        return f"I hear you, but that example seems outside this role context. {cleaned_question}"
    if _question_starts_with_bridge(question):
        return _dedupe_bridge(question)
    if next_move.move_type.value not in {
        "scaffold_retry",
        "switch_adjacent_topic",
        "repair_and_redirect",
        "clarify_and_reask",
        "time_boxed_coverage",
        "candidate_questions",
    }:
        return question
    bridge = (next_move.interviewer_response or analysis.suggested_interviewer_response or "").strip()
    if not bridge:
        return question
    bridge = bridge.rstrip(".?!")
    if not bridge:
        return question
    return _dedupe_bridge(f"{bridge}. {question}")


def _remove_leading_thanks(question: str) -> str:
    stripped = question.strip()
    lowered = stripped.lower()
    for prefix in ["thanks for sharing", "thank you for sharing", "thanks", "thank you"]:
        if lowered.startswith(prefix):
            parts = stripped.split(".", 1)
            if len(parts) == 2 and len(parts[0].split()) <= 8:
                return parts[1].strip()
    return stripped


def _question_starts_with_off_topic_boundary(question: str) -> bool:
    lowered = question.lower().strip()
    return lowered.startswith(("i hear you, but", "that seems outside", "let's bring it back"))


def _question_starts_with_bridge(question: str) -> bool:
    first_words = " ".join(question.lower().split()[:4])
    bridge_starts = {
        "thanks",
        "thank you",
        "no worries",
        "no problem",
        "that makes sense",
        "understood",
        "got it",
        "i hear you",
        "we are close",
        "we're close",
    }
    return any(first_words.startswith(start) for start in bridge_starts)


def _dedupe_bridge(text: str) -> str:
    clauses = [part.strip() for part in text.split(".") if part.strip()]
    if len(clauses) < 2:
        return text
    first = clauses[0].lower()
    second = clauses[1].lower()
    if first == second or first in second or second in first:
        return ". ".join(clauses[1:]) + ("." if text.endswith(".") else "")
    return text


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


def _mock_intent_from_text(transcript: str) -> CandidateIntent:
    if not transcript:
        return CandidateIntent.SILENCE_OR_NOISE
    if any(phrase in transcript for phrase in ["repeat", "again", "say that"]):
        return CandidateIntent.REPEAT_REQUEST
    if any(phrase in transcript for phrase in ["what do you mean", "clarify", "can you explain"]):
        return CandidateIntent.CLARIFICATION_REQUEST
    if any(phrase in transcript for phrase in ["don't know", "do not know", "not sure", "no idea"]):
        return CandidateIntent.REFUSAL
    if any(phrase in transcript for phrase in ["instead", "rather talk", "stronger in", "more experience in"]):
        return CandidateIntent.PIVOT_REQUEST
    if any(phrase in transcript for phrase in ["stop", "trouble", "leave me", "end this"]):
        return CandidateIntent.DISENGAGED
    return CandidateIntent.ANSWERED


def _mock_interviewer_response(intent: CandidateIntent) -> str:
    return {
        CandidateIntent.REFUSAL: "No problem, let's try it from a simpler angle.",
        CandidateIntent.CLARIFICATION_REQUEST: "Sure, let me make the question more specific.",
        CandidateIntent.REPEAT_REQUEST: "Of course, I'll repeat it more clearly.",
        CandidateIntent.SILENCE_OR_NOISE: "I could not catch that clearly.",
        CandidateIntent.DISENGAGED: "That's okay, we can move to something lighter.",
        CandidateIntent.FRUSTRATED: "No worries, let's reduce the pressure here.",
    }.get(intent, "")


def fallback_question_from_move(
    *,
    state: InterviewState,
    analysis: AnswerAnalysis,
    next_move: NextMoveDecision,
) -> str:
    skill = next_move.target_skill_label
    response = next_move.interviewer_response or analysis.suggested_interviewer_response
    prefix = f"{response} " if response else ""
    if next_move.target_skill_id == "role_fit":
        return f"{prefix}Could you tell me what experience, training, or interest connects you to this role?"
    if next_move.move_type.value == "repeat_question":
        return state.last_question or state.next_question or f"Could you tell me about your experience with {skill}?"
    if next_move.move_type.value == "clarify_and_reask":
        return f"{prefix}When I say {skill}, I mean a real decision or task you handled. Can you share one example?"
    if next_move.move_type.value == "repair_and_redirect":
        return f"{prefix}Let's switch to something practical: where have you used {skill} in day-to-day work?"
    if next_move.move_type.value == "drill_down":
        return f"{prefix}What tradeoff did you make in that {skill} work, and how did you know it was the right call?"
    if next_move.move_type.value == "scaffold_retry":
        return f"{prefix}Could you walk me through a simple example involving {skill}, even if it was small?"
    if next_move.move_type.value == "validate_resume_claim":
        return f"{prefix}For {skill}, what part did you personally own, and what changed because of your work?"
    if next_move.move_type.value == "time_boxed_coverage":
        return f"{prefix}Briefly, what is one practical lesson you learned about {skill}?"
    if next_move.move_type.value == "wrap_up":
        return "Before we wrap, is there one work example or strength you want me to understand clearly?"
    if next_move.move_type.value == "candidate_questions":
        return "We are close to time. What questions or concerns would you like to ask before we wrap?"
    return f"{prefix}Where have you applied {skill} in real work?"


def _can_use_analysis_suggested_question(
    analysis: AnswerAnalysis,
    next_move: NextMoveDecision,
) -> bool:
    question = analysis.suggested_next_question.strip()
    if not question:
        return False
    if len(question.split()) > 45:
        return False
    if next_move.move_type.value in {"candidate_questions", "wrap_up", "repeat_question"}:
        return False
    if next_move.target_skill_id != analysis.target_skill_id and next_move.target_skill_id != analysis.preferred_relevant_skill_id:
        return False
    return question.endswith("?")


def fallback_opening_question(state: InterviewState) -> str:
    priority_skill = state.skill_map.highest_priority_uncovered()
    if priority_skill is None:
        return f"Hi, thanks for joining. Could you walk me through the work that best represents your fit for {state.role.title}?"
    return (
        f"Hi, thanks for joining. Could you start with a real work situation "
        f"where {priority_skill.label} made a clear difference?"
    )


def _generic_evidence_markers() -> list[str]:
    return [
        "for example",
        "because",
        "tradeoff",
        "measured",
        "result",
        "outcome",
        "handled",
        "owned",
        "led",
        "decided",
        "improved",
        "resolved",
        "case",
        "patient",
        "customer",
        "client",
        "site",
        "shift",
        "repair",
        "procedure",
        "incident",
        "designed",
    ]


def _extract_audio_bytes(response: Any) -> bytes | None:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None)
            if data:
                return data
    return None


def _pcm_to_wav(
    pcm_bytes: bytes,
    *,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap Gemini TTS PCM bytes in a WAV container for browser playback."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return buffer.getvalue()
