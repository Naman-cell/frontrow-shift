"""Example: generate a report using the report engine.

Usage:
    cd report_engine
    pip install -e .
    python examples/generate_report.py
"""
import asyncio

from report_engine import ReportEngineConfig, ReportInput, generate_report
from report_engine.models import TurnInput


async def main():
    report_input = ReportInput(
        job_title="Backend Engineer",
        seniority="Mid",
        industry="Technology",
        job_description="Build and maintain scalable backend services",
        resume_json={
            "summary": "5 years backend experience with Python and Go",
            "skills": ["Python", "Go", "PostgreSQL", "Redis", "Docker"],
        },
        required_skills=["Python", "SQL", "System Design", "API Development"],
        turns=[
            TurnInput(
                question_text="Tell me about your experience with Python.",
                answer_text="I have 5 years of Python experience. I built a high-throughput data pipeline using asyncio that processes 50k events per second. I owned the architecture decisions and measured the performance improvements.",
            ),
            TurnInput(
                question_text="How do you handle database optimization?",
                answer_text="At my last role I led a database optimization project. We identified slow queries using pg_stat_statements, added strategic indexes, and implemented connection pooling with PgBouncer. This reduced p95 query latency from 200ms to 15ms.",
            ),
            TurnInput(
                question_text="Walk me through a system you designed.",
                answer_text="I designed an event-driven order processing system. It used Kafka for event streaming, PostgreSQL for persistence, and Redis for caching. I handled the trade-off between consistency and availability by implementing saga patterns for distributed transactions.",
            ),
        ],
    )

    # Heuristic mode (no API key needed)
    config = ReportEngineConfig(use_gemini=False)
    report = await generate_report(report_input, config)

    print(f"Interview: {report.interview_id}")
    print(f"Fit Score: {report.fit_score}/100 (bar: {report.role_bar})")
    print(f"Verdict: {report.verdict}")
    print(f"Rationale: {report.rationale}")
    print()
    print("Score Composition:")
    for item in report.score_composition:
        print(f"  {item.label}: {item.score_4}/4.0 ({item.points:.1f} pts, weight={item.weight})")
    print()
    print("Skill-Role Match:")
    for item in report.skill_role_match:
        level = f"{item.candidate_level_4}/4.0" if item.candidate_level_4 is not None else "N/A"
        print(f"  {item.label}: {level} [{item.band}]")
    print()
    print("Evidence by Question:")
    for ebq in report.evidence_by_question:
        print(f"  Q{ebq.turn_index}: {ebq.question[:60]}...")
        print(f"    Score: {ebq.score_4}/4.0 [{ebq.score_label}] - {ebq.ai_judgement[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
