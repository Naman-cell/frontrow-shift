"""Haystack component nodes for the report generation pipeline."""

import logging
import os
from time import perf_counter

os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "false")

from haystack import component

from report_engine.models import (
    AdvisorySignal,
    CompetencyScorecardItem,
    EvidenceByQuestion,
    EvidenceRecord,
    EvidenceSignalType,
    InterviewReport,
    InterviewState,
    ReportFinding,
    ScoreCompositionItem,
    SkillBreakdown,
    SkillRoleMatchItem,
    SkillScoreDetail,
)
from report_engine.heuristics import (
    quality_score_4,
    report_rationale,
    soft_layer as heuristic_soft_layer,
)
from report_engine.scoring_service import (
    DimensionScoringResult,
    EvidenceAnalysisResult,
    HeuristicReportScoringService,
    ReportScoringService,
    SkillAssessmentResult,
)

LOGGER = logging.getLogger(__name__)


# ── Deterministic helpers ────────────────────────────────────────────


def skill_score_4(raw_score: float, confidence: float, attempts: int) -> float:
    if attempts == 0:
        return 0.0
    score = 2.0 + (raw_score * 2.0)
    confidence_adjustment = (confidence - 0.5) * 0.5
    return round(max(1.0, min(4.0, score + confidence_adjustment)), 2)


def required_level_for_seniority(seniority: str) -> float:
    seniority_key = seniority.lower()
    if seniority_key in {"senior", "lead", "staff"}:
        return 3.25
    if seniority_key in {"junior", "fresher", "entry"}:
        return 2.0
    return 2.75


def skill_band(score_4_val: float, attempts: int, seniority: str) -> str:
    if attempts == 0:
        return "not_assessed"
    target = required_level_for_seniority(seniority)
    if score_4_val >= target + 0.5:
        return "exceeds"
    if score_4_val >= target - 0.25:
        return "meets"
    if score_4_val >= max(1.5, target - 1.0):
        return "below"
    return "well_below"


def score_band(score: float, target: float) -> str:
    if score == 0:
        return "not_assessed"
    if score >= target + 0.5:
        return "exceeds"
    if score >= target - 0.25:
        return "meets"
    if score >= target - 1.0:
        return "below"
    return "well_below"


def score_label(score_4: float) -> str:
    if score_4 == 0:
        return "not_assessed"
    if score_4 >= 3.5:
        return "exceeds_expectation"
    if score_4 >= 2.5:
        return "meets_expectation"
    if score_4 >= 1.5:
        return "below_expectation"
    return "well_below_expectation"


def signal_level(signal_count: int, total: int) -> str:
    ratio = signal_count / max(total, 1)
    if ratio >= 0.45:
        return "strong"
    if ratio >= 0.25:
        return "above_average"
    if ratio > 0:
        return "emerging"
    return "not_enough_signal"


# ── Haystack component nodes ─────────────────────────────────────────


@component
class TranscriptCompilerNode:
    """Compile turns into structured data for downstream Gemini nodes."""

    @component.output_types(
        state=InterviewState,
        skill_scores_4=dict,
    )
    def run(self, state: InterviewState) -> dict:
        scores = {
            skill.skill_id: skill_score_4(skill.current_score, skill.confidence, skill.attempts)
            for skill in state.skill_map.skills.values()
        }
        return {"state": state, "skill_scores_4": scores}


@component
class GeminiDimensionScorerNode:
    """Score the 4 rubric dimensions using Gemini (or heuristic fallback)."""

    def __init__(self, service: ReportScoringService | None = None) -> None:
        self.service = service or HeuristicReportScoringService()

    @component.output_types(dimension_result=DimensionScoringResult)
    def run(self, state: InterviewState, skill_scores_4: dict) -> dict:
        raise NotImplementedError("Use run_async()")

    @component.output_types(dimension_result=DimensionScoringResult)
    async def run_async(self, state: InterviewState, skill_scores_4: dict) -> dict:
        started = perf_counter()
        result = await self.service.score_dimensions(state, skill_scores_4)
        ms = int((perf_counter() - started) * 1000)
        LOGGER.info("report_dimension_scorer_ms=%d", ms)
        return {"dimension_result": result}


@component
class GeminiSkillAssessorNode:
    """Assess each required skill individually using Gemini."""

    def __init__(self, service: ReportScoringService | None = None) -> None:
        self.service = service or HeuristicReportScoringService()

    @component.output_types(skill_result=SkillAssessmentResult)
    def run(self, state: InterviewState) -> dict:
        raise NotImplementedError("Use run_async()")

    @component.output_types(skill_result=SkillAssessmentResult)
    async def run_async(self, state: InterviewState) -> dict:
        started = perf_counter()
        result = await self.service.assess_skills(state)
        ms = int((perf_counter() - started) * 1000)
        LOGGER.info("report_skill_assessor_ms=%d", ms)
        return {"skill_result": result}


@component
class GeminiEvidenceAnalyzerNode:
    """Analyze evidence quality per turn using Gemini."""

    def __init__(self, service: ReportScoringService | None = None) -> None:
        self.service = service or HeuristicReportScoringService()

    @component.output_types(evidence_result=EvidenceAnalysisResult)
    def run(self, state: InterviewState) -> dict:
        raise NotImplementedError("Use run_async()")

    @component.output_types(evidence_result=EvidenceAnalysisResult)
    async def run_async(self, state: InterviewState) -> dict:
        started = perf_counter()
        result = await self.service.analyze_evidence(state)
        ms = int((perf_counter() - started) * 1000)
        LOGGER.info("report_evidence_analyzer_ms=%d", ms)
        return {"evidence_result": result}


@component
class ReportAssemblerNode:
    """Merge Gemini outputs with deterministic scoring into InterviewReport."""

    @component.output_types(report=InterviewReport)
    def run(
        self,
        state: InterviewState,
        skill_scores_4: dict,
        dimension_result: DimensionScoringResult,
        skill_result: SkillAssessmentResult,
        evidence_result: EvidenceAnalysisResult,
    ) -> dict:
        evidence_by_id = {r.evidence_id: r for r in state.evidence_ledger.records}
        seniority = state.role.seniority
        target = required_level_for_seniority(seniority)

        # Use Gemini dimension scores if available, else from heuristic
        dimension_scores = {
            dim_id: ds.score_4
            for dim_id, ds in dimension_result.scores.items()
        }

        # Build skill breakdown
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
                key=lambda s: (-s.importance, s.label),
            )
        ]

        # Build skill-role match, using Gemini skill scores when available
        skill_role_match = []
        for skill in sorted(state.skill_map.skills.values(), key=lambda s: (-s.importance, s.label)):
            gemini_assessment = skill_result.assessments.get(skill.skill_id)
            if gemini_assessment and gemini_assessment.score_4 > 0:
                s4 = gemini_assessment.score_4
            else:
                s4 = skill_scores_4.get(skill.skill_id, 0.0)
            skill_role_match.append(
                SkillRoleMatchItem(
                    skill_id=skill.skill_id,
                    label=skill.label,
                    candidate_level_4=round(s4, 2) if skill.attempts else None,
                    required_level_4=target,
                    band=skill_band(s4, skill.attempts, seniority),
                    assessed=skill.attempts > 0,
                    evidence_ids=skill.evidence_ids,
                )
            )

        # Strengths and risks from evidence ledger
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

        # Score composition with per-skill details and Gemini rationales
        score_composition = _build_score_composition(
            state, dimension_scores, skill_scores_4, dimension_result, skill_result,
        )
        fit_score = round(sum(item.points for item in score_composition))

        verdict = _verdict(fit_score=fit_score, risks=risks, caveats=caveats)

        # Use Gemini rationale if available, else heuristic
        rationale = dimension_result.overall_rationale or report_rationale(
            state, fit_score=fit_score, strengths=strengths, risks=risks,
        )

        # Competency scorecard with Gemini rationales
        competency_scorecard = _build_competency_scorecard(
            state, dimension_scores, evidence_by_id, dimension_result,
        )

        # Evidence by question — enriched with Gemini analysis
        evidence_by_question = _build_evidence_by_question(state, evidence_result, seniority)

        # AI native signals
        ai_native_signals = _build_ai_native_signals(state)

        # Soft layer — use Gemini dimension scores
        soft = heuristic_soft_layer(state, dimension_scores)

        # Worry areas and next steps
        worry_areas = _build_worry_areas(skill_role_match, risks)
        recommended_next_steps = _build_recommended_next_steps(worry_areas, strengths)
        tags = _build_tags(state, skill_role_match, strengths)

        report = InterviewReport(
            interview_id=state.interview_id,
            overall_score=fit_score / 100,
            fit_score=fit_score,
            role_bar=100,
            verdict=verdict,
            rationale=rationale,
            tags=tags,
            dimension_scores=dimension_scores,
            score_composition=score_composition,
            skill_breakdown=skill_breakdown,
            skill_role_match=skill_role_match,
            competency_scorecard=competency_scorecard,
            ai_native_signals=ai_native_signals,
            soft_layer=soft,
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
        return {"report": report}


# ── Assembler helpers ────────────────────────────────────────────────


def _build_score_composition(
    state: InterviewState,
    dimension_scores: dict[str, float],
    skill_scores_4: dict[str, float],
    dimension_result: DimensionScoringResult,
    skill_result: SkillAssessmentResult,
) -> list[ScoreCompositionItem]:
    target = required_level_for_seniority(state.role.seniority)
    items = []
    for dimension in state.rubric.dimensions:
        score = dimension_scores.get(dimension.dimension_id, 0.0)
        # Score 1.0 is the floor ("no signal"), so subtract it before normalizing.
        # Normalize against the target range so that meeting target = full weight.
        effective = max(0.0, score - 1.0)
        normalized = effective / max(target - 1.0, 0.5)
        points = min(1.0, normalized) * dimension.weight * 100

        # Use Gemini rationale if available
        dim_score = dimension_result.scores.get(dimension.dimension_id)
        rationale = (dim_score.rationale if dim_score and dim_score.rationale else
                     _dimension_rationale(dimension.dimension_id, score, target))

        # Per-skill details under field_expertise
        skill_details: list[SkillScoreDetail] = []
        if dimension.dimension_id == "field_expertise":
            assessed = [s for s in state.skill_map.skills.values() if s.attempts > 0]
            total_importance = sum(s.importance for s in assessed) or 1.0
            for skill in sorted(state.skill_map.skills.values(), key=lambda s: (-s.importance, s.label)):
                gemini = skill_result.assessments.get(skill.skill_id)
                s4 = gemini.score_4 if gemini and gemini.score_4 > 0 else skill_scores_4.get(skill.skill_id, 0.0)
                skill_details.append(
                    SkillScoreDetail(
                        skill_id=skill.skill_id,
                        label=skill.label,
                        score_4=round(s4, 2),
                        score_label=score_label(round(s4, 2)),
                        target_4=target,
                        band=skill_band(s4, skill.attempts, state.role.seniority),
                        weight_in_dimension=round(skill.importance / total_importance, 2) if skill.attempts > 0 else 0.0,
                        evidence_ids=skill.evidence_ids,
                    )
                )

        items.append(
            ScoreCompositionItem(
                dimension=dimension.dimension_id,
                label=dimension.label,
                weight=dimension.weight,
                score_4=round(score, 2),
                target_4=target,
                points=round(points, 1),
                rationale=rationale,
                skill_details=skill_details,
            )
        )
    return items


def _build_competency_scorecard(
    state: InterviewState,
    dimension_scores: dict[str, float],
    evidence_by_id: dict[str, EvidenceRecord],
    dimension_result: DimensionScoringResult,
) -> list[CompetencyScorecardItem]:
    target = required_level_for_seniority(state.role.seniority)
    items = []
    for dimension in state.rubric.dimensions:
        evidence_ids = [
            r.evidence_id for r in evidence_by_id.values()
            if r.dimension == dimension.dimension_id
        ][:6]
        score = dimension_scores.get(dimension.dimension_id, 0.0)
        dim_score = dimension_result.scores.get(dimension.dimension_id)
        rationale = (dim_score.rationale if dim_score and dim_score.rationale else
                     _dimension_rationale(dimension.dimension_id, score, target))
        items.append(
            CompetencyScorecardItem(
                dimension=dimension.dimension_id,
                label=dimension.label,
                weight=dimension.weight,
                score_4=round(score, 2),
                target_4=target,
                band=score_band(score, target),
                rationale=rationale,
                evidence_ids=evidence_ids,
            )
        )
    return items


def _build_evidence_by_question(
    state: InterviewState,
    evidence_result: EvidenceAnalysisResult,
    seniority: str,
) -> list[EvidenceByQuestion]:
    # Index Gemini analyses by turn_index for enrichment
    gemini_by_turn = {a.turn_index: a for a in evidence_result.analyses}

    ranked_turns = sorted(
        state.turns,
        key=lambda turn: max((r.confidence for r in turn.evidence), default=0.0),
        reverse=True,
    )[:6]
    rows = []
    for turn in ranked_turns:
        analysis = turn.answer_analysis
        answer = turn.candidate_answer
        if analysis is None:
            continue
        gemini = gemini_by_turn.get(turn.turn_index)
        if gemini and gemini.quality_judgment:
            ai_judgement = gemini.quality_judgment
            s4 = gemini.score_4
            excerpt = "; ".join(gemini.key_quotes[:3]) if gemini.key_quotes else (
                (answer.transcript if answer and answer.transcript else analysis.summary)[:500]
            )
        else:
            ai_judgement = analysis.summary
            s4 = quality_score_4(analysis.quality)
            excerpt = (answer.transcript if answer and answer.transcript else analysis.summary)[:500]
        rows.append(
            EvidenceByQuestion(
                turn_id=turn.turn_id,
                turn_index=turn.turn_index,
                dimension=turn.evidence[0].dimension if turn.evidence else "field_expertise",
                skill_id=(gemini.skill_id if gemini and gemini.skill_id else analysis.target_skill_id),
                question=turn.question,
                answer_excerpt=excerpt,
                score_4=s4,
                score_label=score_label(s4),
                band=score_band(s4, required_level_for_seniority(seniority)),
                ai_judgement=ai_judgement,
                evidence_ids=[r.evidence_id for r in turn.evidence],
            )
        )
    return rows


def _build_ai_native_signals(state: InterviewState) -> list[AdvisorySignal]:
    strong = [r for r in state.evidence_ledger.records if r.signal_type == EvidenceSignalType.STRONG_EVIDENCE]
    concrete = [r for r in state.evidence_ledger.records if r.signal_type == EvidenceSignalType.CONCRETE_EXPERIENCE]
    partial = [r for r in state.evidence_ledger.records if r.signal_type == EvidenceSignalType.PARTIAL_UNDERSTANDING]

    def first(records: list, fb: str) -> str:
        return records[0].summary if records else fb

    return [
        AdvisorySignal(
            label="Reasoning quality",
            level=signal_level(len(strong) + len(concrete), len(state.turns)),
            summary=first(concrete or strong, "Look for concrete tradeoffs, measurements, and decision reasoning."),
            evidence_ids=[r.evidence_id for r in (concrete or strong)[:3]],
        ),
        AdvisorySignal(
            label="Coachability",
            level=signal_level(len(partial), max(len(state.turns), 1)),
            summary="Estimated from whether partial answers improved after scaffolding or follow-up.",
            evidence_ids=[r.evidence_id for r in partial[:3]],
        ),
        AdvisorySignal(
            label="Learning agility",
            level=signal_level(len(concrete), len(state.turns)),
            summary=first(concrete, "Look for examples where unfamiliar systems were learned and applied."),
            evidence_ids=[r.evidence_id for r in concrete[:3]],
        ),
    ]


def _build_worry_areas(
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


def _build_recommended_next_steps(
    worry_areas: list[ReportFinding],
    strengths: list[ReportFinding],
) -> list[ReportFinding]:
    steps = []
    if worry_areas:
        steps.append(ReportFinding(
            title="Probe the highest-risk area in the next round.",
            summary=worry_areas[0].summary,
            evidence_ids=worry_areas[0].evidence_ids,
        ))
    if strengths:
        steps.append(ReportFinding(
            title="Validate the strongest evidence with a deeper practical exercise.",
            summary=strengths[0].summary,
            evidence_ids=strengths[0].evidence_ids,
        ))
    steps.append(ReportFinding(
        title="Use a human review pass before final hiring action.",
        summary="The report links every recommendation to evidence, but final hiring decisions should remain human-reviewed.",
    ))
    return steps


def _build_tags(
    state: InterviewState,
    skill_role_match: list[SkillRoleMatchItem],
    strengths: list[ReportFinding],
) -> list[str]:
    tags = [state.role.seniority, state.role.title]
    tags.extend(item.label for item in skill_role_match if item.band in {"meets", "exceeds"})
    tags.extend(finding.title for finding in strengths[:2])
    return list(dict.fromkeys(tags))[:6]


def _verdict(*, fit_score: int, risks: list[ReportFinding], caveats: list[str]) -> str:
    if fit_score >= 75 and len(risks) <= 1 and not caveats:
        return "advance"
    if fit_score >= 60:
        return "hold"
    return "needs_review"


def _dimension_rationale(dimension: str, score: float, target: float) -> str:
    if score == 0:
        return "Not enough evidence was captured for this dimension."
    if score >= target:
        return "Meets or clears the role bar based on captured evidence."
    return "Below the role bar; should be probed in the next round."
