from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import health, interviews, voice, websocket
from app.core.config import get_settings
from app.managers.interview_session_manager import InterviewSessionManager
from app.pipelines.registry import clear_pipeline_registry, register_default_pipelines
from app.runtime.factory import (
    build_interview_session_manager,
    close_interview_session_manager,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    clear_pipeline_registry()
    register_default_pipelines()
    try:
        app.state.interview_session_manager = await build_interview_session_manager(settings)
    except Exception:
        # Keep local development resilient: if Docker infra is not up yet, the
        # app still starts with in-memory stores and mock model behavior.
        app.state.interview_session_manager = InterviewSessionManager()
    try:
        yield
    finally:
        live_voice_service = getattr(app.state, "live_voice_service", None)
        if live_voice_service is not None and hasattr(live_voice_service, "close"):
            await live_voice_service.close()
        await close_interview_session_manager(app.state.interview_session_manager)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(interviews.router, prefix=settings.api_v1_prefix)
    app.include_router(websocket.router, prefix=settings.api_v1_prefix)
    app.include_router(voice.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
