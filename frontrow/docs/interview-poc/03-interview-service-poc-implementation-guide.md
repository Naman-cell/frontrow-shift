# Interview Service POC Implementation Guide

## 1. Purpose

This document is the concrete end-to-end guide for building a POC of the AI
interview service.

It uses the concept described in:

```text
docs/interview-poc/01-ai-interview-workflow-concept.md
```

and the platform reference described in:

```text
docs/interview-poc/02-platform-service-ai-workflow-reference.md
```

The goal is to build a system that can conduct a more humane, adaptive,
context-aware AI interview using:

- Python,
- FastAPI,
- WebSocket,
- Postgres,
- Redis,
- Gemini 2.5 Flash audio understanding,
- Haystack-style workflow orchestration.

## 2. POC Outcome

The POC should demonstrate:

1. An interview can be initialized from resume and job description.
2. A first question can be generated before the WebSocket session begins.
3. Candidate answers can be processed turn by turn.
4. The system can update interview state after each answer.
5. The system can choose whether to drill down, scaffold, switch topic, or wrap up.
6. The system can generate a natural next question.
7. The system avoids repeating already-covered topics.
8. The system produces an evidence-backed final report.
9. The same architecture works for at least two different role types.

## 3. Recommended Service Boundary

Create one backend service responsible for the live interview orchestration.

Suggested service name:

```text
service-ai-interview
```

Responsibilities:

- interview initialization,
- WebSocket interview session,
- Redis session state,
- per-turn pipeline execution,
- report generation,
- Postgres persistence,
- observability.

Out of scope for this service:

- resume parsing internals,
- JD creation UI,
- candidate scheduling UI,
- authentication implementation details,
- model provider implementation internals beyond client interfaces.

## 4. Proposed Directory Structure

```text
service-ai-interview/
  app/
    main.py
    api/
      v1/
        endpoints/
          interviews.py
          websocket.py
          reports.py
          health.py
    core/
      config.py
      dependencies.py
    models/
      interview.py
      turn.py
      rubric.py
      report.py
      state.py
    pipelines/
      registry.py
      initialization/
        pipeline.py
        components.py
        prompts.py
      turn_processing/
        pipeline.py
        components.py
        prompts.py
      context_provider/
        pipeline.py
        components.py
      question_generation/
        pipeline.py
        components.py
        prompts.py
      report_generation/
        pipeline.py
        components.py
        prompts.py
    services/
      gemini_audio_client.py
      resume_client.py
      jd_client.py
      redis_session_store.py
      postgres_repository.py
      websocket_manager.py
    observability/
      interview_tracer.py
      execution_lifecycle.py
      step_recorder.py
    runtime/
      background_tasks.py
      redis_runtime.py
      postgres_runtime.py
    utils/
      time.py
      ids.py
      json.py
  tests/
```

## 5. Main Runtime Components

### 5.1 FastAPI App

The app exposes:

```text
POST /api/v1/interviews
POST /api/v1/interviews/{interview_id}/start
WS   /api/v1/interviews/{interview_id}/ws
POST /api/v1/interviews/{interview_id}/complete
GET  /api/v1/interviews/{interview_id}/report
GET  /health
```

The exact API can vary, but the POC should clearly separate:

- session creation,
- session initialization,
- live WebSocket turn processing,
- completion/report generation.

### 5.2 Redis

Redis stores active interview session state.

Suggested keys:

```text
interview:session:{interview_id}
interview:turns:{interview_id}
interview:lock:{interview_id}
interview:ws:{interview_id}
interview:steps-buffer:{interview_id}
```

Redis state should be flushed or archived after completion, once data is safely
persisted in Postgres.

### 5.3 Postgres

Postgres stores durable data:

- interview sessions,
- candidates,
- roles,
- generated interview plans,
- turns,
- evidence records,
- final reports,
- execution steps if not using a separate observability store.

### 5.4 Gemini Audio Client

Gemini 2.5 Flash audio should be wrapped behind a service interface:

```python
class AudioUnderstandingClient:
    async def analyze_answer_audio(
        self,
        audio_bytes: bytes,
        *,
        question: str,
        interview_context: dict,
    ) -> AudioUnderstandingResult:
        ...
```

Do not call the provider directly from pipeline components everywhere. Keep a
single client abstraction so the provider can be replaced or tuned.

## 6. Data Models

### 6.1 InterviewSession

```json
{
  "interview_id": "int_123",
  "tenant_id": "tenant_abc",
  "candidate_id": "cand_456",
  "role_id": "role_backend_mid",
  "status": "initialized",
  "interview_type": "technical",
  "duration_minutes": 30,
  "created_at": "...",
  "started_at": null,
  "completed_at": null
}
```

### 6.2 InterviewState

Stored in Redis during the live session.

```json
{
  "interview_id": "int_123",
  "status": "running",
  "turn_index": 4,
  "duration_minutes": 30,
  "started_at": "...",
  "time_remaining_seconds": 1420,
  "resume_summary": {},
  "job_description_summary": {},
  "interview_plan": {},
  "rubric": {},
  "skill_map": {},
  "conversation_summary": "Candidate has discussed Python API work and one deployment project.",
  "turns": [],
  "evidence_ledger": [],
  "covered_topics": [],
  "open_threads": [],
  "last_question": {},
  "last_answer": {},
  "next_question": {},
  "completion": {
    "required_coverage_met": false,
    "ready_to_wrap": false
  }
}
```

### 6.3 SkillNode

```json
{
  "skill_id": "python_concurrency",
  "label": "Python concurrency",
  "dimension": "field_expertise",
  "importance": 0.8,
  "target_depth": "medium",
  "current_score": 0.45,
  "confidence": 0.62,
  "attempts": 1,
  "scaffold_attempts": 0,
  "status": "in_progress",
  "evidence_ids": ["ev_001"],
  "related_resume_claims": [],
  "related_jd_requirements": []
}
```

### 6.4 InterviewTurn

```json
{
  "turn_id": "turn_005",
  "interview_id": "int_123",
  "turn_index": 5,
  "question": "Can you explain how Python threads behave for CPU-bound work?",
  "question_strategy": {
    "target_skill": "python_concurrency",
    "move_type": "scaffold_retry",
    "difficulty": "medium",
    "reason": "Candidate gave partial GIL answer."
  },
  "candidate_answer": {
    "audio_ref": "s3://...",
    "transcript": "...",
    "analysis_summary": "...",
    "confidence": 0.84
  },
  "created_at": "...",
  "answered_at": "..."
}
```

### 6.5 EvidenceRecord

```json
{
  "evidence_id": "ev_017",
  "interview_id": "int_123",
  "turn_id": "turn_005",
  "skill_id": "python_concurrency",
  "dimension": "field_expertise",
  "signal_type": "partial_understanding",
  "summary": "Candidate associated GIL with threads but did not explain bytecode execution or CPU-bound limitations.",
  "score_delta": -0.1,
  "confidence": 0.77,
  "quote_or_audio_ref": "turn_005_segment_1",
  "created_at": "..."
}
```

## 7. Pipeline Registry

Implement a small pipeline registry similar to the platform service.

```python
PipelineFactory = Callable[[], object]

_factories: dict[str, PipelineFactory] = {}
_cache: dict[str, object] = {}

def register_pipeline(name: str, factory: PipelineFactory) -> None:
    if name in _factories:
        raise RuntimeError(f"Pipeline already registered: {name}")
    _factories[name] = factory

async def get_pipeline(name: str) -> object:
    if name not in _factories:
        raise KeyError(f"Unknown pipeline: {name}")
    if name not in _cache:
        _cache[name] = _factories[name]()
    return _cache[name]
```

Recommended registered pipelines:

```text
interview_initialization
interview_turn_processing
interview_report_generation
```

Optional internal pipelines:

```text
answer_understanding
context_provider
next_question_generation
```

## 8. Initialization Pipeline

### 8.1 Purpose

Runs before the live interview begins.

It creates:

- role-aware interview plan,
- initial skill map,
- rubric weights,
- first question,
- Redis session seed.

### 8.2 Inputs

```json
{
  "interview_id": "int_123",
  "candidate_id": "cand_456",
  "role_id": "role_backend_mid",
  "resume_parse_result": {},
  "job_description": {},
  "interview_type": "technical",
  "duration_minutes": 30
}
```

### 8.3 Haystack Graph

```text
resume_context_formatter
  -> jd_context_formatter
  -> role_rubric_builder
  -> skill_map_builder
  -> opening_question_generator
  -> initialization_result_aggregator
  -> redis_session_initializer
```

### 8.4 Output

```json
{
  "interview_id": "int_123",
  "first_question": "Hi, good to meet you. Could you briefly walk me through your Python backend experience and the kind of systems you worked on?",
  "skill_map": {},
  "rubric": {},
  "status": "initialized"
}
```

### 8.5 First Question Rules

The first question can be structured but should be generated from context.

For fresher:

```text
Can you tell me a little about yourself and what kind of work or projects made
you interested in this role?
```

For experienced candidate:

```text
Hi, good to meet you. Could you walk me through the most relevant experience
from your background for this role?
```

Do not hardcode exact questions as the only allowed options. Use them as
behavioral templates in prompt guidance.

## 9. WebSocket Session Flow

### 9.1 Connection

When the WebSocket connects:

1. Load `InterviewState` from Redis.
2. Validate status is `initialized` or `running`.
3. Send the first/prepared question if it has not been sent.
4. Mark session as running.

### 9.2 Candidate Answer

For every answer message:

```text
receive audio payload
store audio temporarily or durably
call turn_processing pipeline
receive next question
send next question over websocket
persist updated Redis state
```

### 9.3 Completion

Complete if:

- time expires,
- interviewer/admin ends,
- candidate ends,
- required coverage is met and wrap-up completed,
- unrecoverable error occurs.

On completion:

```text
persist session state to Postgres
start report_generation pipeline
flush Redis state after safe persistence
```

## 10. Turn Processing Pipeline

### 10.1 Purpose

This is the core interview intelligence pipeline.

It processes one candidate answer and returns the next interviewer message.

### 10.2 Inputs

```json
{
  "interview_id": "int_123",
  "turn_id": "turn_005",
  "audio_ref": "blob/s3/local ref",
  "audio_bytes": null,
  "current_state": {},
  "last_question": {},
  "time_remaining_seconds": 1200
}
```

### 10.3 Recommended Haystack Graph

```text
session_state_loader
  -> audio_answer_understanding
  -> answer_quality_validator
  -> interview_context_provider
  -> evidence_extractor
  -> skill_state_updater
  -> next_move_planner
  -> question_generator
  -> tone_and_safety_rewriter
  -> turn_result_aggregator
  -> redis_session_updater
```

### 10.4 Component Responsibilities

#### session_state_loader

Loads active Redis state and validates the session.

#### audio_answer_understanding

Uses Gemini audio model to produce:

- transcript,
- answer summary,
- uncertainty markers,
- notable claims,
- communication observations,
- possible mishearing caveats.

#### answer_quality_validator

Checks whether the answer is:

- relevant,
- empty,
- too short,
- unclear,
- refusal,
- "I do not know",
- off-topic,
- needs clarification.

#### interview_context_provider

Builds the compact context needed for decision making:

- last question,
- last answer,
- recent turns,
- conversation summary,
- skill map,
- covered topics,
- uncovered high-priority topics,
- resume claims,
- JD requirements,
- time remaining.

#### evidence_extractor

Extracts structured evidence from the answer.

This should not decide the next question. It should produce objective signals.

#### skill_state_updater

Updates the skill map:

- score,
- confidence,
- attempts,
- scaffold attempts,
- status,
- evidence ids.

#### next_move_planner

Chooses the next interviewer move.

Output example:

```json
{
  "move_type": "scaffold_retry",
  "target_skill": "python_concurrency",
  "difficulty": "medium",
  "reason": "Candidate recognized threading connection but missed practical implications.",
  "desired_signal": "Can explain CPU-bound thread limitation and alternatives.",
  "avoid": ["asking the same GIL definition again"]
}
```

#### question_generator

Generates the next candidate-facing question from the plan.

#### tone_and_safety_rewriter

Ensures the question is:

- natural,
- concise,
- professional,
- not shaming,
- not overly verbose,
- not repetitive.

#### turn_result_aggregator

Builds a complete turn result:

- answer analysis,
- evidence,
- skill updates,
- next move,
- next question,
- completion recommendation.

#### redis_session_updater

Persists updated state.

## 11. Next-Move Planning Policy

The planner should choose from a controlled move set:

```text
open_topic
drill_down
scaffold_retry
ask_for_example
validate_resume_claim
switch_adjacent_topic
move_to_behavioral
close_topic
time_boxed_coverage
wrap_up
```

### 11.1 Example: Weak GIL Answer

Input signals:

```json
{
  "target_skill": "python_concurrency",
  "importance": 0.8,
  "answer_quality": "partial",
  "attempts": 1,
  "scaffold_attempts": 0,
  "time_remaining_seconds": 1300
}
```

Planner output:

```json
{
  "move_type": "scaffold_retry",
  "target_skill": "python_concurrency",
  "reason": "Important role skill; candidate showed partial recognition.",
  "instruction": "Ask a simpler applied follow-up without repeating the original question."
}
```

Generated question:

```text
That's okay. Think about Python threads for a moment. If two threads are doing
CPU-heavy Python work at the same time, what limitation might they run into?
```

### 11.2 Example: Candidate Says "I Do Not Know"

Planner output:

```json
{
  "move_type": "switch_adjacent_topic",
  "target_skill": "api_design",
  "reason": "Candidate explicitly declined Python concurrency; avoid over-drilling."
}
```

Generated question:

```text
No problem, let's move to something different. When you design a REST API for a
new feature, what are the first things you think about?
```

### 11.3 Example: Candidate Claims AI Model Experience

Planner output:

```json
{
  "move_type": "validate_resume_claim",
  "target_skill": "model_deployment",
  "reason": "Candidate mentioned deploying AI models; validate practical depth."
}
```

Generated question:

```text
You mentioned working with AI models. Could you walk me through how one of those
models was deployed and monitored after release?
```

## 12. Context Management Strategy

Do not pass the full transcript into every model call.

Maintain:

1. Full turn history for persistence.
2. Rolling conversation summary.
3. Structured skill map.
4. Evidence ledger.
5. Recent N turns for local conversational continuity.

The context provider should build a compact prompt context:

```json
{
  "role_summary": "...",
  "resume_relevant_points": [],
  "rubric_priorities": [],
  "current_skill_map_summary": {},
  "covered_topics": [],
  "recent_turns": [],
  "last_question": "...",
  "last_answer_summary": "...",
  "time_remaining": "...",
  "open_threads": []
}
```

This prevents context loss and keeps prompts smaller.

## 13. Report Generation Pipeline

### 13.1 Purpose

Generate a final interview report after completion.

### 13.2 Inputs

```json
{
  "interview_id": "int_123",
  "session": {},
  "resume_summary": {},
  "job_description_summary": {},
  "rubric": {},
  "turns": [],
  "evidence_ledger": [],
  "skill_map": {}
}
```

### 13.3 Haystack Graph

```text
session_data_loader
  -> evidence_normalizer
  -> dimension_score_calculator
  -> strength_risk_extractor
  -> question_level_evaluator
  -> recommendation_generator
  -> report_formatter
  -> postgres_report_writer
```

### 13.4 Report Output

```json
{
  "interview_id": "int_123",
  "overall_recommendation": "proceed",
  "overall_score": 7.2,
  "dimension_scores": {
    "field_expertise": 7.0,
    "experience_depth": 7.8,
    "communication": 7.1,
    "behavioral_ownership": 6.8
  },
  "strengths": [],
  "risks": [],
  "evidence_summary": [],
  "question_evaluations": [],
  "confidence": 0.78
}
```

## 14. Scoring and Weighting

Weights must be generated or selected during initialization from role context.

Example:

```json
{
  "role_level": "senior",
  "weights": {
    "field_expertise": 0.30,
    "experience_depth": 0.35,
    "communication": 0.15,
    "behavioral_ownership": 0.20
  }
}
```

The final score should not be a blind LLM judgment. It should be computed from
evidence records and then explained by the LLM.

Recommended approach:

1. Extract evidence per turn.
2. Assign score deltas or rubric observations.
3. Aggregate by skill.
4. Aggregate by dimension.
5. Apply role weights.
6. Use LLM to write explanation from structured evidence.

## 15. Observability

Create execution records similar to the platform service.

Parent record:

```text
interview_executions
```

Child records:

```text
interview_execution_steps
```

Minimum fields:

```text
execution_id
interview_id
candidate_id
role_id
turn_id
pipeline_name
step_uuid
step_name
component_name
status
timestamp
duration_ms
model_name
prompt_version
decision_reason
error
```

This is essential for debugging:

- why the next question was asked,
- what context was used,
- what evidence was extracted,
- why a topic was skipped,
- why a score changed.

## 16. POC Implementation Phases

### Phase 1: Skeleton

- Create FastAPI service.
- Add Redis session store.
- Add Postgres models or simple repository layer.
- Add pipeline registry.
- Add mock Gemini audio analyzer.
- Add initialization pipeline.
- Add turn processing pipeline.
- Add report generation pipeline.

### Phase 2: Intelligence

- Implement skill map builder.
- Implement context provider.
- Implement evidence extractor.
- Implement next-move planner.
- Implement question generator.
- Add prompt/version tracking.

### Phase 3: Live WebSocket

- Wire WebSocket to Redis session state.
- On candidate answer, run turn pipeline.
- Send generated question back.
- Handle disconnect/reconnect.
- Add time tracking.

### Phase 4: Final Report

- Persist final session to Postgres.
- Generate report from evidence ledger.
- Add dimension-level scores.
- Add strengths/risks.
- Add question-level evaluation.

### Phase 5: Validation

- Test with at least two roles:
  - fresher software engineer,
  - senior backend engineer,
  - or one non-technical role such as healthcare assistant.
- Test weak answers, strong answers, refusals, vague answers, and resume claims.

## 17. Example POC Scenario

Role:

```text
Mid-level Python backend engineer
```

Resume:

```text
Worked on FastAPI services, PostgreSQL, Redis, Docker, and AI model integration.
```

Opening question:

```text
Hi, good to meet you. Could you walk me through the backend work from your
experience that feels most relevant to this role?
```

Candidate says:

```text
I worked mostly on APIs and some AI model deployment.
```

System detects:

```json
{
  "claims": ["API development", "AI model deployment"],
  "depth": "shallow",
  "next_best_move": "validate_resume_claim"
}
```

Next question:

```text
You mentioned AI model deployment. Could you describe one model you helped
deploy and what you had to monitor once it was live?
```

Candidate gives weak answer.

System:

- records weak evidence for model deployment,
- avoids repeating the same question,
- switches to API design or asks a simpler follow-up depending on role weight.

## 18. Anti-Patterns to Avoid

Do not:

- make one giant prompt responsible for everything,
- store only raw transcripts and generate the report at the end,
- pass the full transcript into every turn,
- rely on a fixed question bank,
- ask the next question before updating skill state,
- make the model directly mutate Redis/Postgres,
- let question generation decide strategy implicitly,
- hide decision reasoning,
- treat "I do not know" as a failure to be hammered repeatedly,
- overfit to software engineering only.

## 19. Production Considerations After POC

After POC, consider:

- prompt versioning,
- model fallback,
- per-tenant interview configuration,
- audit logs,
- privacy and retention rules for audio,
- PII handling,
- candidate fairness review,
- human review overrides,
- load testing WebSocket concurrency,
- report calibration against human interviewer ratings,
- role taxonomy management,
- multilingual support if needed.

## 20. Final Recommendation

Use Haystack-style workflows for:

- initialization,
- per-turn processing,
- final report generation.

Do not use Haystack as the owner of the entire live interview loop. Keep the
WebSocket/session manager in normal FastAPI/asyncio code, and call pipelines at
bounded points.

The architecture should be:

```text
FastAPI/WebSocket session manager
  -> Redis active state
  -> Haystack per-turn pipeline
  -> Gemini audio understanding
  -> structured evidence/state update
  -> next question response
  -> Postgres final persistence
  -> Haystack report pipeline
```

This gives the POC the same strengths as the platform workflow service:

- modularity,
- traceability,
- controlled state,
- testability,
- separation of orchestration and business logic,
- clear execution history.

At the same time, it avoids over-engineering the interactive interview loop.

