import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.dependencies import get_interview_session_manager
from app.models.websocket import WebSocketInboundPayload

router = APIRouter(tags=["websocket"])


@router.websocket("/interviews/{interview_id}/ws")
async def interview_websocket(websocket: WebSocket, interview_id: str) -> None:
    await websocket.accept()
    manager = get_interview_session_manager(websocket)

    snapshot = await manager.reconnect_snapshot(interview_id)
    if snapshot is not None and snapshot.current_question:
        state = await manager.get_state(interview_id)
        initial_payload = manager._outbound_for_state(state, completed=False)
        await websocket.send_json(initial_payload.model_dump(mode="json"))
        asyncio.create_task(_send_audio_payload(websocket, manager, snapshot.current_question, state))

    try:
        while True:
            raw_payload = await websocket.receive_json()
            try:
                payload = WebSocketInboundPayload.model_validate(raw_payload)
            except ValidationError as exc:
                await websocket.send_json({"error": "invalid_payload", "details": exc.errors()})
                continue

            outbound = await manager.process_turn(interview_id, payload)
            await websocket.send_json(outbound.model_dump(mode="json"))
            if outbound.query_asked and not outbound.completed:
                state = await manager.get_state(interview_id)
                asyncio.create_task(_send_audio_payload(websocket, manager, outbound.query_asked, state))
            if outbound.completed:
                if outbound.query_asked:
                    try:
                        state = await manager.get_state(interview_id)
                    except KeyError:
                        state = None
                    await _send_audio_payload(websocket, manager, outbound.query_asked, state)
                await websocket.close()
                return
    except WebSocketDisconnect:
        return


async def _send_audio_payload(websocket: WebSocket, manager, question: str, state) -> None:
    payload = await manager.audio_payload_for_question(question, state=state)
    if not payload.audio_base64 and not payload.meta.get("tts_error"):
        return
    try:
        await websocket.send_json(payload.model_dump(mode="json"))
    except RuntimeError:
        return
