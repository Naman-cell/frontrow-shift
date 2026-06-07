import json
import logging
from asyncio import create_task
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.models.interview import (
    InterviewQuestionMode,
    InterviewSession,
    InterviewSessionCreate,
    InterviewStatus,
    ReportFromTranscriptRequest,
)
from app.models.report import InterviewReport
from app.models.state import InterviewState, ReconnectState
from app.models.turn import CandidateAnswer
from app.models.websocket import WebSocketInboundPayload, WebSocketOutboundPayload
from app.pipelines.initialization.pipeline import InterviewInitializationInput, InterviewInitializationPipeline
from app.pipelines.report_generation.pipeline import (
    ReportGenerationInput,
    ReportGenerationOutput,
    ReportGenerationPipeline,
)
from app.pipelines.turn_processing.pipeline import TurnProcessingInput, TurnProcessingPipeline
from app.services.audio_understanding_service import AudioUnderstandingService

LOGGER = logging.getLogger(__name__)


class InMemoryActiveSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, InterviewState] = {}
        self._reconnect: dict[str, ReconnectState] = {}

    async def save_state(self, state: InterviewState) -> None:
        self._sessions[state.interview_id] = state
        self._reconnect[state.interview_id] = state.reconnect_state()

    async def get_state(self, interview_id: str) -> InterviewState:
        return self._sessions[interview_id]

    async def get_reconnect_state(self, interview_id: str) -> ReconnectState | None:
        return self._reconnect.get(interview_id)

    async def delete_state(self, interview_id: str) -> None:
        self._sessions.pop(interview_id, None)
        self._reconnect.pop(interview_id, None)


class InMemoryDurableInterviewRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, InterviewSession] = {}
        self._reports: dict[str, InterviewReport] = {}

    async def save_session(self, session: InterviewSession) -> None:
        self._sessions[session.interview_id] = session

    async def get_session(self, interview_id: str) -> InterviewSession:
        return self._sessions[interview_id]

    async def save_report(self, report: InterviewReport) -> None:
        self._reports[report.interview_id] = report

    async def get_report(self, interview_id: str) -> InterviewReport:
        return self._reports[interview_id]


class InterviewSessionManager:
    def __init__(
        self,
        active_store: InMemoryActiveSessionStore | None = None,
        durable_repository: InMemoryDurableInterviewRepository | None = None,
        initialization_pipeline: InterviewInitializationPipeline | None = None,
        turn_processing_pipeline: TurnProcessingPipeline | None = None,
        report_generation_pipeline: ReportGenerationPipeline | None = None,
        audio_understanding_service: AudioUnderstandingService | None = None,
    ) -> None:
        self.active_store = active_store or InMemoryActiveSessionStore()
        self.durable_repository = durable_repository or InMemoryDurableInterviewRepository()
        self.initialization_pipeline = initialization_pipeline or InterviewInitializationPipeline()
        self.turn_processing_pipeline = turn_processing_pipeline or TurnProcessingPipeline(
            audio_understanding_service=audio_understanding_service,
        )
        self.report_generation_pipeline = report_generation_pipeline or ReportGenerationPipeline()
        self.redis_client = None

    async def create_interview(self, payload: InterviewSessionCreate) -> InterviewSession:
        session = InterviewSession(
            interview_id=f"int_{uuid4().hex[:12]}",
            tenant_id=payload.tenant_id,
            candidate_id=payload.candidate_id,
            role=payload.role,
            duration_minutes=payload.duration_minutes,
            question_mode=payload.question_mode,
            planned_questions=payload.planned_questions,
        )
        await self.durable_repository.save_session(session)
        initialized = await self.initialization_pipeline.run(InterviewInitializationInput(session=session))
        initialized.state.next_question = (
            await self.turn_processing_pipeline.audio_understanding_service.generate_opening_question(
                state=initialized.state,
            )
        )
        await self.active_store.save_state(initialized.state)
        return session

    async def start_interview(self, interview_id: str) -> WebSocketOutboundPayload:
        session = await self.durable_repository.get_session(interview_id)
        state = await self.active_store.get_state(interview_id)
        now = datetime.now(timezone.utc)
        session.status = InterviewStatus.ONGOING
        session.started_at = session.started_at or now
        state.status = InterviewStatus.ONGOING
        state.started_at = state.started_at or now
        self._refresh_time_remaining(state)
        state.last_question = state.next_question
        await self.durable_repository.save_session(session)
        await self.active_store.save_state(state)
        return self._outbound_for_state(state, completed=False)

    async def reconnect_snapshot(self, interview_id: str) -> ReconnectState | None:
        return await self.active_store.get_reconnect_state(interview_id)

    async def process_turn(
        self,
        interview_id: str,
        payload: WebSocketInboundPayload,
        *,
        audio_assembly_ms: int = 0,
    ) -> WebSocketOutboundPayload:
        request_started_at = perf_counter()
        if payload.user_leave or payload.overtime or payload.is_complete:
            report = await self.complete_interview(interview_id, incomplete=payload.user_leave)
            return WebSocketOutboundPayload(
                query_asked="",
                completed=True,
                interview_duration=0,
                meta={"report_id": report.interview_id},
            )

        state = await self.active_store.get_state(interview_id)
        self._refresh_time_remaining(state)
        started_at = perf_counter()
        output = await self.turn_processing_pipeline.run(
            TurnProcessingInput(
                state=state,
                answer=CandidateAnswer(
                    transcript=payload.text,
                    audio_ref=payload.audio_ref,
                    audio_base64=payload.audio_base64,
                    audio_mime_type=payload.audio_mime_type,
                ),
            )
        )
        pipeline_ms = int((perf_counter() - started_at) * 1000)
        self._strip_audio_payloads(output.state)
        if output.next_move.should_end_interview:
            finish_started_at = perf_counter()
            await self._mark_interview_finished(interview_id, state=output.state)
            finish_ms = int((perf_counter() - finish_started_at) * 1000)
            self._schedule_report_generation(interview_id)
            backend_total_ms = int((perf_counter() - request_started_at) * 1000)
            end_latency = self._latency_meta(
                output.state,
                turn_pipeline=pipeline_ms,
                backend_total=backend_total_ms,
                state_save=finish_ms,
                audio_assembly=audio_assembly_ms,
                report_generation="deferred",
            )
            self._emit_turn_latency_log(
                interview_id=interview_id,
                turn_index=len(output.state.turns),
                latency=end_latency,
            )
            return WebSocketOutboundPayload(
                query_asked=output.next_move.interviewer_response
                or "Understood, we can stop here. Thank you for your time.",
                completed=True,
                interview_duration=output.state.time_remaining_seconds,
                meta={
                    "report_id": interview_id,
                    "pipeline": "haystack.turn_processing",
                    "turn_index": len(output.state.turns),
                    "candidate_intent": output.turn.answer_analysis.intent,
                    "answer_quality": output.turn.answer_analysis.quality,
                    "candidate_transcript": output.turn.candidate_answer.transcript,
                    "candidate_answer_summary": output.turn.answer_analysis.summary,
                    "move_type": output.next_move.move_type,
                    "target_skill": output.next_move.target_skill_id,
                    "reason": output.next_move.reason,
                    "interviewer_response": output.next_move.interviewer_response,
                    "ended_by_policy": True,
                    "latency_ms": end_latency,
                },
            )
        completed = await self._apply_question_mode(output.state)
        if completed:
            finish_started_at = perf_counter()
            await self._mark_interview_finished(interview_id, state=output.state)
            finish_ms = int((perf_counter() - finish_started_at) * 1000)
            self._schedule_report_generation(interview_id)
            backend_total_ms = int((perf_counter() - request_started_at) * 1000)
            plan_latency = self._latency_meta(
                output.state,
                turn_pipeline=pipeline_ms,
                backend_total=backend_total_ms,
                state_save=finish_ms,
                audio_assembly=audio_assembly_ms,
                report_generation="deferred",
            )
            self._emit_turn_latency_log(
                interview_id=interview_id,
                turn_index=len(output.state.turns),
                latency=plan_latency,
            )
            return WebSocketOutboundPayload(
                query_asked="",
                completed=True,
                interview_duration=output.state.time_remaining_seconds,
                meta={
                    "report_id": interview_id,
                    "reason": "manual_plan_exhausted",
                    "latency_ms": plan_latency,
                },
            )
        save_started_at = perf_counter()
        await self.active_store.save_state(output.state)
        save_ms = int((perf_counter() - save_started_at) * 1000)
        backend_total_ms = int((perf_counter() - request_started_at) * 1000)
        outbound = self._outbound_for_state(output.state, completed=False)
        latency = self._latency_meta(
            output.state,
            turn_pipeline=pipeline_ms,
            backend_total=backend_total_ms,
            state_save=save_ms,
            audio_assembly=audio_assembly_ms,
        )
        outbound.meta["latency_ms"] = latency
        self._emit_turn_latency_log(
            interview_id=interview_id,
            turn_index=len(output.state.turns),
            latency=latency,
        )
        return outbound

    async def complete_interview(self, interview_id: str, *, incomplete: bool = False) -> InterviewReport:
        await self._mark_interview_finished(interview_id, incomplete=incomplete)
        session = await self.durable_repository.get_session(interview_id)
        state = await self.active_store.get_state(interview_id)
        self._strip_audio_payloads(state)
        report_output = await self.launch_report_chain(state)
        await self.durable_repository.save_session(session)
        await self.durable_repository.save_report(report_output.report)
        await self.active_store.save_state(state)
        return report_output.report

    async def get_report(self, interview_id: str) -> InterviewReport:
        return await self.durable_repository.get_report(interview_id)

    async def generate_report_from_transcript(
        self, request: ReportFromTranscriptRequest,
    ) -> InterviewReport:
        """Build an InterviewState from a Q&A transcript and generate a report."""
        session = InterviewSession(
            interview_id=f"int_transcript_{uuid4().hex[:8]}",
            tenant_id="transcript_upload",
            candidate_id="transcript_upload",
            role=request.role,
            duration_minutes=request.duration_minutes,
        )
        initialized = await self.initialization_pipeline.run(
            InterviewInitializationInput(session=session),
        )
        state = initialized.state
        state.status = InterviewStatus.ONGOING
        state.started_at = datetime.now(timezone.utc)
        state.time_remaining_seconds = request.duration_minutes * 60

        for turn in request.turns:
            state.last_question = turn.question
            state.next_question = turn.question
            output = await self.turn_processing_pipeline.run(
                TurnProcessingInput(
                    state=state,
                    answer=CandidateAnswer(transcript=turn.answer),
                )
            )
            state = output.state
            if output.next_move.should_end_interview:
                break

        state.status = InterviewStatus.COMPLETED
        state.updated_at = datetime.now(timezone.utc)
        report_output = await self.launch_report_chain(state)
        return report_output.report

    async def launch_report_chain(self, state: InterviewState) -> ReportGenerationOutput:
        return await self.report_generation_pipeline.run(ReportGenerationInput(state=state))

    async def _mark_interview_finished(
        self,
        interview_id: str,
        *,
        incomplete: bool = False,
        state: InterviewState | None = None,
    ) -> None:
        session = await self.durable_repository.get_session(interview_id)
        state = state or await self.active_store.get_state(interview_id)
        completed_at = datetime.now(timezone.utc)
        session.status = InterviewStatus.INCOMPLETE if incomplete else InterviewStatus.COMPLETED
        session.completed_at = session.completed_at or completed_at
        state.status = session.status
        state.updated_at = completed_at
        self._strip_audio_payloads(state)
        await self.durable_repository.save_session(session)
        await self.active_store.save_state(state)

    def _schedule_report_generation(self, interview_id: str) -> None:
        async def generate() -> None:
            try:
                state = await self.active_store.get_state(interview_id)
                self._strip_audio_payloads(state)
                report_output = await self.launch_report_chain(state)
                await self.durable_repository.save_report(report_output.report)
            except Exception:
                LOGGER.exception("Deferred report generation failed for interview %s", interview_id)

        create_task(generate())

    def _strip_audio_payloads(self, state: InterviewState) -> None:
        for turn in state.turns:
            answer = turn.candidate_answer
            if answer is None or not answer.audio_base64:
                continue
            approx_bytes = int(len(answer.audio_base64) * 0.75)
            answer.audio_ref = answer.audio_ref or (
                f"inline_audio:{approx_bytes}_bytes:{answer.audio_mime_type or 'audio'}"
            )
            answer.audio_base64 = None

    async def _apply_question_mode(self, state: InterviewState) -> bool:
        if state.question_mode not in {InterviewQuestionMode.HYBRID, InterviewQuestionMode.MANUAL}:
            return False
        next_plan_position = state.plan_position + 1
        if next_plan_position < len(state.planned_questions):
            state.plan_position = next_plan_position
            state.next_question = state.planned_questions[next_plan_position]
            state.last_question = state.next_question
            return False
        if state.question_mode == InterviewQuestionMode.MANUAL:
            return True
        return False

    def _outbound_for_state(self, state: InterviewState, *, completed: bool) -> WebSocketOutboundPayload:
        next_move = state.last_next_move
        question = state.next_question or ""
        return WebSocketOutboundPayload(
            query_asked=question,
            completed=completed,
            interview_duration=state.time_remaining_seconds,
            reconnect=state.reconnect_state().model_dump(),
            meta=self._meta_for_state(state, next_move),
        )

    async def get_state(self, interview_id: str) -> InterviewState:
        return await self.active_store.get_state(interview_id)

    def _meta_for_state(self, state: InterviewState, next_move) -> dict:
        return {
            "pipeline": "haystack.turn_processing",
            "execution_steps": [
                "target_skill_selector",
                "answer_understanding",
                "evidence_extractor",
                "skill_state_updater",
                "next_move_planner",
                "question_generator",
                "turn_aggregator",
            ],
            "question_mode": state.question_mode,
            "turn_index": len(state.turns),
            "candidate_intent": state.turns[-1].answer_analysis.intent if state.turns else None,
            "answer_quality": state.turns[-1].answer_analysis.quality if state.turns else None,
            "candidate_transcript": (
                state.turns[-1].candidate_answer.transcript
                if state.turns and state.turns[-1].candidate_answer
                else None
            ),
            "candidate_answer_summary": (
                state.turns[-1].answer_analysis.summary
                if state.turns and state.turns[-1].answer_analysis
                else None
            ),
            "move_type": next_move.move_type if next_move else None,
            "target_skill": next_move.target_skill_id if next_move else None,
            "reason": next_move.reason if next_move else None,
            "interviewer_response": next_move.interviewer_response if next_move else None,
            "time_remaining_seconds": state.time_remaining_seconds,
        }

    def _latency_meta(
        self,
        state: InterviewState,
        *,
        turn_pipeline: int,
        backend_total: int,
        state_save: int,
        audio_assembly: int = 0,
        report_generation: str | None = None,
    ) -> dict:
        meta = {
            "backend_total": backend_total,
            "turn_pipeline": turn_pipeline,
            "state_save": state_save,
            "audio_assembly": audio_assembly,
            **state.runtime_metrics,
        }
        if report_generation is not None:
            meta["report_generation"] = report_generation
        return meta

    def _emit_turn_latency_log(
        self,
        *,
        interview_id: str,
        turn_index: int,
        latency: dict,
    ) -> None:
        """Emit a single structured log line with per-segment ms durations."""
        LOGGER.info(
            "turn_latency %s",
            json.dumps(
                {
                    "event": "turn_latency",
                    "interview_id": interview_id,
                    "turn_index": turn_index,
                    "backend_total_ms": latency.get("backend_total", 0),
                    "turn_pipeline_ms": latency.get("turn_pipeline", 0),
                    "answer_understanding_ms": latency.get("answer_understanding_ms", 0),
                    "gemini_analyze_ms": latency.get("gemini_analyze_ms", 0),
                    "question_generator_ms": latency.get("question_generator_ms", 0),
                    "evidence_extractor_ms": latency.get("evidence_extractor_ms", 0),
                    "skill_state_updater_ms": latency.get("skill_state_updater_ms", 0),
                    "next_move_planner_ms": latency.get("next_move_planner_ms", 0),
                    "target_skill_selector_ms": latency.get("target_skill_selector_ms", 0),
                    "turn_aggregator_ms": latency.get("turn_aggregator_ms", 0),
                    "state_save_ms": latency.get("state_save", 0),
                    "audio_assembly_ms": latency.get("audio_assembly", 0),
                },
                separators=(",", ":"),
            ),
        )

    def _refresh_time_remaining(self, state: InterviewState) -> None:
        if state.started_at is None:
            state.time_remaining_seconds = state.duration_minutes * 60
            return
        now = datetime.now(timezone.utc)
        started_at = state.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = int((now - started_at).total_seconds())
        state.time_remaining_seconds = max(0, (state.duration_minutes * 60) - elapsed)
