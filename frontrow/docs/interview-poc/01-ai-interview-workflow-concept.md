# AI Interview Workflow POC: Complete Concept and Architecture

## 1. Purpose

This document describes the complete conceptual architecture for a humane,
adaptive, AI-based interview system. The goal is to move away from robotic,
templated interview behavior and toward an interviewer that can:

- understand candidate answers with better fidelity,
- preserve interview context across a 20-30 minute session,
- ask thoughtful follow-up questions,
- adapt depth and direction based on candidate performance,
- align questions to the job description, resume, role seniority, and interview
  type,
- generate a final report grounded in evidence from the interview rather than
  vague summaries.

The proposed design borrows the workflow-orchestration idea from a Haystack-based
pipeline service, but adapts it to an interactive interview domain. The interview
should not be modeled as one static linear pipeline. It should be modeled as a
stateful interview session where each candidate response triggers a per-turn
pipeline that updates context, evaluates evidence, plans the next move, and
generates the next question.

## 2. Problem Statement

The existing AI interview system has several practical issues:

1. The interview feels robotic.
   The interviewer asks questions in a templated sequence and does not respond
   naturally to what the candidate just said.

2. Context is lost during the session.
   The system does not reliably remember what has already been asked, what the
   candidate answered well, what they avoided, or which topics need deeper
   probing.

3. Next-question generation is weak.
   The system may jump topics too abruptly, repeat itself, ask questions that do
   not match the candidate's background, or fail to drill down when a candidate
   makes an interesting claim.

4. Candidate answer interpretation has been unreliable.
   Previously, the system used text-to-text behavior based on transcripts. Since
   transcripts may lose nuance or contain errors, downstream analysis and final
   reports became vague or inaccurate.

5. Final reports lack evidence.
   A report is only useful if it points to specific observed signals: what the
   candidate said, how deeply they explained it, whether they needed hints, and
   whether they could apply the concept.

6. The system must support different interview categories.
   The same architecture should work for software engineering, healthcare
   assistant, operations, support, data, or other role types. It should be role
   agnostic at the orchestration layer and role specific through configuration,
   rubrics, resume data, JD data, and generated interview plans.

## 3. Audio Understanding Direction

The move to Gemini 2.5 Flash audio-to-text/audio understanding is a good
improvement for report quality. It reduces the loss that happens when the system
depends only on a brittle transcript.

However, better audio understanding alone does not solve the deeper interview
flow problem.

Audio model improvement helps with:

- more accurate candidate answer capture,
- better preservation of spoken content,
- better downstream evidence extraction,
- better final report grounding.

It does not automatically solve:

- what question should be asked next,
- when to give a candidate a second attempt,
- when to switch topics,
- when to drill down,
- how to avoid repeating covered topics,
- how to keep the interview humane,
- how to balance role coverage with conversational flow.

Those require explicit orchestration, state management, and strategy.

## 4. Core Architecture Principle

The main principle is:

> The interview is a long-running stateful session, but each candidate turn is a
> bounded workflow.

Do not build one monolithic workflow that tries to process the entire interview
from start to end.

Instead:

- the WebSocket/session manager owns the live interview loop,
- Redis owns active session state,
- Postgres owns durable session/report records,
- a per-turn pipeline processes each candidate answer,
- a separate initialization pipeline prepares the interview plan,
- a separate report pipeline generates the final evaluation.

This gives the system structure without making the interview rigid.

## 5. High-Level Runtime Shape

```text
---------------------+
| Scheduled/Instant   |
| Interview Created   |
+----------+----------+
           |
           v
+---------------------+
| Initialization      |
| Pipeline            |
| - JD/resume context |
| - role rubric       |
| - first question    |
| - skill map         |
+----------+----------+
           |
           v
+---------------------+
| Redis Session State |
+----------+----------+
           |
           v
+---------------------+       Candidate audio/answer
| WebSocket Interview | <--------------------------+
| Session Manager     |                            |
+----------+----------+                            |
           |                                       |
           v                                       |
+---------------------+                            |
| Per-Turn Pipeline   |                            |
| - answer analysis   |                            |
| - evidence extract  |                            |
| - state update      |                            |
| - next move plan    |                            |
| - next question     | ---------------------------+
+----------+----------+
           |
           v
+---------------------+
| Completion Trigger  |
| time/coverage/end   |
+----------+----------+
           |
           v
+---------------------+
| Report Pipeline     |
| - metrics           |
| - evidence          |
| - recommendation    |
+----------+----------+
           |
           v
+---------------------+
| Postgres Persistence|
+---------------------+
```

## 6. Why Per-Turn Pipelines Are Better Than One Long Pipeline

A 20-30 minute interview is interactive. The system cannot know the full path in
advance because the path depends on candidate responses.

One long static DAG would be a poor fit because:

- the number of turns is not fixed,
- the candidate may refuse, pause, ask for clarification, or give partial
  answers,
- topics may need to be revisited or skipped,
- time remaining affects priorities,
- the next question depends on fresh evidence,
- WebSocket interaction needs low-latency responses.

Per-turn pipelines are a better fit because:

- each turn is bounded and testable,
- state can be loaded from Redis at the start and saved at the end,
- failures can be isolated to one turn,
- every decision can be traced,
- latency can be managed,
- the final report has structured turn-by-turn evidence.

## 7. Human Interviewer Behavior to Model

The system should behave less like a quiz engine and more like a thoughtful
interviewer.

Human interviewers do not simply ask a question, grade it, and jump to the next
topic. They interpret the answer and decide the next move.

Example:

Candidate is asked: "What is the GIL in Python?"

Possible candidate response:

- strong answer: explains interpreter lock, bytecode execution, CPU-bound
  threading limits, multiprocessing alternatives.
- partial answer: says "it has something to do with threads" but cannot explain
  impact.
- weak answer: says "I am not sure."
- evasive answer: talks generally about Python but avoids the concept.

The next question should differ:

- For a strong answer: drill deeper or move to applied concurrency tradeoffs.
- For a partial answer: scaffold with a hint.
- For a weak answer: offer one simpler attempt if the role requires it.
- For an explicit "I do not know": acknowledge and move on.
- For an evasive answer: ask a concrete follow-up or mark low confidence.

This behavior can be encoded as strategy, not as hardcoded questions.

## 8. No Hardcoded Questions, But Structured Behavior

The requirement "no hardcoded questions" is reasonable. The system should not
depend on a static bank of questions stored in code or DB.

However, "no hardcoded questions" must not mean "no structure."

The system still needs stable behavior rules:

- do not repeat already-covered topics,
- ask at most one scaffolded retry after a weak answer unless the rubric says
  the skill is critical,
- acknowledge uncertainty without shaming the candidate,
- if candidate claims experience, validate with a concrete follow-up,
- if candidate gives a shallow answer, ask for an example,
- if time remaining is low, prioritize high-weight uncovered competencies,
- if candidate explicitly says they do not know, move on after a brief
  acknowledgement,
- do not over-drill low-priority topics,
- do not ask trivia unless the role demands it,
- keep questions role appropriate and seniority appropriate.

These are interviewer policies, not hardcoded questions.

## 9. The Interview Map

The user's 2D-grid idea can be formalized as an interview map.

The interview map is a dynamic graph of competencies, topics, and evidence
states. The interviewer navigates this graph during the interview.

Each node may represent:

- a skill,
- a domain,
- a behavioral competency,
- a resume claim,
- a JD requirement,
- a role-specific scenario,
- an experience area.

Example nodes for a backend engineer:

- Python fundamentals
- Python concurrency
- API design
- database modeling
- query performance
- debugging production issues
- system design
- testing
- ownership
- communication
- collaboration

Each node tracks:

- role importance,
- target depth,
- current evidence score,
- confidence in the score,
- attempts made,
- whether a scaffolded retry was used,
- whether the topic is exhausted,
- whether it was skipped,
- related resume claims,
- related JD requirements,
- last asked turn,
- candidate sentiment/comfort signal if available.

The next-question planner selects the next move through this map.

## 10. Interview Navigation Moves

A next-question planner should not directly generate a question first. It should
first decide the move.

Possible moves:

1. Open new topic.
   Use when a high-priority topic has not yet been covered.

2. Drill down.
   Use when the candidate gave a strong answer and the role requires depth.

3. Scaffold retry.
   Use when the answer was incomplete but the topic is important enough to give
   one more chance.

4. Ask for concrete example.
   Use when the candidate speaks abstractly or claims experience without proof.

5. Validate resume claim.
   Use when the resume says they used a skill but the interview has not yet
   confirmed it.

6. Switch adjacent topic.
   Use when the current topic is weak, exhausted, or no longer productive.

7. Move to behavioral.
   Use to assess ownership, conflict resolution, communication, ambiguity, or
   responsibility.

8. Close topic.
   Use when enough evidence has been collected.

9. Time-boxed coverage move.
   Use near the end to cover remaining high-weight dimensions.

10. Graceful wrap-up.
   Use when time is nearly done or required coverage is complete.

The actual question generator receives the planned move as input.

## 11. Core Data Model Concepts

The active session state should contain at least:

```json
{
  "session_id": "interview_123",
  "candidate_id": "candidate_456",
  "role_id": "backend_python_mid",
  "status": "running",
  "started_at": "...",
  "duration_minutes": 30,
  "time_remaining_seconds": 1200,
  "resume_summary": {},
  "job_description_summary": {},
  "interview_plan": {},
  "skill_map": {},
  "turns": [],
  "covered_topics": [],
  "open_threads": [],
  "evidence_ledger": [],
  "current_focus": {},
  "last_question": {},
  "last_answer": {},
  "finalization_flags": {}
}
```

The most important part is the evidence ledger. The report should not depend on
an LLM remembering the entire conversation. It should depend on structured
evidence accumulated turn by turn.

## 12. Evidence Ledger

Each answer should produce evidence records.

Example:

```json
{
  "turn_id": 7,
  "skill": "python_concurrency",
  "question": "What is the GIL in Python?",
  "candidate_answer_summary": "Candidate said it is related to threading but did not explain bytecode execution or CPU-bound limitations.",
  "observed_signals": [
    "recognized relationship to threading",
    "could not explain practical impact",
    "needed scaffold"
  ],
  "score_delta": -0.2,
  "confidence": 0.72,
  "depth": "shallow",
  "attempt_type": "first_attempt",
  "evidence_quote_or_audio_ref": "turn_7_segment_2",
  "rubric_dimension": "field_expertise"
}
```

This makes final reporting far more grounded.

## 13. Metrics and Report Dimensions

The top-level report dimensions are:

- field expertise,
- experience depth,
- communication,
- behavioral and ownership.

These should have role-dependent weights.

Example fresher role:

```json
{
  "field_expertise": 0.35,
  "experience_depth": 0.15,
  "communication": 0.30,
  "behavioral_ownership": 0.20
}
```

Example senior engineer role:

```json
{
  "field_expertise": 0.30,
  "experience_depth": 0.35,
  "communication": 0.15,
  "behavioral_ownership": 0.20
}
```

Each top-level dimension should have sub-dimensions.

Field expertise:

- fundamentals,
- applied problem solving,
- role-specific tools,
- correctness,
- tradeoff awareness.

Experience depth:

- real project ownership,
- production exposure,
- debugging depth,
- architecture judgment,
- ability to explain decisions.

Communication:

- clarity,
- structure,
- concision,
- ability to ask clarifying questions,
- ability to explain complex topics.

Behavioral and ownership:

- accountability,
- collaboration,
- ambiguity handling,
- learning mindset,
- conflict handling,
- initiative.

## 14. Report Generation Principle

The final report should be a separate pipeline. It should not simply summarize
the transcript. It should aggregate the evidence ledger.

Report pipeline inputs:

- session metadata,
- JD summary,
- resume summary,
- interview plan,
- full turn history,
- evidence ledger,
- skill map final state,
- audio/transcript references,
- rubric weights.

Report pipeline outputs:

- final recommendation,
- score by top-level dimension,
- score by sub-dimension,
- evidence-backed strengths,
- evidence-backed risks,
- role fit summary,
- question-by-question evaluation,
- possible interviewer notes,
- confidence level,
- caveats.

## 15. Suggested System Boundaries

The interview system should separate:

- live WebSocket session management,
- orchestration pipelines,
- model providers,
- Redis state management,
- Postgres persistence,
- report generation,
- admin/interview configuration,
- observability and tracing.

This keeps the system extensible. Gemini can be swapped or supplemented later
without rewriting interview strategy.

## 16. What Success Looks Like

The POC should prove:

1. The system asks a better second question after a weak or partial answer.
2. The system remembers what was already covered.
3. The system adapts to resume/JD context.
4. The system can choose between drill-down, scaffold, switch-topic, and close-topic.
5. The system can produce a final report grounded in turn-level evidence.
6. The system supports at least two different roles without hardcoded questions.
7. The architecture is observable enough to debug why a question was asked.

## 17. Minimal POC Scope

The first POC does not need a complete production-grade interview platform.

Recommended POC scope:

- one FastAPI endpoint or WebSocket simulation,
- Redis-like in-memory or actual Redis session state,
- one initialization pipeline,
- one per-turn pipeline,
- one report pipeline,
- two role configurations,
- simulated audio-analysis input or Gemini integration if already available,
- Postgres persistence optional for POC but recommended if easy,
- full logging of next-question decisions.

The POC should focus on decision quality, not UI polish.

