from app.models.interview import RoleContext
from app.models.next_move import MoveType
from app.models.skill_map import SkillMap, SkillNode
from app.models.state import InterviewState
from app.models.turn import AnswerAnalysis, AnswerQuality, CandidateIntent, InterviewTurn
from app.pipelines.turn_processing.processors.next_move_planning import NextMovePlanner


def make_state(*, time_remaining_seconds: int = 900, duration_minutes: int = 30) -> InterviewState:
    return InterviewState(
        interview_id="int_test",
        role=RoleContext(
            title="Backend Engineer",
            required_skills=["Python concurrency", "API design", "System design"],
        ),
        duration_minutes=duration_minutes,
        time_remaining_seconds=time_remaining_seconds,
        skill_map=SkillMap(
            skills={
                "python_concurrency": SkillNode(
                    skill_id="python_concurrency",
                    label="Python concurrency",
                    importance=0.9,
                    target_depth="medium",
                ),
                "api_design": SkillNode(
                    skill_id="api_design",
                    label="API design",
                    importance=0.8,
                    target_depth="medium",
                ),
                "system_design": SkillNode(
                    skill_id="system_design",
                    label="System design",
                    importance=0.7,
                    target_depth="medium",
                ),
            }
        ),
    )


def make_analysis(
    quality: AnswerQuality,
    *,
    skill_id: str = "python_concurrency",
    intent: CandidateIntent = CandidateIntent.ANSWERED,
) -> AnswerAnalysis:
    label = skill_id.replace("_", " ").title()
    return AnswerAnalysis(
        quality=quality,
        summary=f"{quality.value} answer",
        target_skill_id=skill_id,
        target_skill_label=label,
        confidence=0.82,
        intent=intent,
    )


def test_strong_answer_triggers_drill_down() -> None:
    planner = NextMovePlanner()
    state = make_state()
    state.skill_map.skills["python_concurrency"].attempts = 1

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.STRONG))

    assert decision.move_type == MoveType.DRILL_DOWN
    assert decision.target_skill_id == "python_concurrency"


def test_partial_answer_triggers_scaffold_retry_for_important_skill() -> None:
    planner = NextMovePlanner()
    state = make_state()

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.PARTIAL))

    assert decision.move_type == MoveType.SCAFFOLD_RETRY
    assert decision.target_skill_id == "python_concurrency"


def test_first_explicit_do_not_know_gets_scaffold_retry_for_important_skill() -> None:
    planner = NextMovePlanner()
    state = make_state()

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.REFUSAL))

    assert decision.move_type == MoveType.SCAFFOLD_RETRY
    assert decision.target_skill_id == "python_concurrency"


def test_repeated_do_not_know_moves_to_adjacent_topic() -> None:
    planner = NextMovePlanner()
    state = make_state()
    state.skill_map.skills["python_concurrency"].attempts = 2

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.REFUSAL))

    assert decision.move_type == MoveType.SWITCH_ADJACENT_TOPIC
    assert decision.target_skill_id == "api_design"


def test_vague_resume_claim_triggers_validation() -> None:
    planner = NextMovePlanner()
    state = make_state()
    analysis = make_analysis(AnswerQuality.UNSUPPORTED_CLAIM)
    analysis.resume_claim_detected = True
    analysis.extracted_claim = "I led the platform migration."

    decision = planner.plan(state=state, analysis=analysis)

    assert decision.move_type == MoveType.VALIDATE_RESUME_CLAIM
    assert decision.target_skill_id == "python_concurrency"


def test_low_time_remaining_starts_candidate_question_closing_phase() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=90)

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.STRONG))

    assert decision.move_type == MoveType.CANDIDATE_QUESTIONS
    assert decision.time_consideration == "closing buffer reached"


def test_two_minute_interview_does_not_close_too_early() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=90, duration_minutes=2)
    state.skill_map.skills["python_concurrency"].attempts = 1

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.STRONG))

    assert decision.move_type == MoveType.DRILL_DOWN


def test_two_minute_interview_enters_candidate_questions_near_end() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=44, duration_minutes=2)

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.STRONG))

    assert decision.move_type == MoveType.CANDIDATE_QUESTIONS


def test_two_minute_interview_wraps_when_time_is_exhausted() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=10, duration_minutes=2)

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.STRONG))

    assert decision.move_type == MoveType.WRAP_UP
    assert decision.should_end_interview is True


def test_five_minute_interview_asks_candidate_questions_at_28_seconds() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=28, duration_minutes=5)

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.REFUSAL))

    assert decision.move_type == MoveType.CANDIDATE_QUESTIONS
    assert decision.should_end_interview is False


def test_low_signal_near_end_still_gives_candidate_questions() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=44, duration_minutes=2)
    state.turns.extend(
        [
            InterviewTurn(
                turn_id="turn_001",
                interview_id=state.interview_id,
                turn_index=1,
                question="Previous question",
                answer_analysis=make_analysis(AnswerQuality.REFUSAL),
                next_move=planner.plan(state=state, analysis=make_analysis(AnswerQuality.REFUSAL)),
            ),
            InterviewTurn(
                turn_id="turn_002",
                interview_id=state.interview_id,
                turn_index=2,
                question="Previous question",
                answer_analysis=make_analysis(AnswerQuality.REFUSAL),
                next_move=planner.plan(state=state, analysis=make_analysis(AnswerQuality.REFUSAL)),
            ),
        ]
    )

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.REFUSAL, skill_id="fastapi"))

    assert decision.move_type == MoveType.CANDIDATE_QUESTIONS
    assert decision.should_end_interview is False


def test_low_signal_with_time_left_steps_back_to_role_fit_instead_of_ending() -> None:
    planner = NextMovePlanner()
    state = make_state(time_remaining_seconds=179, duration_minutes=5)
    state.turns.extend(
        [
            InterviewTurn(
                turn_id="turn_001",
                interview_id=state.interview_id,
                turn_index=1,
                question="Previous question",
                answer_analysis=make_analysis(AnswerQuality.REFUSAL, intent=CandidateIntent.REFUSAL),
                next_move=planner.plan(
                    state=state,
                    analysis=make_analysis(AnswerQuality.REFUSAL, intent=CandidateIntent.REFUSAL),
                ),
            ),
            InterviewTurn(
                turn_id="turn_002",
                interview_id=state.interview_id,
                turn_index=2,
                question="Previous question",
                answer_analysis=make_analysis(AnswerQuality.OFF_TOPIC, intent=CandidateIntent.OFF_TOPIC),
                next_move=planner.plan(
                    state=state,
                    analysis=make_analysis(AnswerQuality.OFF_TOPIC, intent=CandidateIntent.OFF_TOPIC),
                ),
            ),
        ]
    )

    decision = planner.plan(
        state=state,
        analysis=make_analysis(
            AnswerQuality.REFUSAL,
            skill_id="api_design",
            intent=CandidateIntent.REFUSAL,
        ),
    )

    assert decision.move_type == MoveType.REPAIR_AND_REDIRECT
    assert decision.target_skill_id == "role_fit"
    assert decision.should_end_interview is False


def test_strong_answer_drills_down_before_broadening_coverage() -> None:
    planner = NextMovePlanner()
    state = make_state()
    state.turns.append(
        InterviewTurn(
            turn_id="turn_001",
            interview_id=state.interview_id,
            turn_index=1,
            question="Previous question",
            next_move=planner.plan(state=state, analysis=make_analysis(AnswerQuality.PARTIAL)),
        )
    )

    decision = planner.plan(state=state, analysis=make_analysis(AnswerQuality.STRONG))

    assert decision.move_type == MoveType.DRILL_DOWN
    assert decision.target_skill_id == "python_concurrency"


def test_adjacent_topic_prefers_untouched_skill_over_retesting_high_importance_skill() -> None:
    planner = NextMovePlanner()
    state = make_state()
    state.skill_map.skills["python_concurrency"].attempts = 2
    state.skill_map.skills["api_design"].attempts = 2

    decision = planner.plan(
        state=state,
        analysis=make_analysis(AnswerQuality.REFUSAL, skill_id="python_concurrency"),
    )

    assert decision.move_type == MoveType.SWITCH_ADJACENT_TOPIC
    assert decision.target_skill_id == "system_design"


def test_explicit_stop_request_ends_interview_policy() -> None:
    planner = NextMovePlanner()
    state = make_state()
    analysis = make_analysis(AnswerQuality.REFUSAL)
    analysis.summary = "The candidate explicitly says they do not want to continue and asks to stop the interview."

    decision = planner.plan(state=state, analysis=analysis)

    assert decision.move_type == MoveType.WRAP_UP
    assert decision.should_end_interview is True
    assert "stop" in decision.interviewer_response.lower()
