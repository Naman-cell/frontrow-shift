from fastapi.testclient import TestClient

from app.main import app


class FakeLiveVoiceService:
    sample_rate = 24000
    mime_type = "audio/pcm;rate=24000"

    async def stream_text(self, text: str):
        assert text == "Welcome."
        yield b"chunk-one"
        yield b"chunk-two"


def test_live_voice_websocket_streams_pcm_chunks() -> None:
    with TestClient(app) as client:
        client.app.state.live_voice_service = FakeLiveVoiceService()
        with client.websocket_connect("/api/v1/voice/live") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"text": "Welcome."})
            assert websocket.receive_json()["type"] == "voice_start"
            assert websocket.receive_bytes() == b"chunk-one"
            assert websocket.receive_bytes() == b"chunk-two"
            assert websocket.receive_json()["type"] == "voice_end"
        client.app.state.live_voice_service = None
