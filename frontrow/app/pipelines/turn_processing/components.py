import logging
import os
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "false")

from haystack import component

from app.models.evidence import EvidenceRecord, EvidenceSignalType
from app.models.next_move import MoveType, NextMoveDecision
from app.models.skill_map import SkillStatus
from app.models.state import InterviewState
from app.models.turn import AnswerAnalysis, AnswerQuality, CandidateAnswer, InterviewTurn
from app.pipelines.turn_processing.processors.next_move_planning import NextMovePlanner
from app.services.audio_understanding_service import (
    AudioUnderstandingService,
    MockAudioUnderstandingService,
    fallback_question_from_move,
)

LOGGER = logging.getLogger(__name__)


@component
class TargetSkillSelector:
    """Select the skill that should frame answer analysis for this turn."""

    @component.output_types(state=InterviewState, target_skill_id=str, target_skill_label=str)
    def run(self, state: InterviewState) -> dict:
        started_at = perf_counter()
        state.runtime_metrics = {}
        target_skill = state.skill_map.highest_priority_uncovered()
        if state.last_next_move is not None:
            target_skill = state.skill_map.get_or_create(
                state.last_next_move.target_skill_id,
                state.last_next_move.target_skill_label,
            )
        if target_skill is None:
            target_skill = state.skill_map.get_or_create("role_fit", "Role fit")
        _record_metric(state, "target_skill_selector_ms", started_at)
        return {
            "state": state,
            "target_skill_id": target_skill.skill_id,
            "target_skill_label": target_skill.label,
        }


@component
class AnswerUnderstandingNode:
    """Analyze candidate answer audio/transcript behind a provider abstraction."""

    def __init__(self, service: AudioUnderstandingService | None = None) -> None:
        self.service = service or MockAudioUnderstandingService()

    @component.output_types(state=InterviewState, answer=CandidateAnswer, analysis=AnswerAnalysis)
    def run(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        target_skill_id: str,
        target_skill_label: str,
    ) -> dict:
        raise NotImplementedError(
            "AnswerUnderstandingNode only supports async execution. Use run_async()."
        )

    @component.output_types(state=InterviewState, answer=CandidateAnswer, analysis=AnswerAnalysis)
    async def run_async(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        target_skill_id: str,
        target_skill_label: str,
    ) -> dict:
        started_at = perf_counter()
        try:
            analysis = await self.service.analyze_answer(
                answer,
                question=state.last_question or state.next_question or "",
                target_skill_id=target_skill_id,
                target_skill_label=target_skill_label,
                state=state,
            )
        except Exception:
            LOGGER.exception("Answer understanding provider failed; falling back to local analysis.")
            analysis = await MockAudioUnderstandingService().analyze_answer(
                answer,
                question=state.last_question or state.next_question or "",
                target_skill_id=target_skill_id,
                target_skill_label=target_skill_label,
                state=state,
            )
            analysis.confidence = min(analysis.confidence, 0.25)
            analysis.summary = f"Provider unavailable; fallback analysis used. {analysis.summary}"
        if analysis.transcript and not answer.transcript:
            answer.transcript = analysis.transcript
        if analysis.summary and not answer.analysis_summary:
            answer.analysis_summary = analysis.summary
        _record_metric(state, "answer_understanding_ms", started_at)
        return {"state": state, "answer": answer, "analysis": analysis}


@component
class EvidenceExtractorNode:
    """Convert answer analysis into durable evidence records."""

    @component.output_types(
        state=InterviewState,
        answer=CandidateAnswer,
        analysis=AnswerAnalysis,
        evidence=list[EvidenceRecord],
    )
    def run(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
    ) -> dict:
        started_at = perf_counter()
        signal_type = {
            AnswerQuality.STRONG: EvidenceSignalType.STRONG_EVIDENCE,
            AnswerQuality.CONCRETE_EXPERIENCE: EvidenceSignalType.CONCRETE_EXPERIENCE,
            AnswerQuality.REFUSAL: EvidenceSignalType.REFUSAL,
            AnswerQuality.UNSUPPORTED_CLAIM: EvidenceSignalType.UNSUPPORTED_CLAIM,
            AnswerQuality.PARTIAL: EvidenceSignalType.PARTIAL_UNDERSTANDING,
        }.get(analysis.quality, EvidenceSignalType.LOW_CONFIDENCE)
        score_delta = {
            EvidenceSignalType.STRONG_EVIDENCE: 0.25,
            EvidenceSignalType.CONCRETE_EXPERIENCE: 0.2,
            EvidenceSignalType.PARTIAL_UNDERSTANDING: 0.05,
            EvidenceSignalType.UNSUPPORTED_CLAIM: -0.05,
            EvidenceSignalType.REFUSAL: -0.15,
        }.get(signal_type, 0.0)
        turn_id = f"turn_{len(state.turns) + 1:03d}"
        skill = state.skill_map.get_or_create(
            analysis.target_skill_id,
            analysis.target_skill_label,
        )
        record = EvidenceRecord(
            evidence_id=f"ev_{uuid4().hex[:10]}",
            interview_id=state.interview_id,
            turn_id=turn_id,
            skill_id=analysis.target_skill_id,
            dimension=skill.dimension,
            signal_type=signal_type,
            summary=analysis.summary,
            score_delta=score_delta,
            confidence=analysis.confidence,
            quote_or_audio_ref=answer.audio_ref or answer.transcript[:180],
        )
        state.evidence_ledger.append(record)
        _record_metric(state, "evidence_extractor_ms", started_at)
        return {
            "state": state,
            "answer": answer,
            "analysis": analysis,
            "evidence": [record],
        }


@component
class SkillStateUpdaterNode:
    """Apply extracted evidence to the evolving skill map."""

    @component.output_types(
        state=InterviewState,
        answer=CandidateAnswer,
        analysis=AnswerAnalysis,
        evidence=list[EvidenceRecord],
    )
    def run(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        evidence: list[EvidenceRecord],
    ) -> dict:
        started_at = perf_counter()
        skill = state.skill_map.get_or_create(
            analysis.target_skill_id,
            analysis.target_skill_label,
        )
        skill.attempts += 1
        skill.evidence_ids.extend(record.evidence_id for record in evidence)

        if analysis.quality in {AnswerQuality.STRONG, AnswerQuality.CONCRETE_EXPERIENCE}:
            skill.current_score = min(skill.current_score + 0.25, 1.0)
            skill.confidence = min(skill.confidence + 0.35, 1.0)
            skill.status = (
                SkillStatus.SUFFICIENT
                if skill.confidence >= 0.65
                else SkillStatus.IN_PROGRESS
            )
        elif analysis.quality == AnswerQuality.REFUSAL:
            skill.current_score = max(skill.current_score - 0.15, -1.0)
            skill.confidence = min(skill.confidence + 0.2, 1.0)
            skill.status = SkillStatus.LOW_CONFIDENCE
        elif analysis.quality == AnswerQuality.UNSUPPORTED_CLAIM:
            skill.status = SkillStatus.NEEDS_VALIDATION
            skill.confidence = min(skill.confidence + 0.1, 1.0)
        else:
            skill.scaffold_attempts += 1
            skill.current_score = min(skill.current_score + 0.05, 1.0)
            skill.confidence = min(skill.confidence + 0.15, 1.0)
            skill.status = SkillStatus.IN_PROGRESS

        _record_metric(state, "skill_state_updater_ms", started_at)
        return {
            "state": state,
            "answer": answer,
            "analysis": analysis,
            "evidence": evidence,
        }


@component
class NextMovePlannerNode:
    """Choose the next interviewing move before generating question wording."""

    def __init__(self, planner: NextMovePlanner | None = None) -> None:
        self.planner = planner or NextMovePlanner()

    @component.output_types(
        state=InterviewState,
        answer=CandidateAnswer,
        analysis=AnswerAnalysis,
        evidence=list[EvidenceRecord],
        next_move=NextMoveDecision,
    )
    def run(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        evidence: list[EvidenceRecord],
    ) -> dict:
        started_at = perf_counter()
        next_move = self.planner.plan(state=state, analysis=analysis)
        _record_metric(state, "next_move_planner_ms", started_at)
        return {
            "state": state,
            "answer": answer,
            "analysis": analysis,
            "evidence": evidence,
            "next_move": next_move,
        }


@component
class QuestionGeneratorNode:
    """Generate the next candidate-facing question from the next-move decision."""

    def __init__(self, service: AudioUnderstandingService | None = None) -> None:
        self.service = service or MockAudioUnderstandingService()

    @component.output_types(
        state=InterviewState,
        answer=CandidateAnswer,
        analysis=AnswerAnalysis,
        evidence=list[EvidenceRecord],
        next_move=NextMoveDecision,
        next_question=str,
    )
    def run(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        evidence: list[EvidenceRecord],
        next_move: NextMoveDecision,
    ) -> dict:
        started_at = perf_counter()
        if next_move.should_end_interview:
            question = next_move.interviewer_response
        else:
            question = fallback_question_from_move(
                state=state,
                analysis=analysis,
                next_move=next_move,
            )
            question = self._dedup_question(question, state, next_move)

        _record_metric(state, "question_generator_ms", started_at)
        return {
            "state": state,
            "answer": answer,
            "analysis": analysis,
            "evidence": evidence,
            "next_move": next_move,
            "next_question": question,
        }

    @component.output_types(
        state=InterviewState,
        answer=CandidateAnswer,
        analysis=AnswerAnalysis,
        evidence=list[EvidenceRecord],
        next_move=NextMoveDecision,
        next_question=str,
    )
    async def run_async(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        evidence: list[EvidenceRecord],
        next_move: NextMoveDecision,
    ) -> dict:
        started_at = perf_counter()
        if next_move.should_end_interview:
            question = next_move.interviewer_response
        else:
            question = await self.service.generate_question(
                state=state,
                answer=answer,
                analysis=analysis,
                next_move=next_move,
            )
            question = self._dedup_question(question, state, next_move)

        _record_metric(state, "question_generator_ms", started_at)
        return {
            "state": state,
            "answer": answer,
            "analysis": analysis,
            "evidence": evidence,
            "next_move": next_move,
            "next_question": question,
        }

    def _dedup_question(
        self,
        question: str,
        state: InterviewState,
        next_move: NextMoveDecision,
    ) -> str:
        """If the question was already asked recently, substitute an alternative."""
        recent_questions = {turn.question.strip().lower() for turn in state.turns[-4:]}
        if question.strip().lower() not in recent_questions:
            return question
        LOGGER.warning(
            "Duplicate question detected for interview=%s turn=%d; generating alternative.",
            state.interview_id,
            len(state.turns) + 1,
        )
        skill_label = next_move.target_skill_label
        if next_move.move_type == MoveType.REPAIR_AND_REDIRECT:
            return f"Let's try a different angle. Can you describe a specific situation where {skill_label} came up in your work?"
        if next_move.move_type == MoveType.SCAFFOLD_RETRY:
            return f"Even a small example would help. What is one thing you have done that involved {skill_label}?"
        if next_move.move_type == MoveType.SWITCH_ADJACENT_TOPIC:
            return f"Let's move on. Can you tell me about a time you worked with {skill_label}?"
        return f"Could you share a different example related to {skill_label}?"


@component
class TurnAggregatorNode:
    """Append the completed turn and return the updated interview state."""

    @component.output_types(
        state=InterviewState,
        turn=InterviewTurn,
        next_move=NextMoveDecision,
        next_question=str,
        evidence_created=list[EvidenceRecord],
    )
    def run(
        self,
        state: InterviewState,
        answer: CandidateAnswer,
        analysis: AnswerAnalysis,
        evidence: list[EvidenceRecord],
        next_move: NextMoveDecision,
        next_question: str,
    ) -> dict:
        started_at = perf_counter()
        turn_index = len(state.turns) + 1
        turn = InterviewTurn(
            turn_id=f"turn_{turn_index:03d}",
            interview_id=state.interview_id,
            turn_index=turn_index,
            question=state.last_question or state.next_question or "",
            candidate_answer=answer,
            answer_analysis=analysis,
            evidence=evidence,
            next_move=next_move,
            next_question=next_question,
            answered_at=datetime.now(timezone.utc),
        )
        state.turns.append(turn)
        state.last_question = next_question
        state.next_question = next_question
        state.last_next_move = next_move
        if next_move.move_type.value == "candidate_questions":
            state.closing_question_sent = True
        state.covered_topics = sorted(state.skill_map.covered_skill_ids)
        state.conversation_summary = _conversation_summary(state)
        state.open_threads = _open_threads(state)
        state.updated_at = datetime.now(timezone.utc)
        _record_metric(state, "turn_aggregator_ms", started_at)
        return {
            "state": state,
            "turn": turn,
            "next_move": next_move,
            "next_question": next_question,
            "evidence_created": evidence,
        }


def _conversation_summary(state: InterviewState) -> str:
    recent = state.turns[-6:]
    if not recent:
        return ""
    parts = []
    for turn in recent:
        if turn.answer_analysis is None:
            continue
        parts.append(
            f"Q{turn.turn_index}: {turn.answer_analysis.target_skill_label}; "
            f"intent={turn.answer_analysis.intent}; quality={turn.answer_analysis.quality}; "
            f"signal={turn.answer_analysis.summary[:180]}"
        )
    return " | ".join(parts)


def _open_threads(state: InterviewState) -> list[str]:
    threads = []
    for turn in state.turns[-8:]:
        analysis = turn.answer_analysis
        if analysis is None:
            continue
        if analysis.extracted_claim:
            threads.append(f"Validate claim: {analysis.extracted_claim[:140]}")
        if analysis.intent.value in {"refusal", "frustrated", "disengaged"}:
            threads.append(
                f"Candidate had difficulty with {analysis.target_skill_label}; avoid trapping them there."
            )
        if analysis.missing_expected_points:
            missing = ", ".join(analysis.missing_expected_points[:3])
            threads.append(f"Unresolved points for {analysis.target_skill_label}: {missing}")
    return list(dict.fromkeys(threads))[-8:]


def _record_metric(state: InterviewState, key: str, started_at: float) -> None:
    state.runtime_metrics[key] = int((perf_counter() - started_at) * 1000)
