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
from app.services.audio_understanding_service import (
    GeminiAudioUnderstandingService,
    MockAudioUnderstandingService,
)


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
            tts_model=settings.gemini_tts_model,
            tts_voice=settings.gemini_tts_voice,
            enable_tts=settings.enable_tts,
        )

    manager = InterviewSessionManager(
        active_store=active_store,
        durable_repository=durable_repository,
        audio_understanding_service=audio_service,
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
