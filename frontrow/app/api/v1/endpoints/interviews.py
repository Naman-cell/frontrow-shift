from fastapi import APIRouter, HTTPException

from app.core.dependencies import InterviewSessionManagerDep
from app.models.interview import InterviewSession, InterviewSessionCreate, ReportFromTranscriptRequest
from app.models.report import InterviewReport
from app.models.websocket import WebSocketInboundPayload, WebSocketOutboundPayload

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("/report-from-transcript", response_model=InterviewReport)
async def report_from_transcript(
    payload: ReportFromTranscriptRequest,
    manager: InterviewSessionManagerDep,
) -> InterviewReport:
    return await manager.generate_report_from_transcript(payload)


@router.post("", response_model=InterviewSession)
async def create_interview(
    payload: InterviewSessionCreate,
    manager: InterviewSessionManagerDep,
) -> InterviewSession:
    return await manager.create_interview(payload)


@router.post("/{interview_id}/start", response_model=WebSocketOutboundPayload)
async def start_interview(
    interview_id: str,
    manager: InterviewSessionManagerDep,
) -> WebSocketOutboundPayload:
    try:
        return await manager.start_interview(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc


@router.post("/{interview_id}/turn", response_model=WebSocketOutboundPayload)
async def process_turn(
    interview_id: str,
    payload: WebSocketInboundPayload,
    manager: InterviewSessionManagerDep,
) -> WebSocketOutboundPayload:
    try:
        return await manager.process_turn(interview_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc


@router.post("/{interview_id}/complete", response_model=InterviewReport)
async def complete_interview(
    interview_id: str,
    manager: InterviewSessionManagerDep,
) -> InterviewReport:
    try:
        return await manager.complete_interview(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc


@router.get("/{interview_id}/report", response_model=InterviewReport)
async def get_report(
    interview_id: str,
    manager: InterviewSessionManagerDep,
) -> InterviewReport:
    try:
        return await manager.get_report(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
