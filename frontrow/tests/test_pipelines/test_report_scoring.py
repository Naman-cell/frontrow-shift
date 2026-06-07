from app.models.interview import RoleContext
from app.models.state import InterviewState
from app.models.turn import AnswerAnalysis, AnswerQuality, CandidateAnswer, CandidateIntent, InterviewTurn
from app.pipelines.report_generation.heuristics import answer_depth_score as _answer_depth_score, ownership_score as _ownership_score


def test_refusal_and_interview_criticism_do_not_inflate_depth_or_ownership() -> None:
    assert _answer_depth_score(
        "",
        "The candidate criticizes the interview question and does not answer.",
        AnswerQuality.REFUSAL,
    ) == 1.0

    state = InterviewState(
        interview_id="int_report_scoring",
        role=RoleContext(title="Retail Sales Associate"),
        turns=[
            InterviewTurn(
                turn_id="turn_001",
                interview_id="int_report_scoring",
                turn_index=1,
                question="Tell me about customer discovery.",
                candidate_answer=CandidateAnswer(
                    transcript="This feels templated and not human. I do not know."
                ),
                answer_analysis=AnswerAnalysis(
                    quality=AnswerQuality.REFUSAL,
                    intent=CandidateIntent.REFUSAL,
                    summary="The candidate criticizes the interview and does not answer.",
                    target_skill_id="customer_discovery",
                    target_skill_label="Customer discovery",
                ),
            )
        ],
    )

    assert _ownership_score(state) == 1.0
