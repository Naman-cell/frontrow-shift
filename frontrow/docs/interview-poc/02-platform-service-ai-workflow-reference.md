# Platform Reference: Lessons from service-ai-workflow

## 1. Purpose

This document extracts architectural ideas from the existing
`service-ai-workflow` platform service that are useful for an AI interview
workflow POC.

The goal is not to copy the healthcare claim-remediation business logic. The
goal is to reuse the proven service patterns:

- FastAPI service boundary,
- pipeline registry,
- Haystack `AsyncPipeline` orchestration,
- sub-pipeline composition,
- execution context,
- execution and execution-step tracking,
- Redis-backed active runtime state,
- background task execution,
- component-level observability,
- checkpointing,
- recovery-friendly state transitions,
- separation between orchestration and domain-specific components.

## 2. Existing Service Overview

The relevant service is:

```text
service-ai-workflow/
```

Important files:

```text
service-ai-workflow/app/main.py
service-ai-workflow/app/api/v1/endpoints/pipelines.py
service-ai-workflow/app/pipelines/registry.py
service-ai-workflow/app/pipelines/denied_claims_remediation/pipeline.py
service-ai-workflow/app/pipelines/denied_claims_remediation/phase1.py
service-ai-workflow/app/pipelines/denied_claims_remediation/phase2.py
service-ai-workflow/app/pipelines/denied_claims_remediation/processors/unified_claim_processor.py
service-ai-workflow/app/pipelines/master_schema/processors/master_schema.py
service-ai-workflow/app/pipelines/master_schema/processors/pipeline_builder.py
service-ai-workflow/app/pipelines/process_single_claim_enhanced/pipeline.py
service-ai-workflow/app/observability/haystack_tracer.py
service-ai-workflow/app/observability/execution_lifecycle.py
library-python-common/library_ai_executions/library_ai_executions/execution_recorder.py
```

The claim-remediation service is a FastAPI application that exposes workflow
endpoints. At runtime it uses Haystack pipelines for structured orchestration
and custom asyncio loops for pagination/concurrency-heavy processing.

## 3. Main Architectural Pattern

The key pattern is:

```text
FastAPI endpoint
    -> validate request and runtime gates
    -> create execution context
    -> fetch registered pipeline
    -> run pipeline inside execution_context
    -> record execution and execution_steps
    -> persist final state
```

For long-running workflows, the endpoint starts a background task and returns an
acknowledgement immediately.

This is especially relevant for interviews because an interview session is also
long-running and stateful.

## 4. Pipeline Registry

The platform service uses a registry:

```text
app/pipelines/registry.py
```

Conceptually:

```python
register_pipeline("pipeline_name", factory)
pipeline = await get_pipeline("pipeline_name")
```

Important characteristics:

- pipelines are registered by name,
- factories create pipeline instances,
- created pipelines are cached,
- a global semaphore can cap concurrent pipeline runs.

For the interview service, a similar registry can hold:

- `interview_initialization`,
- `interview_turn_processing`,
- `interview_report_generation`,
- optional `answer_analysis`,
- optional `next_question_generation`,
- optional `context_provider`.

## 5. Haystack Usage in the Platform Service

Haystack is used as a DAG orchestration engine.

The service builds pipelines using:

```python
pipeline = AsyncPipeline()
pipeline.add_component("component_name", Component())
pipeline.connect("source.output", "target.input")
await pipeline.run_async(data={...})
```

Components expose typed outputs:

```python
@component.output_types(result=dict)
async def run_async(...):
    return {"result": ...}
```

The important lesson is that Haystack is not only for LLM chains. In the platform
service, Haystack components include:

- data retrieval,
- Elasticsearch writes,
- validation,
- gates,
- indexing delays,
- LLM processors,
- aggregation,
- status updates.

For the interview service, Haystack can similarly orchestrate:

- context retrieval,
- audio answer understanding,
- evidence extraction,
- skill-state updates,
- next-move planning,
- question generation,
- tone/humanization,
- Redis state persistence,
- report generation.

## 6. Claim Remediation Flow as a Reference

The claim-remediation endpoint is:

```text
POST /api/v1/workflows/compute/denied_claims_remediation
```

The high-level flow:

```text
endpoint
  -> validate executor handoff
  -> create ExecutionContext
  -> run DeniedClaimsRemediationPipeline
      -> phase 1 Haystack pipeline
      -> phase 2 asyncio pagination/concurrency loop
          -> per-claim UnifiedClaimProcessor Haystack pipeline
```

This nested orchestration is the most useful pattern for the interview POC.

## 7. Phase 1 Pattern

Claim remediation phase 1 is a Haystack graph:

```text
denied_claims_retriever
  -> claims_presence_gate
  -> existing_claims_filter
  -> claim_processing
  -> indexing_delay
```

This teaches an important pattern:

- use Haystack for structured, dependency-based workflow steps,
- use gates to control downstream behavior,
- use adapters when component sync/async interfaces differ,
- isolate domain operations in components.

Interview equivalent:

```text
session_context_loader
  -> answer_understanding
  -> evidence_extractor
  -> state_update_gate
  -> next_move_planner
  -> question_generator
  -> session_state_persister
```

## 8. Phase 2 Pattern

Claim remediation phase 2 is not a single Haystack graph. It is a custom
asyncio loop that:

- retrieves work in pages,
- processes chunks concurrently,
- updates claim status,
- invokes a per-item pipeline,
- records checkpoints,
- observes failure limits,
- cooperatively checks for interruption.

This matters because not everything should be forced into Haystack.

Interview equivalent:

- the WebSocket loop should not be a Haystack DAG,
- the live session manager should own connection state and message flow,
- each user answer can trigger a Haystack pipeline,
- the session manager decides when to end, pause, recover, or finalize.

## 9. Unified Claim Processor Pattern

The per-claim pipeline is:

```text
master_schema_processor
  -> master_schema_validator
  -> es_indexing_delay
  -> should_proceed_gate
  -> process_single_claim
  -> claim_notes_pusher
  -> result_aggregator
  -> claim_processing_status_updater
```

This pattern maps well to interview turns:

```text
answer_capture_processor
  -> answer_quality_validator
  -> context_provider
  -> should_continue_gate
  -> next_move_planner
  -> question_generator
  -> turn_result_aggregator
  -> session_state_updater
```

The lesson is to structure each turn as a pipeline with explicit intermediate
artifacts rather than one giant LLM prompt.

## 10. SuperComponent Pattern

The platform service wraps complex internal pipelines as Haystack
`@super_component` classes.

Example:

```text
MasterSchemaProcessor
```

Internally it runs a large pipeline that retrieves, formats, enriches, assembles,
and persists a master schema document. Externally it behaves like one component
inside a larger pipeline.

Interview equivalent:

- `AnswerUnderstandingProcessor`
- `InterviewContextProvider`
- `NextQuestionPlanner`
- `ReportGenerationProcessor`

Each can be internally complex but externally simple.

## 11. Execution Context

The platform service uses:

```python
ExecutionContext(
    organization_id=...,
    pipeline_name=...,
    execution_id=...,
    claim_id=...
)
```

This context is stored in a context variable and accessed by the custom
Haystack tracer.

Interview equivalent:

```python
ExecutionContext(
    organization_id=tenant_id,
    pipeline_name="interview_turn_processing",
    execution_id=interview_session_id,
    claim_id=None
)
```

The interview service may define a richer context:

```python
InterviewExecutionContext(
    tenant_id=...,
    interview_id=...,
    candidate_id=...,
    role_id=...,
    turn_id=...,
    pipeline_name=...
)
```

The same principle applies: every pipeline step should know which session and
turn it belongs to.

## 12. Executions and Execution Steps

The platform has two main observability indices:

```text
executions
execution_steps
```

The relationship:

```text
executions 1 -> many execution_steps
```

For claim remediation:

- `executions` is the parent workflow run,
- `execution_steps` are component/checkpoint records,
- per-claim steps share the same execution id and include a claim id.

Interview equivalent:

- `interview_executions` or `executions` is the parent interview session/run,
- `interview_execution_steps` or `execution_steps` are turn/component records,
- per-turn steps include `turn_id`,
- optionally answer-level steps include `question_id`.

Suggested interview fields:

```text
execution_id / interview_id
tenant_id
candidate_id
role_id
pipeline_name
turn_id
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

## 13. Redis Buffering Pattern

The platform tracer buffers step records in Redis before bulk persistence. This
prevents Data Service/Elasticsearch from being overloaded during large runs.

Interview sessions produce fewer steps than claim batches, but Redis is still
useful for:

- active session state,
- current interview context,
- turn history cache,
- in-progress model call state,
- reconnect handling,
- active WebSocket status,
- temporary execution-step buffering.

The interview service can persist final data to Postgres when the session ends.

## 14. Background Task Pattern

The platform starts long-running workflows as background tasks:

```python
task = asyncio.create_task(_run_pipeline())
register_background_task(task, ...)
```

Interview equivalent:

- the live WebSocket loop is already long-running,
- report generation can be a background task after interview completion,
- session cleanup/final persistence can be done in a managed background task.

Do not block the WebSocket while generating the final report if it takes time.

## 15. Interruption and Recovery Pattern

The platform supports cooperative interruption:

- tracer checks at Haystack component boundaries,
- long loops call explicit interrupt checkpoints,
- final status becomes interrupted if requested,
- snapshots may be saved.

Interview equivalent:

- candidate disconnect,
- interviewer/admin stops session,
- time expires,
- candidate requests repeat/clarification,
- model provider error,
- network reconnection.

The interview service should support resumable or gracefully finalizable states:

```text
created
initialized
running
paused
completed
abandoned
failed
report_generating
report_ready
```

## 16. Component Timing Pattern

The platform records timing for selected components, especially LLM-heavy
components.

Interview equivalent:

Track timing for:

- audio understanding,
- answer analysis,
- context provider,
- next-move planner,
- question generation,
- report generation.

This matters because live interviews need low turn latency.

## 17. What to Reuse Conceptually

Reuse these ideas:

- pipeline registry,
- per-pipeline factories,
- Haystack `AsyncPipeline`,
- super-components for complex subflows,
- execution context,
- execution/step tracking,
- Redis active state,
- background report task,
- checkpoint records,
- component timing,
- explicit gates,
- result aggregators,
- state updaters.

Do not reuse directly:

- claim-specific models,
- Elasticsearch-specific assumptions,
- healthcare claim status names,
- master schema business logic,
- denied-claims executor handoff flow unless the interview service has its own
  scheduler/executor.

## 18. Platform-to-Interview Mapping

| Platform claim service | Interview service equivalent |
| --- | --- |
| denied_claims_remediation execution | interview session execution |
| claim_processing index | active interview session/turn state |
| StoredClaim | InterviewTurn / CandidateAnswer |
| claim_id | turn_id or question_id |
| master_schema_processor | answer/context/evidence processor |
| process_single_claim | next-question intelligence pipeline |
| ClaimProcessingStatusUpdater | SessionStateUpdater |
| result_aggregator | TurnResultAggregator |
| Phase2CheckpointRecorder | TurnCheckpointRecorder |
| HaystackExecutionTracer | InterviewExecutionTracer |
| execution_steps | interview step trace |

## 19. Recommended Adaptation

The interview service should use the platform architecture as a reference, but
with one important change:

> The live interview loop should remain outside Haystack. Haystack should process
> initialization, each turn, and final report generation.

This prevents over-engineering the WebSocket flow while keeping the decision
logic structured.

