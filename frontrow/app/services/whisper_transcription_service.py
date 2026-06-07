import base64
import logging
import os
import tempfile
from time import perf_counter

LOGGER = logging.getLogger(__name__)


class TranscriptionService:
    """Base class for audio transcription."""

    async def transcribe(self, audio_base64: str, mime_type: str = "audio/webm") -> str:
        raise NotImplementedError


class WhisperTranscriptionService(TranscriptionService):
    """Azure AI Foundry Whisper-based transcription (fast, 1-2s)."""

    def __init__(
        self,
        *,
        api_key: str,
        azure_endpoint: str,
        model: str = "whisper",
        api_version: str = "2024-06-01",
    ) -> None:
        from openai import AsyncAzureOpenAI

        self.client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )
        self.model = model

    async def transcribe(self, audio_base64: str, mime_type: str = "audio/webm") -> str:
        audio_bytes = base64.b64decode(audio_base64)
        ext = _mime_to_ext(mime_type)
        started = perf_counter()
        fd, path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio_bytes)
            with open(path, "rb") as f:
                response = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=f,
                    response_format="text",
                )
        finally:
            os.unlink(path)
        ms = int((perf_counter() - started) * 1000)
        LOGGER.info("whisper_transcribe_ms=%d audio_bytes=%d", ms, len(audio_bytes))
        return response.strip()


def _mime_to_ext(mime_type: str) -> str:
    # Strip codec parameters: "audio/webm;codecs=opus" → "audio/webm"
    base_type = mime_type.split(";")[0].strip()
    mapping = {
        "audio/webm": ".webm",
        "audio/wav": ".wav",
        "audio/mp3": ".mp3",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
        "audio/mp4": ".mp4",
        "audio/m4a": ".m4a",
    }
    ext = mapping.get(base_type)
    if ext is None:
        LOGGER.warning("Unknown MIME type %r, falling back to .webm", mime_type)
        return ".webm"
    return ext
