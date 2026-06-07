import json
from asyncio import CancelledError, Task, create_task
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.services.azure_speech_voice_service import AzureSpeechVoiceError, AzureSpeechVoiceService

router = APIRouter(prefix="/voice", tags=["voice"])


@router.websocket("/live")
async def live_voice(websocket: WebSocket) -> None:
    await websocket.accept()
    service = getattr(websocket.app.state, "live_voice_service", None)
    if service is None:
        settings = get_settings()
        service = AzureSpeechVoiceService(
            speech_key=settings.azure_speech_key,
            region=settings.azure_speech_region,
            voice_name=settings.azure_tts_voice,
            output_format=settings.azure_tts_output_format,
        )
        websocket.app.state.live_voice_service = service

    current_stream: Task | None = None

    async def stream_to_client(text: str) -> None:
        try:
            await websocket.send_json(
                {
                    "type": "voice_start",
                    "sample_rate": service.sample_rate,
                    "mime_type": service.mime_type,
                }
            )
            async for audio_chunk in service.stream_text(text):
                await websocket.send_bytes(audio_chunk)
            await websocket.send_json({"type": "voice_end"})
        except CancelledError:
            raise
        except AzureSpeechVoiceError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})

    try:
        await websocket.send_json(
            {
                "type": "ready",
                "provider": "azure_speech",
                "sample_rate": service.sample_rate,
                "mime_type": service.mime_type,
            }
        )
        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid voice payload JSON."})
                continue

            text = str(payload.get("text") or "").strip()
            if not text:
                continue

            if current_stream is not None and not current_stream.done():
                current_stream.cancel()
                with suppress(CancelledError):
                    await current_stream
            current_stream = create_task(stream_to_client(text))
    except WebSocketDisconnect:
        if current_stream is not None and not current_stream.done():
            current_stream.cancel()
        return
    except AzureSpeechVoiceError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
