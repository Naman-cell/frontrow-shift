from __future__ import annotations

from app.models.state import InterviewState, ReconnectState


class RedisActiveSessionStore:
    """Redis-backed active interview state store.

    This mirrors the AI-Brew split between a full `:session` payload and a
    lighter `:state` reconnect snapshot, while storing Pydantic JSON for the
    POC.
    """

    def __init__(self, redis_client, *, ttl_seconds: int = 7200) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def _session_key(self, interview_id: str) -> str:
        return f"frontrow:{interview_id}:session"

    def _state_key(self, interview_id: str) -> str:
        return f"frontrow:{interview_id}:state"

    async def save_state(self, state: InterviewState) -> None:
        await self.redis.set(
            self._session_key(state.interview_id),
            state.model_dump_json(),
            ex=self.ttl_seconds,
        )
        await self.redis.set(
            self._state_key(state.interview_id),
            state.reconnect_state().model_dump_json(),
            ex=self.ttl_seconds,
        )

    async def get_state(self, interview_id: str) -> InterviewState:
        raw = await self.redis.get(self._session_key(interview_id))
        if raw is None:
            raise KeyError(interview_id)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return InterviewState.model_validate_json(raw)

    async def get_reconnect_state(self, interview_id: str) -> ReconnectState | None:
        raw = await self.redis.get(self._state_key(interview_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ReconnectState.model_validate_json(raw)

    async def delete_state(self, interview_id: str) -> None:
        await self.redis.delete(
            self._session_key(interview_id),
            self._state_key(interview_id),
        )


