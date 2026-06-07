from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import InterviewSessionManagerDep
from app.models.report import InterviewReport
from app.models.state import InterviewState

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineReportRequest(BaseModel):
    interview_id: str | None = None
    state: InterviewState | None = None


@router.post("/report", response_model=InterviewReport)
async def pipeline_report(
    payload: PipelineReportRequest,
    manager: InterviewSessionManagerDep,
) -> InterviewReport:
    """Run the report generation pipeline directly on an interview state."""
    state: InterviewState | None = None
    if payload.interview_id:
        try:
            state = await manager.get_state(payload.interview_id)
        except (KeyError, Exception) as exc:
            raise HTTPException(status_code=404, detail="Interview not found") from exc
    elif payload.state:
        state = payload.state
    if state is None:
        raise HTTPException(status_code=400, detail="Provide interview_id or state")
    output = await manager.launch_report_chain(state)
    return output.report
