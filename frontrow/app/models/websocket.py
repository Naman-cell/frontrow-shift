from pydantic import BaseModel, Field


class WebSocketInboundPayload(BaseModel):
    message_type: str = "answer"
    text: str = ""
    audio_ref: str | None = None
    audio_stream_id: str | None = None
    audio_chunk_base64: str | None = None
    audio_chunk_final: bool = False
    audio_base64: str | None = None
    audio_mime_type: str | None = None
    user_leave: bool = False
    overtime: bool = False
    is_complete: bool = False


class WebSocketOutboundPayload(BaseModel):
    message_type: str = "question"
    query_asked: str
    completed: bool = False
    interview_duration: int
    audio_base64: str | None = None
    audio_mime_type: str | None = None
    reconnect: dict | None = None
    meta: dict = Field(default_factory=dict)
