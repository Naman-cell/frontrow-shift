from dataclasses import dataclass

from app.models.next_move import MoveType, NextMoveDecision
from app.models.skill_map import SkillNode, SkillStatus
from app.models.state import InterviewState
from app.models.turn import AnswerAnalysis, AnswerQuality, CandidateIntent


@dataclass(frozen=True)
class InterviewPolicy:
    max_same_skill_attempts: int = 2
    max_low_signal_streak_before_wrap: int = 3
    scaffold_retry_importance_threshold: float = 0.65
    closing_buffer_seconds: int = 180
    low_time_seconds: int = 120
    closing_time_seconds: int = 45


class NextMovePlanner:
    def __init__(self, policy: InterviewPolicy | None = None) -> None:
        self.policy = policy or InterviewPolicy()

    def plan(self, *, state: InterviewState, analysis: AnswerAnalysis) -> NextMoveDecision:
        recent_skill_ids = [turn.next_move.target_skill_id for turn in state.turns[-2:] if turn.next_move]
        target_skill = state.skill_map.get_or_create(analysis.target_skill_id, analysis.target_skill_label)
        evidence_used = state.evidence_ledger.ids_for_skill(target_skill.skill_id)
        low_signal_streak = self._low_signal_streak(state=state, current=analysis)
        closing_buffer_seconds = self._closing_buffer_seconds(state)
        final_wrap_seconds = self._final_wrap_seconds(state)
        low_time_seconds = self._low_time_seconds(state)

        if self._candidate_wants_to_stop(analysis):
            return self._decision(
                MoveType.WRAP_UP,
                target_skill,
                "Candidate explicitly indicated they do not want to continue, so stop the interview gracefully.",
                evidence_used,
                alternatives_avoided=["ask_another_question_after_stop_request"],
                interviewer_response="Understood, we can stop here. Thank you for your time.",
                should_end_interview=True,
            )

        if state.closing_question_sent:
            closing_response = self._closing_response_after_candidate_space(state=state, analysis=analysis)
            return self._decision(
                MoveType.WRAP_UP,
                target_skill,
                (
                    "Candidate used the closing space, so address their final input "
                    "and close the interview."
                ),
                evidence_used,
                time_consideration="closing phase complete",
                interviewer_response=closing_response,
                should_end_interview=True,
            )

        if state.time_remaining_seconds <= final_wrap_seconds:
            return self._decision(
                MoveType.WRAP_UP,
                target_skill,
                "Interview time is nearly exhausted, so the next move is to close gracefully.",
                evidence_used,
                time_consideration=f"{final_wrap_seconds} seconds or less remaining",
                interviewer_response="We are right at time, so I will wrap here. Thank you for speaking with me today.",
                should_end_interview=True,
            )

        if state.time_remaining_seconds <= closing_buffer_seconds and not state.closing_question_sent:
            role_fit = state.skill_map.get_or_create("candidate_questions", "Candidate questions")
            return self._decision(
                MoveType.CANDIDATE_QUESTIONS,
                role_fit,
                "Enough time remains for candidate questions and a clean outro, so start the closing phase now.",
                evidence_used,
                alternatives_avoided=["start_new_deep_topic_too_late"],
                time_consideration="closing buffer reached",
                interviewer_response="We are close to time.",
            )

        if low_signal_streak >= self.policy.max_low_signal_streak_before_wrap:
            consecutive_role_fit = self._consecutive_role_fit_repairs(state)
            if not state.closing_question_sent and state.time_remaining_seconds <= closing_buffer_seconds:
                role_fit = state.skill_map.get_or_create("candidate_questions", "Candidate questions")
                return self._decision(
                    MoveType.CANDIDATE_QUESTIONS,
                    role_fit,
                    "Candidate has had several low-signal turns and the interview is near closing, so give them one final chance to ask questions or add context.",
                    evidence_used,
                    alternatives_avoided=["end_without_candidate_closing_space", "keep_pressuring_candidate"],
                    time_consideration="closing buffer reached after low-signal turns",
                    interviewer_response="No problem, we do not need to stay stuck there.",
                )
            if consecutive_role_fit >= 2:
                if not state.closing_question_sent:
                    cq_skill = state.skill_map.get_or_create("candidate_questions", "Candidate questions")
                    return self._decision(
                        MoveType.CANDIDATE_QUESTIONS,
                        cq_skill,
                        "Candidate has not been able to provide signal across multiple role-fit redirects; offer closing space before ending.",
                        evidence_used,
                        alternatives_avoided=["keep_looping_on_role_fit", "keep_pressuring_candidate"],
                        interviewer_response="That is completely fine.",
                    )
                wrap_skill = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
                return self._decision(
                    MoveType.WRAP_UP,
                    wrap_skill,
                    "Candidate has not been able to provide signal after repeated role-fit redirects; close gracefully.",
                    evidence_used,
                    alternatives_avoided=["keep_looping_on_role_fit", "keep_pressuring_candidate"],
                    interviewer_response="That is completely fine, we can wrap up here. Thank you for your time.",
                    should_end_interview=True,
                )
            if state.time_remaining_seconds > closing_buffer_seconds:
                role_fit = state.skill_map.get_or_create("role_fit", "Role fit and background")
                return self._decision(
                    MoveType.REPAIR_AND_REDIRECT,
                    role_fit,
                    "Multiple low-signal turns happened while meaningful time remains, so step back to role-fit background instead of ending early.",
                    evidence_used,
                    alternatives_avoided=["end_too_early", "keep_pressuring_candidate"],
                    interviewer_response="No problem, we do not need to stay stuck there.",
                )
            wrap_skill = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
            return self._decision(
                MoveType.WRAP_UP,
                wrap_skill,
                "Multiple low-signal or disengaged turns in a row; close gently instead of pressuring the candidate.",
                evidence_used,
                alternatives_avoided=["keep_pressuring_candidate", "repeat_failed_topic"],
                interviewer_response="No problem, we do not need to stay stuck there.",
                should_end_interview=True,
            )

        if analysis.intent == CandidateIntent.REPEAT_REQUEST:
            return self._decision(
                MoveType.REPEAT_QUESTION,
                target_skill,
                "Candidate asked for repetition, so repeat the current question without changing topic.",
                evidence_used,
                alternatives_avoided=["advance_without_answer"],
                interviewer_response="Of course, let me say it again more clearly.",
            )

        if analysis.intent == CandidateIntent.PIVOT_REQUEST or analysis.preferred_topics:
            preferred_skill = self._preferred_skill(state=state, analysis=analysis)
            if preferred_skill is not None and preferred_skill.skill_id != target_skill.skill_id:
                return self._decision(
                    MoveType.REPAIR_AND_REDIRECT,
                    preferred_skill,
                    "Candidate signaled a stronger or preferred area; redirect naturally while preserving role-relevant coverage.",
                    evidence_used,
                    alternatives_avoided=["ignore_candidate_preference"],
                    interviewer_response=analysis.suggested_interviewer_response
                    or "Got it, let's use that direction.",
                )

        if analysis.intent == CandidateIntent.CLARIFICATION_REQUEST:
            return self._decision(
                MoveType.CLARIFY_AND_REASK,
                target_skill,
                "Candidate asked for clarification, so clarify the ask and keep the same evaluation target.",
                evidence_used,
                alternatives_avoided=["penalize_clarification_request"],
                interviewer_response="Sure, let me make that more specific.",
            )

        if analysis.intent in {CandidateIntent.SILENCE_OR_NOISE, CandidateIntent.OFF_TOPIC}:
            if target_skill.attempts <= 1:
                return self._decision(
                    MoveType.CLARIFY_AND_REASK,
                    target_skill,
                    "The answer did not produce usable signal, so offer one clearer retry.",
                    evidence_used,
                    alternatives_avoided=["score_noise_as_knowledge_gap"],
                    interviewer_response="I could not get a clear signal from that.",
                )
            adjacent = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
            return self._decision(
                MoveType.REPAIR_AND_REDIRECT,
                adjacent,
                "The current topic has not produced signal after a retry; redirect to a practical adjacent area.",
                evidence_used,
                alternatives_avoided=["loop_on_unclear_answer"],
                interviewer_response=(
                    "I hear you, but that example seems outside this role context."
                    if analysis.intent == CandidateIntent.OFF_TOPIC
                    else "No worries, let's try a more practical angle."
                ),
            )

        if analysis.intent in {CandidateIntent.DISENGAGED, CandidateIntent.FRUSTRATED}:
            return self._decision(
                MoveType.WRAP_UP,
                target_skill,
                "Candidate sounded disengaged or frustrated, so end gracefully instead of continuing.",
                evidence_used,
                alternatives_avoided=["increase_difficulty", "ask_more_after_frustration"],
                interviewer_response="That's okay, we can stop here. Thanks for your time today.",
                should_end_interview=True,
            )

        if state.time_remaining_seconds <= low_time_seconds:
            coverage_target = state.skill_map.next_coverage_target(set(recent_skill_ids)) or target_skill
            return self._decision(
                MoveType.TIME_BOXED_COVERAGE,
                coverage_target,
                "Low time remains, so prioritize the most important uncovered area.",
                evidence_used,
                alternatives_avoided=["drill_down", "scaffold_retry"],
                time_consideration=f"{low_time_seconds} seconds or less remaining",
            )

        if analysis.quality == AnswerQuality.REFUSAL:
            if (
                target_skill.importance >= self.policy.scaffold_retry_importance_threshold
                and target_skill.attempts <= 1
            ):
                return self._decision(
                    MoveType.SCAFFOLD_RETRY,
                    target_skill,
                    "Candidate did not know an important skill; offer one simpler retry before moving on.",
                    evidence_used,
                    alternatives_avoided=["mark_important_skill_failed_after_one_try"],
                    interviewer_response="No problem, let's try it from a simpler angle.",
                )
            adjacent = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
            return self._decision(
                MoveType.SWITCH_ADJACENT_TOPIC,
                adjacent,
                "Candidate could not answer; acknowledge it and move to a nearby skill rather than trapping them.",
                evidence_used,
                alternatives_avoided=["scaffold_retry_after_refusal"],
            )

        if analysis.quality == AnswerQuality.UNSUPPORTED_CLAIM or analysis.resume_claim_detected:
            target_skill.status = SkillStatus.NEEDS_VALIDATION
            return self._decision(
                MoveType.VALIDATE_RESUME_CLAIM,
                target_skill,
                "Candidate made a resume or experience claim without enough concrete supporting evidence.",
                evidence_used,
                alternatives_avoided=["accept_claim_without_validation"],
            )

        if analysis.quality in {AnswerQuality.PARTIAL, AnswerQuality.WEAK, AnswerQuality.UNCLEAR}:
            if (
                target_skill.importance >= self.policy.scaffold_retry_importance_threshold
                and target_skill.scaffold_attempts < 1
                and target_skill.attempts <= self.policy.max_same_skill_attempts
            ):
                return self._decision(
                    MoveType.SCAFFOLD_RETRY,
                    target_skill,
                    "The skill matters for the role and the answer needs a more supported retry.",
                    evidence_used,
                    alternatives_avoided=["switch_topic_too_early"],
            )
            adjacent = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
            return self._decision(
                MoveType.SWITCH_ADJACENT_TOPIC,
                adjacent,
                "The answer was limited and this area has already had enough support for now.",
                evidence_used,
            )

        if analysis.quality in {AnswerQuality.STRONG, AnswerQuality.CONCRETE_EXPERIENCE}:
            real_skills = [
                s for s in state.skill_map.skills.values()
                if s.skill_id not in {"candidate_questions", "role_fit"}
            ]
            untouched = sum(1 for s in real_skills if s.attempts == 0)
            if untouched > 0 and untouched / max(len(real_skills), 1) > 0.5:
                adjacent = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
                return self._decision(
                    MoveType.SWITCH_ADJACENT_TOPIC,
                    adjacent,
                    "Prioritizing breadth: more than half the required skills remain untouched.",
                    evidence_used,
                    alternatives_avoided=["drill_down_before_coverage"],
                )
            if target_skill.attempts <= self.policy.max_same_skill_attempts and target_skill.target_depth != "low":
                return self._decision(
                    MoveType.DRILL_DOWN,
                    target_skill,
                    "Candidate gave useful evidence, so a deeper probe can test depth and tradeoffs.",
                    evidence_used,
                )
            adjacent = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
            return self._decision(
                MoveType.SWITCH_ADJACENT_TOPIC,
                adjacent,
                "The skill has enough evidence for now; broaden coverage.",
                evidence_used,
            )

        if target_skill.skill_id in recent_skill_ids and len(state.skill_map.skills) > 1:
            adjacent = state.skill_map.next_coverage_target({target_skill.skill_id}) or target_skill
            return self._decision(
                MoveType.SWITCH_ADJACENT_TOPIC,
                adjacent,
                "This topic has enough signal for now; broaden coverage with a natural transition.",
                evidence_used,
                alternatives_avoided=["over_probe_same_topic"],
            )

        return self._decision(
            MoveType.ASK_FOR_EXAMPLE,
            target_skill,
            "Ask for a concrete example to convert a vague answer into usable evidence.",
            evidence_used,
        )

    def _preferred_skill(self, *, state: InterviewState, analysis: AnswerAnalysis) -> SkillNode | None:
        if analysis.preferred_relevant_skill_id and analysis.preferred_relevant_skill_id in state.skill_map.skills:
            return state.skill_map.skills[analysis.preferred_relevant_skill_id]
        preferred_tokens = {
            token
            for topic in analysis.preferred_topics
            for token in topic.lower().replace("/", " ").replace("-", " ").split()
            if len(token) > 2
        }
        if not preferred_tokens:
            return None
        candidates = []
        for skill in state.skill_map.skills.values():
            label_tokens = set(skill.label.lower().replace("/", " ").replace("-", " ").split())
            overlap = len(preferred_tokens & label_tokens)
            if overlap:
                candidates.append((overlap, skill.importance, -skill.attempts, skill))
        if candidates:
            return max(candidates, key=lambda item: item[:3])[3]
        return None

    def _decision(
        self,
        move_type: MoveType,
        skill: SkillNode,
        reason: str,
        evidence_used: list[str],
        alternatives_avoided: list[str] | None = None,
        time_consideration: str | None = None,
        interviewer_response: str = "",
        should_end_interview: bool = False,
    ) -> NextMoveDecision:
        return NextMoveDecision(
            move_type=move_type,
            target_skill_id=skill.skill_id,
            target_skill_label=skill.label,
            reason=reason,
            evidence_used=evidence_used,
            alternatives_avoided=alternatives_avoided or [],
            time_consideration=time_consideration,
            interviewer_response=interviewer_response,
            should_end_interview=should_end_interview,
        )

    def _low_signal_streak(self, *, state: InterviewState, current: AnswerAnalysis) -> int:
        low_signal_qualities = {
            AnswerQuality.REFUSAL,
            AnswerQuality.WEAK,
            AnswerQuality.UNCLEAR,
            AnswerQuality.OFF_TOPIC,
        }
        low_signal_intents = {
            CandidateIntent.REFUSAL,
            CandidateIntent.SILENCE_OR_NOISE,
            CandidateIntent.DISENGAGED,
            CandidateIntent.FRUSTRATED,
            CandidateIntent.OFF_TOPIC,
        }
        streak = 0
        analyses = [
            turn.answer_analysis
            for turn in reversed(state.turns[-3:])
            if turn.answer_analysis is not None
        ]
        analyses.insert(0, current)
        for analysis in analyses:
            if analysis.quality in low_signal_qualities or analysis.intent in low_signal_intents:
                streak += 1
            else:
                break
        return streak

    def _consecutive_role_fit_repairs(self, state: InterviewState) -> int:
        """Count how many recent consecutive turns were repair_and_redirect to role_fit."""
        count = 0
        for turn in reversed(state.turns):
            if (
                turn.next_move
                and turn.next_move.move_type == MoveType.REPAIR_AND_REDIRECT
                and turn.next_move.target_skill_id == "role_fit"
            ):
                count += 1
            else:
                break
        return count

    def _candidate_wants_to_stop(self, analysis: AnswerAnalysis) -> bool:
        text = " ".join(
            part
            for part in [
                analysis.transcript,
                analysis.summary,
                analysis.suggested_interviewer_response,
                analysis.extracted_claim or "",
                " ".join(analysis.missing_expected_points),
            ]
            if part
        ).lower()
        stop_phrases = [
            "do not want to continue",
            "don't want to continue",
            "dont want to continue",
            "does not want to continue",
            "stop the interview",
            "stop this interview",
            "end the interview",
            "end this interview",
            "not continue",
            "no longer continue",
            "demanding to stop",
            "stop here",
            "end here",
            "i want to stop",
            "i dont feel like",
            "i don't feel like",
            "don't want to do this",
            "dont want to do this",
            "can we stop",
            "please stop",
            "i want to leave",
            "let me go",
        ]
        if analysis.intent in {CandidateIntent.DISENGAGED, CandidateIntent.FRUSTRATED}:
            return True
        return any(phrase in text for phrase in stop_phrases)

    def _closing_response_after_candidate_space(
        self,
        *,
        state: InterviewState,
        analysis: AnswerAnalysis,
    ) -> str:
        response = (analysis.suggested_interviewer_response or "").strip()
        if response and not _contains_placeholder(response):
            return _with_signoff(_strip_trailing_question(response))
        if analysis.intent == CandidateIntent.CANDIDATE_QUESTION:
            return (
                f"That's a fair question. Based on the role brief I have, this {state.role.title} "
                f"role is centered on {_role_brief(state)}. The hiring team can share the exact "
                "team expectations and next steps after this round. Thank you for taking the time today."
            )
        if analysis.quality in {
            AnswerQuality.STRONG,
            AnswerQuality.CONCRETE_EXPERIENCE,
            AnswerQuality.PARTIAL,
        }:
            return _with_signoff(
                "Thanks for adding that context. I have enough from this conversation, "
                "so we can close here."
            )
        return "Thanks for your time today. We can close here."

    def _closing_buffer_seconds(self, state: InterviewState) -> int:
        total_seconds = max(state.duration_minutes * 60, 1)
        return max(45, min(self.policy.closing_buffer_seconds, int(total_seconds * 0.25)))

    def _low_time_seconds(self, state: InterviewState) -> int:
        total_seconds = max(state.duration_minutes * 60, 1)
        return max(30, min(self.policy.low_time_seconds, int(total_seconds * 0.18)))

    def _closing_time_seconds(self, state: InterviewState) -> int:
        total_seconds = max(state.duration_minutes * 60, 1)
        return max(20, min(self.policy.closing_time_seconds, int(total_seconds * 0.12)))

    def _final_wrap_seconds(self, state: InterviewState) -> int:
        total_seconds = max(state.duration_minutes * 60, 1)
        return max(12, min(18, int(total_seconds * 0.06)))


def _strip_trailing_question(text: str) -> str:
    stripped = text.strip()
    if not stripped.endswith("?"):
        return stripped
    return stripped.rstrip("?").rstrip() + "."


def _contains_placeholder(text: str) -> bool:
    lowered = text.lower()
    placeholder_markers = [
        "[",
        "]",
        "briefly mention",
        "e.g.",
        "for example:",
        "insert",
        "placeholder",
        "specific details here",
    ]
    return any(marker in lowered for marker in placeholder_markers)


def _with_signoff(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    if any(phrase in lowered for phrase in ["thank you", "thanks for", "thanks again"]):
        return stripped
    return f"{stripped} Thank you for taking the time today."


def _role_brief(state: InterviewState) -> str:
    jd_summary = " ".join(state.role.job_description_summary.split())
    if jd_summary:
        return jd_summary.rstrip(".")
    skills = [skill.strip() for skill in state.role.required_skills if skill.strip()]
    if not skills:
        return "the core responsibilities described for the position"
    if len(skills) == 1:
        return skills[0]
    return ", ".join(skills[:3])
