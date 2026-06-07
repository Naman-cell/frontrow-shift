---
name: project-overview
description: Frontrow-shift project: FastAPI interview AI with Haystack pipeline, Pydantic v2, uv toolchain, ruff linter
metadata:
  type: project
---

FastAPI backend at `/Users/naxter./Projects/frontrow-shift/frontrow/`. Key dirs: `app/models/`, `app/pipelines/`, `app/services/`, `app/managers/`, `app/runtime/`, `tests/`.

Dual-path transcription architecture: `WhisperTranscriptionService` (app/services/whisper_transcription_service.py) handles fast transcription (1-2s) on the hot path. Background Gemini analysis is scheduled via `_schedule_background_analysis` in InterviewSessionManager (fire-and-forget asyncio.create_task). Factory wiring in app/runtime/factory.py. Config flags: ENABLE_FAST_TRANSCRIPTION + OPENAI_API_KEY gate Whisper; ENABLE_GEMINI + GEMINI_API_KEY gate Gemini.

Toolchain: `uv` for deps and running (`uv run python -m pytest`, `uv run ruff check .`). 36 tests pass in ~1.3s. Ruff enforces style.

Core data flow: `InterviewState` (state.py) -> turn processing pipeline -> report generation pipeline (Haystack component nodes in components.py) -> `InterviewReport` (report.py).

Skill scoring: 1-4 scale. `skill_score_4()` maps raw score + confidence -> [1,4]. `required_level_for_seniority()` returns target: senior=3.25, junior=2.0, mid=2.75.

**Why:** Reference for future reviews to understand architecture quickly.
**How to apply:** Use when reviewing model changes, pipeline additions, or scoring logic.
