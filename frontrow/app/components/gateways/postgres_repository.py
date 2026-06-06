from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models.interview import InterviewSession
from app.models.report import InterviewReport


class PostgresDurableInterviewRepository:
    """Postgres-backed durable repository for POC sessions and reports."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, future=True)

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    create table if not exists interview_sessions (
                        interview_id text primary key,
                        payload jsonb not null,
                        created_at timestamptz default now(),
                        updated_at timestamptz default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    create table if not exists interview_reports (
                        interview_id text primary key,
                        payload jsonb not null,
                        created_at timestamptz default now(),
                        updated_at timestamptz default now()
                    )
                    """
                )
            )

    async def save_session(self, session: InterviewSession) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    insert into interview_sessions (interview_id, payload, updated_at)
                    values (:interview_id, cast(:payload as jsonb), now())
                    on conflict (interview_id)
                    do update set payload = excluded.payload, updated_at = now()
                    """
                ),
                {
                    "interview_id": session.interview_id,
                    "payload": session.model_dump_json(),
                },
            )

    async def get_session(self, interview_id: str) -> InterviewSession:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text("select payload from interview_sessions where interview_id = :id"),
                {"id": interview_id},
            )
            row = result.first()
        if row is None:
            raise KeyError(interview_id)
        return InterviewSession.model_validate(row.payload)

    async def save_report(self, report: InterviewReport) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    insert into interview_reports (interview_id, payload, updated_at)
                    values (:interview_id, cast(:payload as jsonb), now())
                    on conflict (interview_id)
                    do update set payload = excluded.payload, updated_at = now()
                    """
                ),
                {
                    "interview_id": report.interview_id,
                    "payload": report.model_dump_json(),
                },
            )

    async def get_report(self, interview_id: str) -> InterviewReport:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text("select payload from interview_reports where interview_id = :id"),
                {"id": interview_id},
            )
            row = result.first()
        if row is None:
            raise KeyError(interview_id)
        return InterviewReport.model_validate(row.payload)

    async def close(self) -> None:
        await self.engine.dispose()


