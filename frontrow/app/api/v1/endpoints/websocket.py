import base64

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.dependencies import get_interview_session_manager
from app.models.websocket import WebSocketInboundPayload

router = APIRouter(tags=["websocket"])


@router.websocket("/interviews/{interview_id}/ws")
async def interview_websocket(websocket: WebSocket, interview_id: str) -> None:
    await websocket.accept()
    manager = get_interview_session_manager(websocket)
    audio_streams: dict[str, list[bytes]] = {}

    snapshot = await manager.reconnect_snapshot(interview_id)
    if snapshot is not None and snapshot.current_question:
        state = await manager.get_state(interview_id)
        initial_payload = manager._outbound_for_state(state, completed=False)
        await websocket.send_json(initial_payload.model_dump(mode="json"))

    try:
        while True:
            raw_payload = await websocket.receive_json()
            try:
                payload = WebSocketInboundPayload.model_validate(raw_payload)
            except ValidationError as exc:
                await websocket.send_json({"error": "invalid_payload", "details": exc.errors()})
                continue

            if payload.message_type == "audio_chunk":
                if payload.audio_stream_id and payload.audio_chunk_base64:
                    audio_streams.setdefault(payload.audio_stream_id, []).append(
                        base64.b64decode(payload.audio_chunk_base64)
                    )
                continue

            if payload.audio_stream_id and not payload.audio_base64:
                chunks = audio_streams.pop(payload.audio_stream_id, [])
                if chunks:
                    payload.audio_base64 = base64.b64encode(b"".join(chunks)).decode("ascii")

            outbound = await manager.process_turn(interview_id, payload)
            await websocket.send_json(outbound.model_dump(mode="json"))
            if outbound.completed:
                await websocket.close()
                return
    except WebSocketDisconnect:
        return
