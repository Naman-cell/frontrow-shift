"""Report scoring service abstraction.

Provides both heuristic (keyword-based) and Gemini-backed scoring
for interview report generation.
"""

import json
import logging
from asyncio import Semaphore
from typing import Any

from pydantic import BaseModel, Field

from app.models.state import InterviewState
from app.pipelines.report_generation.heuristics import (
    dimension_scores_4,
    quality_score_4,
)

LOGGER = logging.getLogger(__name__)


# ── Result models ────────────────────────────────────────────────────


class DimensionScore(BaseModel):
    dimension_id: str
    score_4: float
    rationale: str
    cited_statements: list[str] = Field(default_factory=list)


class DimensionScoringResult(BaseModel):
    scores: dict[str, DimensionScore] = Field(default_factory=dict)
    overall_rationale: str = ""


class SkillAssessment(BaseModel):
    skill_id: str
    label: str
    score_4: float
    level_description: str = ""
    rationale: str = ""
    cited_evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class SkillAssessmentResult(BaseModel):
    assessments: dict[str, SkillAssessment] = Field(default_factory=dict)


class TurnEvidenceAnalysis(BaseModel):
    turn_index: int
    key_quotes: list[str] = Field(default_factory=list)
    quality_judgment: str = ""
    score_4: float = 2.0
    dimension: str = "field_expertise"
    skill_id: str = ""


class EvidenceAnalysisResult(BaseModel):
    analyses: list[TurnEvidenceAnalysis] = Field(default_factory=list)


# ── Base service ─────────────────────────────────────────────────────


class ReportScoringService:
    async def score_dimensions(
        self,
        state: InterviewState,
        skill_scores_4: dict[str, float],
    ) -> DimensionScoringResult:
        raise NotImplementedError

    async def assess_skills(
        self,
        state: InterviewState,
    ) -> SkillAssessmentResult:
        raise NotImplementedError

    async def analyze_evidence(
        self,
        state: InterviewState,
    ) -> EvidenceAnalysisResult:
        raise NotImplementedError


# ── Heuristic implementation (fallback) ──────────────────────────────


class HeuristicReportScoringService(ReportScoringService):
    async def score_dimensions(
        self,
        state: InterviewState,
        skill_scores_4: dict[str, float],
    ) -> DimensionScoringResult:
        scores = dimension_scores_4(state, skill_scores_4)
        return DimensionScoringResult(
            scores={
                dim_id: DimensionScore(
                    dimension_id=dim_id,
                    score_4=score,
                    rationale="",
                )
                for dim_id, score in scores.items()
            },
            overall_rationale="",
        )

    async def assess_skills(
        self,
        state: InterviewState,
    ) -> SkillAssessmentResult:
        return SkillAssessmentResult(assessments={})

    async def analyze_evidence(
        self,
        state: InterviewState,
    ) -> EvidenceAnalysisResult:
        analyses = []
        for turn in state.turns:
            if turn.answer_analysis is None:
                continue
            analyses.append(
                TurnEvidenceAnalysis(
                    turn_index=turn.turn_index,
                    quality_judgment=turn.answer_analysis.summary,
                    score_4=quality_score_4(turn.answer_analysis.quality),
                    dimension=turn.evidence[0].dimension if turn.evidence else "field_expertise",
                    skill_id=turn.answer_analysis.target_skill_id,
                )
            )
        return EvidenceAnalysisResult(analyses=analyses)


# ── Gemini implementation ────────────────────────────────────────────


class GeminiReportScoringService(ReportScoringService):
    def __init__(self, *, api_key: str, model: str) -> None:
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.semaphore = Semaphore(4)
        self._heuristic_fallback = HeuristicReportScoringService()

    async def score_dimensions(
        self,
        state: InterviewState,
        skill_scores_4: dict[str, float],
    ) -> DimensionScoringResult:
        prompt = _dimension_scoring_prompt(state)
        try:
            parsed = await self._call_gemini(prompt)
            dimensions = parsed.get("dimensions", {})
            scores = {}
            for dim_id in ["field_expertise", "experience_depth", "communication", "behavioral_ownership"]:
                dim_data = dimensions.get(dim_id, {})
                scores[dim_id] = DimensionScore(
                    dimension_id=dim_id,
                    score_4=max(1.0, min(4.0, float(dim_data.get("score_4", 2.0)))),
                    rationale=dim_data.get("rationale", ""),
                    cited_statements=_coerce_str_list(dim_data.get("cited_statements")),
                )
            return DimensionScoringResult(
                scores=scores,
                overall_rationale=parsed.get("overall_rationale", ""),
            )
        except Exception:
            LOGGER.exception("Gemini dimension scoring failed; using heuristic fallback.")
            return await self._heuristic_fallback.score_dimensions(state, skill_scores_4)

    async def assess_skills(
        self,
        state: InterviewState,
    ) -> SkillAssessmentResult:
        prompt = _skill_assessment_prompt(state)
        try:
            parsed = await self._call_gemini(prompt)
            assessments = {}
            for skill_id, data in parsed.get("assessments", {}).items():
                assessments[skill_id] = SkillAssessment(
                    skill_id=skill_id,
                    label=data.get("label", skill_id),
                    score_4=max(1.0, min(4.0, float(data.get("score_4", 2.0)))),
                    level_description=data.get("level_description", ""),
                    rationale=data.get("rationale", ""),
                    cited_evidence=_coerce_str_list(data.get("cited_evidence")),
                    confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                )
            return SkillAssessmentResult(assessments=assessments)
        except Exception:
            LOGGER.exception("Gemini skill assessment failed; using heuristic fallback.")
            return await self._heuristic_fallback.assess_skills(state)

    async def analyze_evidence(
        self,
        state: InterviewState,
    ) -> EvidenceAnalysisResult:
        prompt = _evidence_analysis_prompt(state)
        try:
            parsed = await self._call_gemini(prompt)
            analyses = []
            for item in parsed.get("analyses", []):
                analyses.append(
                    TurnEvidenceAnalysis(
                        turn_index=int(item.get("turn_index", 0)),
                        key_quotes=_coerce_str_list(item.get("key_quotes")),
                        quality_judgment=item.get("quality_judgment", ""),
                        score_4=max(1.0, min(4.0, float(item.get("score_4", 2.0)))),
                        dimension=item.get("dimension", "field_expertise"),
                        skill_id=item.get("skill_id", ""),
                    )
                )
            return EvidenceAnalysisResult(analyses=analyses)
        except Exception:
            LOGGER.exception("Gemini evidence analysis failed; using heuristic fallback.")
            return await self._heuristic_fallback.analyze_evidence(state)

    async def _call_gemini(self, prompt: str) -> dict[str, Any]:
        async with self.semaphore:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        return _parse_json_response(getattr(response, "text", "") or "")


# ── Prompts ──────────────────────────────────────────────────────────


def _compile_transcript(state: InterviewState) -> str:
    lines = []
    for turn in state.turns:
        transcript = ""
        if turn.candidate_answer:
            transcript = turn.candidate_answer.transcript
        summary = ""
        if turn.answer_analysis:
            summary = turn.answer_analysis.summary
        lines.append(
            f"Q{turn.turn_index} [{turn.answer_analysis.target_skill_label if turn.answer_analysis else '?'}]: "
            f"{turn.question}\n"
            f"A: {transcript}\n"
            f"(Analysis: {summary})"
        )
    return "\n\n".join(lines)


def _dimension_scoring_prompt(state: InterviewState) -> str:
    transcript = _compile_transcript(state)
    skills = ", ".join(state.role.required_skills)
    return f"""
You are scoring a hiring interview for a {state.role.title} ({state.role.seniority} level).

Score the candidate across exactly 4 dimensions on a 1.0-4.0 scale.
For each dimension, you MUST cite at least one specific candidate statement in quotes.

Dimensions:
1. field_expertise — Does the candidate demonstrate knowledge of the required skills?
2. experience_depth — Does the candidate provide concrete, detailed, real-world examples?
3. communication — Are the answers clear, structured, and appropriately detailed?
4. behavioral_ownership — Does the candidate show ownership, initiative, and accountability?

Scoring guide:
- 4.0: Exceptional, exceeds expectations for seniority level
- 3.0: Solid, meets expectations with concrete evidence
- 2.0: Partial, shows some knowledge but gaps remain
- 1.0: Insufficient, refusal, or no usable evidence

Required skills: {skills}
Role: {state.role.title} ({state.role.seniority})
JD: {state.role.job_description_summary}
Resume: {state.role.resume_summary}

Full interview transcript:
{transcript}

Return only valid JSON:
{{
  "dimensions": {{
    "field_expertise": {{
      "score_4": <float>,
      "rationale": "<why this score, referencing specific answers>",
      "cited_statements": ["<exact candidate quote 1>", "<exact candidate quote 2>"]
    }},
    "experience_depth": {{ ... }},
    "communication": {{ ... }},
    "behavioral_ownership": {{ ... }}
  }},
  "overall_rationale": "<2-3 sentence summary of the candidate's performance>"
}}
""".strip()


def _skill_assessment_prompt(state: InterviewState) -> str:
    transcript = _compile_transcript(state)
    skill_lines = "\n".join(
        f"- {skill.skill_id}: {skill.label} (importance: {skill.importance:.2f}, attempts: {skill.attempts})"
        for skill in state.skill_map.skills.values()
        if skill.skill_id not in {"candidate_questions", "role_fit"}
    )
    return f"""
You are assessing individual skills from a hiring interview for a {state.role.title} ({state.role.seniority}).

For each skill below, score the candidate 1.0-4.0 based on the interview evidence.
If a skill was not assessed (zero relevant turns), score 0.0 and say "not assessed".
Cite specific candidate statements for each assessed skill.

Skills to assess:
{skill_lines}

Scoring guide:
- 4.0: Deep expertise with concrete evidence of ownership and outcomes
- 3.0: Solid knowledge with at least one real-world example
- 2.0: Surface-level knowledge, no concrete examples
- 1.0: Could not demonstrate this skill / refused to answer

Full interview transcript:
{transcript}

Return only valid JSON:
{{
  "assessments": {{
    "<skill_id>": {{
      "label": "<skill label>",
      "score_4": <float>,
      "level_description": "<one sentence describing the candidate's level>",
      "rationale": "<why this score>",
      "cited_evidence": ["<exact candidate quote>"],
      "confidence": <float 0-1>
    }}
  }}
}}
""".strip()


def _evidence_analysis_prompt(state: InterviewState) -> str:
    transcript = _compile_transcript(state)
    return f"""
You are analyzing evidence quality from each turn of a hiring interview.

For each question-answer turn, extract:
- The most important candidate quotes (exact words)
- A quality judgment explaining what the answer demonstrates or fails to demonstrate
- A score 1.0-4.0 for evidence quality
- Which rubric dimension this turn primarily informs
- Which skill was being assessed

Full interview transcript:
{transcript}

Return only valid JSON:
{{
  "analyses": [
    {{
      "turn_index": <int>,
      "key_quotes": ["<exact candidate quote>"],
      "quality_judgment": "<what this answer demonstrates or fails to demonstrate>",
      "score_4": <float>,
      "dimension": "<field_expertise|experience_depth|communication|behavioral_ownership>",
      "skill_id": "<skill being assessed>"
    }}
  ]
}}
""".strip()


# ── Helpers ──────────────────────────────────────────────────────────


def _parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []
