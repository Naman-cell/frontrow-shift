from report_engine.models import InterviewReport, ReportEngineConfig, ReportInput
from report_engine.pipeline import ReportGenerationInput, ReportGenerationPipeline
from report_engine.scoring_service import GeminiReportScoringService, HeuristicReportScoringService
from report_engine.state_builder import build_state


async def generate_report(
    report_input: ReportInput,
    config: ReportEngineConfig | None = None,
) -> InterviewReport:
    """Generate an interview report from SkillBrew's input format.

    Usage:
        report = await generate_report(ReportInput(
            job_title="Backend Engineer",
            seniority="Mid",
            required_skills=["Python", "SQL", "System Design"],
            turns=[
                TurnInput(question_text="Tell me about...", answer_text="I built..."),
            ],
        ))
    """
    config = config or ReportEngineConfig()

    # Create audio analyzer if Gemini is configured
    audio_analyzer = None
    if config.use_gemini and config.gemini_api_key:
        from report_engine.audio_analyzer import GeminiAudioAnalyzer

        audio_analyzer = GeminiAudioAnalyzer(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
        )

    # Build internal state (with Gemini audio analysis if available)
    state = await build_state(report_input, audio_analyzer=audio_analyzer)

    # Create scoring service
    if config.use_gemini and config.gemini_api_key:
        scoring_service = GeminiReportScoringService(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
        )
    else:
        scoring_service = HeuristicReportScoringService()

    # Run pipeline
    pipeline = ReportGenerationPipeline(report_scoring_service=scoring_service)
    result = await pipeline.run(ReportGenerationInput(state=state))

    return result.report
