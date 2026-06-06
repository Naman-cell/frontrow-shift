from typing import Annotated

from fastapi import Depends, Request

from app.managers.interview_session_manager import InterviewSessionManager


def get_interview_session_manager(request: Request) -> InterviewSessionManager:
    if not hasattr(request.app.state, "interview_session_manager"):
        request.app.state.interview_session_manager = InterviewSessionManager()
    return request.app.state.interview_session_manager


InterviewSessionManagerDep = Annotated[
    InterviewSessionManager,
    Depends(get_interview_session_manager),
]
