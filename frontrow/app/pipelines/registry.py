from collections.abc import Callable
from typing import Any

PipelineFactory = Callable[[], Any]

_factories: dict[str, PipelineFactory] = {}
_cache: dict[str, Any] = {}


def register_pipeline(name: str, factory: PipelineFactory) -> None:
    if name in _factories:
        raise RuntimeError(f"Pipeline already registered: {name}")
    _factories[name] = factory


async def get_pipeline(name: str) -> Any:
    if name not in _factories:
        raise KeyError(f"Unknown pipeline: {name}")
    if name not in _cache:
        _cache[name] = _factories[name]()
    return _cache[name]


def clear_pipeline_registry() -> None:
    _factories.clear()
    _cache.clear()


def register_default_pipelines() -> None:
    from app.pipelines.initialization.pipeline import InterviewInitializationPipeline
    from app.pipelines.report_generation.pipeline import ReportGenerationPipeline
    from app.pipelines.turn_processing.pipeline import TurnProcessingPipeline

    register_pipeline("interview_initialization", InterviewInitializationPipeline)
    register_pipeline("interview_turn_processing", TurnProcessingPipeline)
    register_pipeline("interview_report_generation", ReportGenerationPipeline)
