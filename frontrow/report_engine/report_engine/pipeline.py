import os

from pydantic import BaseModel

os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "false")

from haystack import AsyncPipeline

from report_engine.models import InterviewReport, InterviewState
from report_engine.components import (
    GeminiDimensionScorerNode,
    GeminiEvidenceAnalyzerNode,
    GeminiSkillAssessorNode,
    ReportAssemblerNode,
    TranscriptCompilerNode,
)
from report_engine.scoring_service import (
    HeuristicReportScoringService,
    ReportScoringService,
)


class ReportGenerationInput(BaseModel):
    state: InterviewState


class ReportGenerationOutput(BaseModel):
    report: InterviewReport


class ReportGenerationPipeline:
    """Haystack-backed report generation pipeline.

    Fan-out architecture: TranscriptCompiler feeds three parallel Gemini
    nodes (dimension scorer, skill assessor, evidence analyzer), whose
    results merge in the ReportAssembler.
    """

    def __init__(
        self,
        report_scoring_service: ReportScoringService | None = None,
    ) -> None:
        self.service = report_scoring_service or HeuristicReportScoringService()
        self.pipeline = self._build_pipeline()

    def _build_pipeline(self) -> AsyncPipeline:
        pipeline = AsyncPipeline()
        pipeline.add_component("transcript_compiler", TranscriptCompilerNode())
        pipeline.add_component("dimension_scorer", GeminiDimensionScorerNode(service=self.service))
        pipeline.add_component("skill_assessor", GeminiSkillAssessorNode(service=self.service))
        pipeline.add_component("evidence_analyzer", GeminiEvidenceAnalyzerNode(service=self.service))
        pipeline.add_component("report_assembler", ReportAssemblerNode())

        # Fan-out: compiler → three parallel Gemini nodes
        pipeline.connect("transcript_compiler.state", "dimension_scorer.state")
        pipeline.connect("transcript_compiler.skill_scores_4", "dimension_scorer.skill_scores_4")

        pipeline.connect("transcript_compiler.state", "skill_assessor.state")

        pipeline.connect("transcript_compiler.state", "evidence_analyzer.state")

        # Fan-in: all results → assembler
        pipeline.connect("transcript_compiler.state", "report_assembler.state")
        pipeline.connect("transcript_compiler.skill_scores_4", "report_assembler.skill_scores_4")
        pipeline.connect("dimension_scorer.dimension_result", "report_assembler.dimension_result")
        pipeline.connect("skill_assessor.skill_result", "report_assembler.skill_result")
        pipeline.connect("evidence_analyzer.evidence_result", "report_assembler.evidence_result")

        return pipeline

    async def run(self, payload: ReportGenerationInput) -> ReportGenerationOutput:
        result = await self.pipeline.run_async(
            data={"transcript_compiler": {"state": payload.state}},
            include_outputs_from={"report_assembler"},
        )
        return ReportGenerationOutput(report=result["report_assembler"]["report"])
