import os

from pydantic import BaseModel

os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "false")

from haystack import AsyncPipeline

from app.models.evidence import EvidenceRecord
from app.models.next_move import NextMoveDecision
from app.models.state import InterviewState
from app.models.turn import CandidateAnswer, InterviewTurn
from app.pipelines.turn_processing.components import (
    AnswerUnderstandingNode,
    EvidenceExtractorNode,
    NextMovePlannerNode,
    QuestionGeneratorNode,
    SkillStateUpdaterNode,
    TargetSkillSelector,
    TurnAggregatorNode,
)
from app.pipelines.turn_processing.processors.next_move_planning import NextMovePlanner
from app.services.audio_understanding_service import (
    AudioUnderstandingService,
    MockAudioUnderstandingService,
)


class TurnProcessingInput(BaseModel):
    state: InterviewState
    answer: CandidateAnswer


class TurnProcessingOutput(BaseModel):
    state: InterviewState
    turn: InterviewTurn
    next_move: NextMoveDecision
    next_question: str
    evidence_created: list[EvidenceRecord]


class TurnProcessingPipeline:
    """Haystack-backed workflow for one candidate answer turn.

    The WebSocket/session manager owns live session mechanics. This bounded
    pipeline owns the interview intelligence for a single answer:
    target skill selection, answer understanding, evidence extraction,
    skill-state update, next-move planning, question generation, and turn
    aggregation.
    """

    def __init__(
        self,
        audio_understanding_service: AudioUnderstandingService | None = None,
        next_move_planner: NextMovePlanner | None = None,
    ) -> None:
        self.audio_understanding_service = (
            audio_understanding_service or MockAudioUnderstandingService()
        )
        self.next_move_planner = next_move_planner or NextMovePlanner()
        self.pipeline = self._build_pipeline()

    def _build_pipeline(self) -> AsyncPipeline:
        pipeline = AsyncPipeline()
        pipeline.add_component("target_skill_selector", TargetSkillSelector())
        pipeline.add_component(
            "answer_understanding",
            AnswerUnderstandingNode(service=self.audio_understanding_service),
        )
        pipeline.add_component("evidence_extractor", EvidenceExtractorNode())
        pipeline.add_component("skill_state_updater", SkillStateUpdaterNode())
        pipeline.add_component(
            "next_move_planner",
            NextMovePlannerNode(planner=self.next_move_planner),
        )
        pipeline.add_component(
            "question_generator",
            QuestionGeneratorNode(service=self.audio_understanding_service),
        )
        pipeline.add_component("turn_aggregator", TurnAggregatorNode())

        pipeline.connect("target_skill_selector.state", "answer_understanding.state")
        pipeline.connect(
            "target_skill_selector.target_skill_id",
            "answer_understanding.target_skill_id",
        )
        pipeline.connect(
            "target_skill_selector.target_skill_label",
            "answer_understanding.target_skill_label",
        )

        pipeline.connect("answer_understanding.state", "evidence_extractor.state")
        pipeline.connect("answer_understanding.answer", "evidence_extractor.answer")
        pipeline.connect("answer_understanding.analysis", "evidence_extractor.analysis")

        pipeline.connect("evidence_extractor.state", "skill_state_updater.state")
        pipeline.connect("evidence_extractor.answer", "skill_state_updater.answer")
        pipeline.connect("evidence_extractor.analysis", "skill_state_updater.analysis")
        pipeline.connect("evidence_extractor.evidence", "skill_state_updater.evidence")

        pipeline.connect("skill_state_updater.state", "next_move_planner.state")
        pipeline.connect("skill_state_updater.answer", "next_move_planner.answer")
        pipeline.connect("skill_state_updater.analysis", "next_move_planner.analysis")
        pipeline.connect("skill_state_updater.evidence", "next_move_planner.evidence")

        pipeline.connect("next_move_planner.state", "question_generator.state")
        pipeline.connect("next_move_planner.answer", "question_generator.answer")
        pipeline.connect("next_move_planner.analysis", "question_generator.analysis")
        pipeline.connect("next_move_planner.evidence", "question_generator.evidence")
        pipeline.connect("next_move_planner.next_move", "question_generator.next_move")

        pipeline.connect("question_generator.state", "turn_aggregator.state")
        pipeline.connect("question_generator.answer", "turn_aggregator.answer")
        pipeline.connect("question_generator.analysis", "turn_aggregator.analysis")
        pipeline.connect("question_generator.evidence", "turn_aggregator.evidence")
        pipeline.connect("question_generator.next_move", "turn_aggregator.next_move")
        pipeline.connect(
            "question_generator.next_question",
            "turn_aggregator.next_question",
        )
        return pipeline

    async def run(self, payload: TurnProcessingInput) -> TurnProcessingOutput:
        result = await self.pipeline.run_async(
            data={
                "target_skill_selector": {"state": payload.state},
                "answer_understanding": {"answer": payload.answer},
            },
            include_outputs_from={"turn_aggregator"},
        )
        output = result["turn_aggregator"]
        return TurnProcessingOutput.model_validate(output)
