from __future__ import annotations

from redis.asyncio import from_url as redis_from_url

from app.components.gateways.postgres_repository import (
    PostgresDurableInterviewRepository,
)
from app.components.gateways.redis_session import RedisActiveSessionStore
from app.core.config import Settings
from app.managers.interview_session_manager import (
    InMemoryActiveSessionStore,
    InMemoryDurableInterviewRepository,
    InterviewSessionManager,
)
from app.pipelines.report_generation.pipeline import ReportGenerationPipeline
from app.pipelines.turn_processing.pipeline import TurnProcessingPipeline
from app.services.audio_understanding_service import (
    GeminiAudioUnderstandingService,
    MockAudioUnderstandingService,
)
from app.services.report_scoring_service import (
    GeminiReportScoringService,
    HeuristicReportScoringService,
)
from app.services.whisper_transcription_service import WhisperTranscriptionService


async def build_interview_session_manager(settings: Settings) -> InterviewSessionManager:
    """Build the session manager with configured real or in-memory adapters."""
    active_store = InMemoryActiveSessionStore()
    redis_client = None
    if settings.active_state_backend.lower() == "redis":
        redis_client = redis_from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        active_store = RedisActiveSessionStore(redis_client)

    durable_repository = InMemoryDurableInterviewRepository()
    if settings.persistence_backend.lower() == "postgres":
        postgres_repository = PostgresDurableInterviewRepository(settings.database_url)
        await postgres_repository.init_schema()
        durable_repository = postgres_repository

    audio_service = MockAudioUnderstandingService()
    if settings.enable_gemini and settings.gemini_api_key:
        audio_service = GeminiAudioUnderstandingService(
            api_key=settings.gemini_api_key,
            audio_model=settings.gemini_audio_model,
        )

    report_scoring_service = HeuristicReportScoringService()
    if settings.enable_gemini and settings.gemini_api_key:
        report_scoring_service = GeminiReportScoringService(
            api_key=settings.gemini_api_key,
            model=settings.gemini_audio_model,
        )

    transcription_service = None
    whisper_ready = (
        settings.enable_fast_transcription
        and settings.azure_whisper_key
        and settings.azure_whisper_endpoint
    )
    if whisper_ready:
        transcription_service = WhisperTranscriptionService(
            api_key=settings.azure_whisper_key,
            azure_endpoint=settings.azure_whisper_endpoint,
            model=settings.whisper_model,
            api_version=settings.azure_whisper_api_version,
        )

    fast_turn_pipeline = None
    if transcription_service is not None:
        fast_turn_pipeline = TurnProcessingPipeline(
            audio_understanding_service=MockAudioUnderstandingService(),
            question_generation_service=audio_service,
        )

    manager = InterviewSessionManager(
        active_store=active_store,
        durable_repository=durable_repository,
        audio_understanding_service=audio_service,
        transcription_service=transcription_service,
        fast_turn_processing_pipeline=fast_turn_pipeline,
        report_generation_pipeline=ReportGenerationPipeline(
            report_scoring_service=report_scoring_service,
        ),
    )
    manager.redis_client = redis_client
    return manager


async def close_interview_session_manager(manager: InterviewSessionManager) -> None:
    repository = getattr(manager, "durable_repository", None)
    if hasattr(repository, "close"):
        await repository.close()
    redis_client = getattr(manager, "redis_client", None)
    if redis_client is not None:
        await redis_client.aclose()
