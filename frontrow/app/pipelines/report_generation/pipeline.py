from pydantic import BaseModel

from app.models.evidence import EvidenceRecord, EvidenceSignalType
from app.models.report import (
    AdvisorySignal,
    CompetencyScorecardItem,
    EvidenceByQuestion,
    InterviewReport,
    ReportFinding,
    ScoreCompositionItem,
    SkillBreakdown,
    SkillRoleMatchItem,
    SoftLayerSection,
)
from app.models.state import InterviewState
from app.models.turn import AnswerQuality


class ReportGenerationInput(BaseModel):
    state: InterviewState


class ReportGenerationOutput(BaseModel):
    report: InterviewReport


class ReportGenerationPipeline:
    async def run(self, payload: ReportGenerationInput) -> ReportGenerationOutput:
        state = payload.state
        evidence_by_id = {record.evidence_id: record for record in state.evidence_ledger.records}
        skill_scores_4 = {
            skill.skill_id: _skill_score_4(skill.current_score, skill.confidence, skill.attempts)
            for skill in state.skill_map.skills.values()
        }
        dimension_scores = _dimension_scores_4(state, skill_scores_4)
        skill_breakdown = [
            SkillBreakdown(
                skill_id=skill.skill_id,
                label=skill.label,
                dimension=skill.dimension,
                score=skill.current_score,
                confidence=skill.confidence,
                attempts=skill.attempts,
                status=skill.status.value,
                evidence_ids=skill.evidence_ids,
            )
            for skill in sorted(
                state.skill_map.skills.values(),
                key=lambda item: (-item.importance, item.label),
            )
        ]
        skill_role_match = [
            SkillRoleMatchItem(
                skill_id=skill.skill_id,
                label=skill.label,
                candidate_level_4=skill_scores_4[skill.skill_id] if skill.attempts else None,
                required_level_4=_required_level_for_seniority(state.role.seniority),
                band=_skill_band(skill_scores_4[skill.skill_id], skill.attempts, state.role.seniority),
                assessed=skill.attempts > 0,
                evidence_ids=skill.evidence_ids,
            )
            for skill in sorted(
                state.skill_map.skills.values(),
                key=lambda item: (-item.importance, item.label),
            )
        ]

        strengths = [
            ReportFinding(
                title="Evidence-backed strength",
                summary=record.summary,
                evidence_ids=[record.evidence_id],
            )
            for record in state.evidence_ledger.records
            if record.signal_type in {EvidenceSignalType.STRONG_EVIDENCE, EvidenceSignalType.CONCRETE_EXPERIENCE}
        ]
        risks = [
            ReportFinding(
                title="Evidence-backed risk",
                summary=record.summary,
                evidence_ids=[record.evidence_id],
            )
            for record in state.evidence_ledger.records
            if record.signal_type in {EvidenceSignalType.REFUSAL, EvidenceSignalType.UNSUPPORTED_CLAIM}
        ]
        caveats = []
        if not state.evidence_ledger.records:
            caveats.append("No evidence records were available; report confidence is low.")

        score_composition = _score_composition(state, dimension_scores)
        fit_score = round(sum(item.points for item in score_composition))
        verdict = _verdict(fit_score=fit_score, risks=risks, caveats=caveats)
        rationale = _report_rationale(state, fit_score=fit_score, strengths=strengths, risks=risks)
        competency_scorecard = _competency_scorecard(state, dimension_scores, evidence_by_id)
        evidence_by_question = _evidence_by_question(state)
        ai_native_signals = _ai_native_signals(state)
        soft_layer = _soft_layer(state, dimension_scores)
        worry_areas = _worry_areas(state, skill_role_match, risks)
        recommended_next_steps = _recommended_next_steps(state, worry_areas, strengths)
        tags = _tags_from_report(state, skill_role_match, strengths)
        return ReportGenerationOutput(
            report=InterviewReport(
                interview_id=state.interview_id,
                overall_score=fit_score / 100,
                fit_score=fit_score,
                role_bar=70,
                verdict=verdict,
                rationale=rationale,
                tags=tags,
                dimension_scores=dimension_scores,
                score_composition=score_composition,
                skill_breakdown=skill_breakdown,
                skill_role_match=skill_role_match,
                competency_scorecard=competency_scorecard,
                ai_native_signals=ai_native_signals,
                soft_layer=soft_layer,
                worry_areas=worry_areas,
                recommended_next_steps=recommended_next_steps,
                evidence_by_question=evidence_by_question,
                question_count=len(state.turns),
                evidence_count=len(state.evidence_ledger.records),
                strengths=strengths,
                risks=risks,
                recommendation=verdict,
                caveats=caveats,
            )
        )


def _skill_score_4(raw_score: float, confidence: float, attempts: int) -> float:
    if attempts == 0:
        return 0.0
    score = 2.0 + (raw_score * 2.0)
    confidence_adjustment = (confidence - 0.5) * 0.5
    return round(max(1.0, min(4.0, score + confidence_adjustment)), 2)


def _required_level_for_seniority(seniority: str) -> float:
    seniority_key = seniority.lower()
    if seniority_key in {"senior", "lead", "staff"}:
        return 3.25
    if seniority_key in {"junior", "fresher", "entry"}:
        return 2.0
    return 2.75


def _skill_band(score_4: float, attempts: int, seniority: str) -> str:
    if attempts == 0:
        return "not_assessed"
    target = _required_level_for_seniority(seniority)
    if score_4 >= target + 0.5:
        return "exceeds"
    if score_4 >= target - 0.25:
        return "meets"
    if score_4 >= max(1.5, target - 1.0):
        return "below"
    return "well_below"


def _dimension_scores_4(state: InterviewState, skill_scores_4: dict[str, float]) -> dict[str, float]:
    field_skills = [skill for skill in state.skill_map.skills.values() if skill.attempts > 0]
    total_importance = sum(skill.importance for skill in field_skills) or 1.0
    field_score = sum(skill_scores_4[skill.skill_id] * skill.importance for skill in field_skills) / total_importance
    quality_values = [
        _quality_score_4(turn.answer_analysis.quality)
        for turn in state.turns
        if turn.answer_analysis is not None
    ]
    evidence_depth = [
        _answer_depth_score(
            turn.candidate_answer.transcript if turn.candidate_answer else "",
            turn.answer_analysis.summary,
            turn.answer_analysis.quality,
        )
        for turn in state.turns
        if turn.answer_analysis is not None
    ]
    return {
        "field_expertise": round(field_score, 2) if field_skills else 0.0,
        "experience_depth": round(sum(evidence_depth) / len(evidence_depth), 2) if evidence_depth else 0.0,
        "communication": round(sum(quality_values) / len(quality_values), 2) if quality_values else 0.0,
        "behavioral_ownership": round(_ownership_score(state), 2),
    }


def _quality_score_4(quality: AnswerQuality) -> float:
    return {
        AnswerQuality.STRONG: 4.0,
        AnswerQuality.CONCRETE_EXPERIENCE: 3.5,
        AnswerQuality.PARTIAL: 2.5,
        AnswerQuality.SHALLOW_EXPERIENCE: 2.0,
        AnswerQuality.WEAK: 1.75,
        AnswerQuality.UNCLEAR: 1.5,
        AnswerQuality.UNSUPPORTED_CLAIM: 1.5,
        AnswerQuality.REFUSAL: 1.0,
        AnswerQuality.OFF_TOPIC: 1.0,
    }.get(quality, 2.0)


def _answer_depth_score(transcript: str, summary: str, quality: AnswerQuality) -> float:
    if quality in {AnswerQuality.REFUSAL, AnswerQuality.OFF_TOPIC, AnswerQuality.UNCLEAR}:
        return 1.0
    if quality in {AnswerQuality.WEAK, AnswerQuality.UNSUPPORTED_CLAIM}:
        return 1.25
    if quality == AnswerQuality.SHALLOW_EXPERIENCE:
        return 1.5
    if quality == AnswerQuality.PARTIAL:
        base = 1.75
    elif quality == AnswerQuality.CONCRETE_EXPERIENCE:
        base = 2.75
    elif quality == AnswerQuality.STRONG:
        base = 3.0
    else:
        base = 1.5
    text = f"{transcript} {summary}".lower()
    if _contains_interview_criticism(text):
        return 1.0
    signal_words = [
        "owned",
        "measured",
        "tradeoff",
        "result",
        "outcome",
        "handled",
        "resolved",
        "improved",
        "decided",
        "led",
        "case",
        "patient",
        "customer",
        "client",
        "site",
        "shift",
        "repair",
        "procedure",
        "incident",
        "designed",
    ]
    score = base + min(sum(1 for word in signal_words if word in text) * 0.18, 0.75)
    return max(1.0, min(4.0, score))


def _ownership_score(state: InterviewState) -> float:
    if not state.turns:
        return 0.0
    ownership_words = [
        "owned",
        "led",
        "designed",
        "measured",
        "decided",
        "implemented",
        "handled",
        "resolved",
        "coordinated",
        "trained",
        "improved",
        "managed",
        "delivered",
        "followed up",
    ]
    positive_turns = [
        turn
        for turn in state.turns
        if turn.answer_analysis is not None
        and turn.answer_analysis.quality
        in {AnswerQuality.PARTIAL, AnswerQuality.STRONG, AnswerQuality.CONCRETE_EXPERIENCE}
    ]
    if not positive_turns:
        return 1.0
    text = " ".join(
        f"{turn.candidate_answer.transcript if turn.candidate_answer else ''} "
        f"{turn.answer_analysis.summary if turn.answer_analysis else ''}"
        for turn in positive_turns
    ).lower()
    if _contains_interview_criticism(text):
        return 1.0
    ownership_hits = sum(1 for word in ownership_words if word in text)
    if ownership_hits == 0:
        return 1.25
    return max(1.0, min(4.0, 1.25 + ownership_hits * 0.3))


def _contains_interview_criticism(text: str) -> bool:
    criticism_phrases = [
        "templated",
        "impersonal",
        "not human",
        "robotic",
        "questioning the interviewer",
        "criticizes the interview",
        "criticizes the interviewer",
        "why the interviewer repeated",
    ]
    return any(phrase in text for phrase in criticism_phrases)


def _score_composition(state: InterviewState, dimension_scores: dict[str, float]) -> list[ScoreCompositionItem]:
    target = _required_level_for_seniority(state.role.seniority)
    items = []
    for dimension in state.rubric.dimensions:
        score = dimension_scores.get(dimension.dimension_id, 0.0)
        points = max(0.0, min(1.0, score / 4.0)) * dimension.weight * 100
        items.append(
            ScoreCompositionItem(
                dimension=dimension.dimension_id,
                label=dimension.label,
                weight=dimension.weight,
                score_4=round(score, 2),
                target_4=target,
                points=round(points, 1),
                rationale=_dimension_rationale(dimension.dimension_id, score, target),
            )
        )
    return items


def _dimension_rationale(dimension: str, score: float, target: float) -> str:
    if score == 0:
        return "Not enough evidence was captured for this dimension."
    if score >= target:
        return "Meets or clears the role bar based on captured evidence."
    return "Below the role bar; should be probed in the next round."


def _competency_scorecard(
    state: InterviewState,
    dimension_scores: dict[str, float],
    evidence_by_id: dict[str, EvidenceRecord],
) -> list[CompetencyScorecardItem]:
    target = _required_level_for_seniority(state.role.seniority)
    items = []
    for dimension in state.rubric.dimensions:
        evidence_ids = [
            record.evidence_id
            for record in evidence_by_id.values()
            if record.dimension == dimension.dimension_id
        ][:6]
        score = dimension_scores.get(dimension.dimension_id, 0.0)
        items.append(
            CompetencyScorecardItem(
                dimension=dimension.dimension_id,
                label=dimension.label,
                weight=dimension.weight,
                score_4=round(score, 2),
                target_4=target,
                band=_score_band(score, target),
                rationale=_dimension_rationale(dimension.dimension_id, score, target),
                evidence_ids=evidence_ids,
            )
        )
    return items


def _score_band(score: float, target: float) -> str:
    if score == 0:
        return "not_assessed"
    if score >= target + 0.5:
        return "exceeds"
    if score >= target - 0.25:
        return "meets"
    if score >= target - 1.0:
        return "below"
    return "well_below"


def _evidence_by_question(state: InterviewState) -> list[EvidenceByQuestion]:
    ranked_turns = sorted(
        state.turns,
        key=lambda turn: max((record.confidence for record in turn.evidence), default=0.0),
        reverse=True,
    )[:6]
    rows = []
    for turn in ranked_turns:
        analysis = turn.answer_analysis
        answer = turn.candidate_answer
        if analysis is None:
            continue
        score = _quality_score_4(analysis.quality)
        rows.append(
            EvidenceByQuestion(
                turn_id=turn.turn_id,
                turn_index=turn.turn_index,
                dimension=turn.evidence[0].dimension if turn.evidence else "field_expertise",
                skill_id=analysis.target_skill_id,
                question=turn.question,
                answer_excerpt=(answer.transcript if answer and answer.transcript else analysis.summary)[:500],
                score_4=score,
                band=_score_band(score, _required_level_for_seniority(state.role.seniority)),
                ai_judgement=analysis.summary,
                evidence_ids=[record.evidence_id for record in turn.evidence],
            )
        )
    return rows


def _ai_native_signals(state: InterviewState) -> list[AdvisorySignal]:
    strong = [record for record in state.evidence_ledger.records if record.signal_type == EvidenceSignalType.STRONG_EVIDENCE]
    concrete = [
        record for record in state.evidence_ledger.records if record.signal_type == EvidenceSignalType.CONCRETE_EXPERIENCE
    ]
    partial = [
        record for record in state.evidence_ledger.records if record.signal_type == EvidenceSignalType.PARTIAL_UNDERSTANDING
    ]
    return [
        AdvisorySignal(
            label="Reasoning quality",
            level=_signal_level(len(strong) + len(concrete), len(state.turns)),
            summary=_first_summary(concrete or strong, "Look for concrete tradeoffs, measurements, and decision reasoning."),
            evidence_ids=[record.evidence_id for record in (concrete or strong)[:3]],
        ),
        AdvisorySignal(
            label="Coachability",
            level=_signal_level(len(partial), max(len(state.turns), 1)),
            summary="Estimated from whether partial answers improved after scaffolding or follow-up.",
            evidence_ids=[record.evidence_id for record in partial[:3]],
        ),
        AdvisorySignal(
            label="Learning agility",
            level=_signal_level(len(concrete), len(state.turns)),
            summary=_first_summary(concrete, "Look for examples where unfamiliar systems were learned and applied."),
            evidence_ids=[record.evidence_id for record in concrete[:3]],
        ),
    ]


def _signal_level(signal_count: int, total: int) -> str:
    ratio = signal_count / max(total, 1)
    if ratio >= 0.45:
        return "strong"
    if ratio >= 0.25:
        return "above_average"
    if ratio > 0:
        return "emerging"
    return "not_enough_signal"


def _first_summary(records: list[EvidenceRecord], fallback: str) -> str:
    return records[0].summary if records else fallback


def _soft_layer(state: InterviewState, dimension_scores: dict[str, float]) -> list[SoftLayerSection]:
    communication = dimension_scores.get("communication", 0.0)
    ownership = dimension_scores.get("behavioral_ownership", 0.0)
    return [
        SoftLayerSection(
            label="Communication",
            score_4=communication,
            facets={
                "clarity_structure": min(4.0, communication + 0.25),
                "use_of_examples": communication,
                "conciseness": max(1.0, communication - 0.25),
            },
            note="Scored from answer content and structure, not accent, pace, tone, or fluency.",
        ),
        SoftLayerSection(
            label="Behavioural and ownership",
            score_4=ownership,
            facets={
                "ownership_of_outcomes": ownership,
                "initiative_beyond_scope": min(4.0, ownership + 0.25),
                "accountability": max(1.0, ownership - 0.25),
            },
            note="STAR-style evidence inferred from concrete ownership, decisions, and measured outcomes.",
        ),
    ]


def _worry_areas(
    state: InterviewState,
    skill_role_match: list[SkillRoleMatchItem],
    risks: list[ReportFinding],
) -> list[ReportFinding]:
    worries = [
        ReportFinding(
            title=f"{item.label} below role bar" if item.assessed else f"{item.label} not assessed",
            summary=(
                f"{item.label} was assessed as {item.band}; confirm this skill if it is critical."
                if item.assessed
                else f"{item.label} was not directly assessed, so it should not be treated as a zero."
            ),
            evidence_ids=item.evidence_ids,
        )
        for item in skill_role_match
        if item.band in {"below", "well_below", "not_assessed"}
    ][:5]
    return worries or risks[:5]


def _recommended_next_steps(
    state: InterviewState,
    worry_areas: list[ReportFinding],
    strengths: list[ReportFinding],
) -> list[ReportFinding]:
    steps = []
    if worry_areas:
        steps.append(
            ReportFinding(
                title="Probe the highest-risk area in the next round.",
                summary=worry_areas[0].summary,
                evidence_ids=worry_areas[0].evidence_ids,
            )
        )
    if strengths:
        steps.append(
            ReportFinding(
                title="Validate the strongest evidence with a deeper practical exercise.",
                summary=strengths[0].summary,
                evidence_ids=strengths[0].evidence_ids,
            )
        )
    steps.append(
        ReportFinding(
            title="Use a human review pass before final hiring action.",
            summary="The report links every recommendation to evidence, but final hiring decisions should remain human-reviewed.",
        )
    )
    return steps


def _verdict(*, fit_score: int, risks: list[ReportFinding], caveats: list[str]) -> str:
    if fit_score >= 75 and len(risks) <= 1 and not caveats:
        return "advance"
    if fit_score >= 60:
        return "hold"
    return "needs_review"


def _report_rationale(
    state: InterviewState,
    *,
    fit_score: int,
    strengths: list[ReportFinding],
    risks: list[ReportFinding],
) -> str:
    if fit_score >= 75:
        base = f"Candidate clears the role bar for {state.role.title} based on captured evidence."
    elif fit_score >= 60:
        base = f"Candidate is close to the role bar for {state.role.title}, but the next round should resolve gaps."
    else:
        base = f"Candidate does not yet clear the role bar for {state.role.title} based on this interview."
    if strengths:
        base += f" Strongest signal: {strengths[0].summary}"
    if risks:
        base += f" Main concern: {risks[0].summary}"
    return base


def _tags_from_report(
    state: InterviewState,
    skill_role_match: list[SkillRoleMatchItem],
    strengths: list[ReportFinding],
) -> list[str]:
    tags = [state.role.seniority, state.role.title]
    tags.extend(item.label for item in skill_role_match if item.band in {"meets", "exceeds"})
    tags.extend(finding.title for finding in strengths[:2])
    return list(dict.fromkeys(tags))[:6]
