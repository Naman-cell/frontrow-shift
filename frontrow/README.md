# Frontrow AI Interview POC

Frontrow is a local proof of concept for a more humane, stateful AI interview service. It keeps the useful lifecycle mechanics from an AI-Brew-style interview system, but replaces the core interview intelligence with a structured Haystack workflow, Google Gemini audio understanding, Redis-backed live state, Postgres persistence, and an evidence-based report rubric.

The system is intended to be field agnostic. It should work for software engineering, healthcare, sales, operations, trades, blue-collar roles, service work, leadership roles, entry-level roles, and any other job family where a role description, candidate background, required skills, and interview duration are available.

The goal is not to make a chatbot that asks a list of questions. The goal is to simulate an interviewer that can listen, adapt, scaffold, drill down, respect candidate intent, track evidence, and produce a hiring report that a human reviewer can audit.

## What This Project Solves

The previous interview flow had several product issues:

- Questions felt robotic and templated.
- Context could be lost across turns.
- The system mostly appended transcript logs instead of maintaining structured interview state.
- “I do not know” and similar responses caused poor transitions.
- The interviewer did not naturally drill down after strong answers.
- Reports were vague because they did not expose evidence, skill coverage, or role-bar scoring.
- Audio testing required too much manual recording and button pushing.
- Voice generation blocked the next text response, increasing perceived latency.

This POC addresses those issues by introducing:

- A Haystack turn-processing graph.
- Structured `InterviewState` instead of raw transcript append-only memory.
- Gemini audio understanding for candidate responses.
- Azure Speech raw PCM streaming for interviewer voice.
- Candidate intent classification.
- Policy-backed next-move planning.
- Sliding-window conversation summary and open threads.
- Time-aware closing orchestration.
- Evidence-led report generation.
- A local browser test UI.

## Technology Stack

- Python 3.12
- FastAPI
- Haystack `AsyncPipeline`
- Google `google-genai`
- Redis
- PostgreSQL
- SQLAlchemy async engine
- Docker Compose
- `uv` for local environment/package management
- Vanilla HTML/CSS/JavaScript frontend

## Runtime Services

Docker Compose provides:

- `frontrow-postgres`
  - Port: `5432`
  - Database: `frontrow`
  - User/password: `postgres/postgres`

- `frontrow-redis`
  - Port: `6379`
  - DB: `0`

Expected environment:

```env
APP_NAME="Frontrow AI Interview POC"
ENVIRONMENT=local
CORS_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]'
PERSISTENCE_BACKEND=postgres
ACTIVE_STATE_BACKEND=redis

GEMINI_API_KEY=your_key_here
GEMINI_AUDIO_MODEL=gemini-2.5-flash
ENABLE_GEMINI=true

AZURE_SPEECH_KEY=your_azure_speech_key_here
AZURE_SPEECH_REGION=southeastasia
AZURE_TTS_VOICE=en-US-AndrewMultilingualNeural
AZURE_TTS_OUTPUT_FORMAT=raw-24khz-16bit-mono-pcm

REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/frontrow
```

## Running Locally

Start infrastructure:

```bash
docker compose up -d
```

Start backend:

```bash
uv run python -m uvicorn app.main:app
```

Serve frontend:

```bash
cd frontend
python3 -m http.server 5173
```

Open:

```text
http://localhost:5173
```

The frontend setup panel includes an interview duration selector for:

```text
2, 5, 10, 15, or 20 minutes
```

This is intentionally shorter than a production hiring slot so the POC can
exercise the time-aware orchestrator quickly.

Run validation:

```bash
uv run pytest
RUFF_CACHE_DIR=/tmp/frontrow-ruff-cache uv run ruff check .
```

## API Surface

Base prefix:

```text
/api/v1
```

REST endpoints:

- `POST /api/v1/interviews`
  - Creates an interview session.
  - Seeds role context, skill map, rubric, and first question.

- `POST /api/v1/interviews/{interview_id}/start`
  - Marks the interview as ongoing.
  - Sets `started_at`.
  - Initializes timer state.

- `POST /api/v1/interviews/{interview_id}/turn`
  - Processes one candidate answer through the same manager path used by WebSocket.
  - Useful for smoke testing.

- `POST /api/v1/interviews/{interview_id}/complete`
  - Completes the interview.
  - Generates and persists the report.

- `GET /api/v1/interviews/{interview_id}/report`
  - Returns the latest persisted report.

WebSocket endpoint:

```text
ws://localhost:8000/api/v1/interviews/{interview_id}/ws
```

Inbound WebSocket payload:

```json
{
  "text": "",
  "audio_ref": null,
  "audio_base64": "...",
  "audio_mime_type": "audio/webm;codecs=opus",
  "user_leave": false,
  "overtime": false,
  "is_complete": false
}
```

Outbound WebSocket question payload:

```json
{
  "message_type": "question",
  "query_asked": "Question text",
  "completed": false,
  "interview_duration": 1200,
  "audio_base64": null,
  "audio_mime_type": null,
  "reconnect": {
    "current_question": "Question text",
    "current_stage": "Ongoing",
    "remaining_seconds": 1200,
    "first_question_sent": true,
    "question_mode": "AI",
    "plan_position": 0,
    "generation": 0
  },
  "meta": {
    "pipeline": "haystack.turn_processing",
    "turn_index": 2,
    "candidate_intent": "answered",
    "answer_quality": "strong",
    "move_type": "drill_down",
    "target_skill": "fastapi",
    "time_remaining_seconds": 1138
  }
}
```

Live voice WebSocket:

```text
ws://localhost:8000/api/v1/voice/live
```

Inbound voice payload:

```json
{
  "text": "Question text to speak"
}
```

Outbound voice control messages are JSON:

```json
{
  "type": "voice_start",
  "sample_rate": 24000,
  "mime_type": "audio/pcm;rate=24000"
}
```

Audio chunks are sent as binary WebSocket frames containing raw 16-bit
little-endian mono PCM at 24 kHz. The browser schedules those chunks through
Web Audio as they arrive. It does not wait for a complete MP3/WAV file.

## End-To-End Interview Lifecycle

1. Interview is created through REST.
2. Role context is stored:
   - role title
   - seniority
   - JD summary
   - resume summary
   - resume claims
   - required skills
3. Initialization pipeline creates `InterviewState`.
4. Skill map is seeded from required skills.
5. Opening question is generated.
6. Candidate starts interview.
7. WebSocket connects.
8. Current question is sent immediately.
9. Frontend sends the question text to `/voice/live`.
10. Azure Speech streams raw PCM chunks back to the frontend.
11. Candidate opens mic.
12. Browser captures audio, detects silence, stops, and sends audio to backend.
13. Haystack turn pipeline processes answer.
14. Updated structured state is saved to Redis.
15. Next text question is sent immediately.
16. Azure Speech voice streams in parallel.
17. Interview ends by manual completion, client overtime, user leave, cheating flag, repeated disengagement, or time-aware closing.
18. Report generation reads final state.
19. Report is saved to Postgres.

## State Management

The system no longer relies on a simple append-only transcript.

Redis stores the active interview state:

```text
frontrow:{interview_id}:session
frontrow:{interview_id}:state
```

`frontrow:{interview_id}:session` stores full `InterviewState` JSON:

```text
InterviewState
  interview_id
  status
  role
  question_mode
  duration_minutes
  started_at
  time_remaining_seconds
  rubric
  skill_map
  conversation_summary
  turns[]
  evidence_ledger
  covered_topics[]
  open_threads[]
  closing_question_sent
  last_question
  next_question
  last_next_move
  planned_questions
  plan_position
```

`frontrow:{interview_id}:state` stores reconnect state:

```text
ReconnectState
  current_question
  current_stage
  remaining_seconds
  first_question_sent
  question_mode
  plan_position
  generation
```

Postgres stores durable artifacts:

```text
interview_sessions
  interview_id
  payload jsonb
  created_at
  updated_at

interview_reports
  interview_id
  payload jsonb
  created_at
  updated_at
```

## Sliding-Window Context

The live context has two layers:

1. Full structured turn history.
2. Compact sliding-window memory.

The compact memory is updated after every turn:

```text
conversation_summary
  Recent turn summaries:
  skill tested
  candidate intent
  answer quality
  key signal

open_threads
  unresolved claims
  missing expected points
  candidate preference/pivot signals
  weak or avoided topics
```

This prevents the question generator from seeing only the last answer in isolation. It can see patterns like:

- Candidate struggled with Python concurrency.
- Candidate preferred DevOps/production work.
- Candidate made a resume claim that needs validation.
- PostgreSQL schema design lacked specifics.
- Recent questions already covered API design.

## Haystack Turn Pipeline

The core interview intelligence lives in:

```text
app/pipelines/turn_processing/pipeline.py
app/pipelines/turn_processing/components.py
```

The Haystack graph:

```text
TargetSkillSelector
  -> AnswerUnderstandingNode
  -> EvidenceExtractorNode
  -> SkillStateUpdaterNode
  -> NextMovePlannerNode
  -> QuestionGeneratorNode
  -> TurnAggregatorNode
```

### TargetSkillSelector

Chooses which skill frames answer analysis.

Behavior:

- If there was a previous next move, use that target skill.
- Otherwise choose highest-priority uncovered skill.
- Fallback to role fit.

### AnswerUnderstandingNode

Uses the configured audio understanding service.

In Gemini mode it sends:

- prompt
- optional candidate audio bytes
- current question
- target skill
- required skill list
- sliding-window summary
- open threads

It returns normalized `AnswerAnalysis`:

```text
quality
intent
summary
confidence
resume_claim_detected
extracted_claim
suggested_interviewer_response
suggested_next_question
preferred_topics
preferred_relevant_skill_id
missing_expected_points
```

The model output is normalized defensively. If Gemini returns a string for a list field, the service coerces it into a one-item list instead of crashing the WebSocket.

### EvidenceExtractorNode

Turns answer analysis into durable evidence records:

```text
EvidenceRecord
  evidence_id
  interview_id
  turn_id
  skill_id
  dimension
  signal_type
  summary
  score_delta
  confidence
  quote_or_audio_ref
```

### SkillStateUpdaterNode

Updates the skill map:

```text
SkillNode
  attempts
  scaffold_attempts
  current_score
  confidence
  status
  evidence_ids
```

Status values:

- `untouched`
- `in_progress`
- `sufficient`
- `needs_validation`
- `low_confidence`

### NextMovePlannerNode

Applies interview policy.

Current policy:

```text
max_same_skill_attempts = 2
max_low_signal_streak_before_wrap = 3
scaffold_retry_importance_threshold = 0.65
closing_buffer_seconds = 180
low_time_seconds = 120
closing_time_seconds = 45
```

Supported moves:

- `open_topic`
- `drill_down`
- `scaffold_retry`
- `ask_for_example`
- `validate_resume_claim`
- `switch_adjacent_topic`
- `clarify_and_reask`
- `repeat_question`
- `repair_and_redirect`
- `move_to_behavioral`
- `close_topic`
- `candidate_questions`
- `time_boxed_coverage`
- `wrap_up`

Important behaviors:

- Strong answer drills down before broadening.
- First important refusal gets a scaffold retry.
- Repeated refusal moves away naturally.
- Candidate pivot request can redirect toward a preferred relevant skill.
- Clarification request clarifies and re-asks.
- Repeat request repeats instead of advancing.
- Frustration/disengagement can stop the interview gracefully.
- Low time starts a closing phase.
- After candidate questions, the next turn wraps up.

### QuestionGeneratorNode

Generates the next candidate-facing question.

Fast path:

- If Gemini answer understanding already returned a suitable `suggested_next_question`, reuse it.
- This avoids a second model call and reduces latency.

Otherwise:

- Gemini generates a new question from:
  - role
  - JD
  - resume
  - required skills
  - recent questions
  - conversation summary
  - open threads
  - candidate intent
  - answer quality
  - planner move

Mock mode uses a compact fallback.

### TurnAggregatorNode

Appends the completed turn and updates:

- `turns`
- `last_question`
- `next_question`
- `last_next_move`
- `covered_topics`
- `conversation_summary`
- `open_threads`
- `closing_question_sent`
- `updated_at`

## Candidate Intents

The system separates “answer quality” from “candidate intent.”

Intent values:

- `answered`
- `refusal`
- `pivot_request`
- `clarification_request`
- `repeat_request`
- `off_topic`
- `silence_or_noise`
- `disengaged`
- `frustrated`
- `unknown`

This distinction matters.

For example:

```text
"I don't know"
  -> refusal
  -> scaffold once or move on

"Can you repeat that?"
  -> repeat_request
  -> repeat current question

"I am stronger in DevOps"
  -> pivot_request
  -> redirect to relevant role skill if possible

silence / noisy answer
  -> silence_or_noise
  -> repair once, do not score as knowledge failure immediately

"I do not want to continue"
  -> disengaged / stop phrase
  -> graceful wrap
```

## Time-Aware Orchestration

Every turn refreshes:

```text
time_remaining_seconds = duration_minutes * 60 - elapsed_seconds
```

The planner uses dynamic time windows, scaled to the selected interview length:

```text
closing_buffer_seconds = max(45, min(180, duration_seconds * 0.25))
low_time_seconds       = max(30, min(120, duration_seconds * 0.18))
closing_time_seconds   = max(20, min(45,  duration_seconds * 0.12))
```

For a 2-minute POC interview, this means:

- Do not start closing immediately at 90 seconds remaining.
- Around 45 seconds remaining, ask the candidate for questions or concerns.
- Around 20 seconds remaining, wrap gracefully.

For a 20-minute interview, this preserves the larger production-like buffers:

- Around 3 minutes remaining, enter the candidate-question closing phase.
- Around 45 seconds remaining, end gracefully.

The planner behavior is:

- At `closing_buffer_seconds`, ask candidate questions/concerns.
- After candidate questions, wrap up.
- At `closing_time_seconds`, end gracefully.

This avoids starting a deep new topic when there is not enough time for:

- candidate response
- analysis
- final question
- outro

### Testing The Natural Outro

To test the actual orchestrator outro, do not click `Complete`; that endpoint
force-completes the session for debugging.

Use this flow:

1. Select `2 minutes` in the frontend.
2. Click `Create + Start`.
3. Answer normally for the first question or two.
4. Watch the timer. When it drops below roughly `0:30`, submit one more answer.
5. The Haystack turn-processing pipeline should choose `candidate_questions`.
6. Answer that final candidate-question prompt.
7. The next turn should end through policy with `ended_by_policy=true` in metadata.

## Gemini Integration

The provider abstraction lives in:

```text
app/services/audio_understanding_service.py
```

Gemini is used for:

- candidate audio answer understanding
- candidate intent classification
- evidence summary
- next question suggestion
- fallback next question generation
- opening question generation

Gemini model:

```text
GEMINI_AUDIO_MODEL=gemini-2.5-flash
```

Azure Speech is used for:

- interviewer voice streaming

Azure Speech settings:

```text
AZURE_SPEECH_KEY=your_azure_speech_key_here
AZURE_SPEECH_REGION=southeastasia
AZURE_TTS_VOICE=en-US-AndrewMultilingualNeural
AZURE_TTS_OUTPUT_FORMAT=raw-24khz-16bit-mono-pcm
```

Concurrency:

```text
model_semaphore = 4
```

The semaphore prevents provider overload. It does not magically make one model call faster. Latency is reduced mostly by:

- reusing `suggested_next_question` from answer understanding
- sending text to the interview UI immediately
- using Azure Speech for raw PCM voice chunks
- playing chunks through Web Audio instead of waiting for a complete audio file

## Audio Flow

Current browser/interview flow:

1. User clicks `Open Mic`.
2. Browser starts recording.
3. Browser monitors silence.
4. Silence auto-stops recording.
5. Audio is sent to WebSocket.
6. Gemini analyzes audio.
7. Text question returns first.
8. Frontend sends that question text to `/voice/live`.
9. Azure Speech emits raw PCM frames.
10. Browser schedules frames immediately with Web Audio.

This is still turn-based for candidate input because the candidate microphone is
sent after local silence detection. It is streaming for interviewer voice output.

True full-duplex conversation would need:

- streaming microphone frames to backend
- partial transcription / partial intent updates
- interruption/barge-in handling
- turn boundary detection server-side

The current POC is a step toward that experience: interviewer speech streams,
but candidate speech is still chunked per answer.

## Report Rubric

The report shape is based on the SkillBrew HTML artifact.

Report fields:

```text
fit_score
role_bar
verdict
rationale
tags
dimension_scores
score_composition
skill_breakdown
skill_role_match
competency_scorecard
ai_native_signals
soft_layer
worry_areas
recommended_next_steps
evidence_by_question
question_count
evidence_count
strengths
risks
caveats
generated_at
```

The four scored dimensions:

- Field expertise
- Experience depth
- Communication
- Behavioural and ownership

The weights are not fixed for every role. They adapt by seniority:

- Fresher, trainee, apprentice, junior:
  - More weight on communication, learning signal, and behavioral readiness.
- Mid-level:
  - Balanced field expertise, depth, communication, and ownership.
- Senior, lead, principal, manager:
  - More weight on experience depth and ownership.

The prompts are also field agnostic. They instruct the model to use the role's natural vocabulary instead of assuming a software context. A good answer might be a project, case, patient interaction, repair, customer issue, site task, sales conversation, route, procedure, shift, incident, or leadership decision depending on the role.

Advisory signals:

- Reasoning quality
- Coachability
- Learning agility

These are advisory and not part of the fit score.

The report is evidence-led:

- every strength links to evidence ids
- every risk links to evidence ids
- every skill has evidence ids
- evidence-by-question shows the question, answer excerpt, score band, and AI judgement

## Frontend POC

The frontend lives in:

```text
frontend/index.html
frontend/app.js
frontend/styles.css
```

Current features:

- create/start interview
- connect WebSocket
- render interviewer text
- stream Azure Speech voice through Web Audio
- open mic
- silence auto-stop
- send audio answer
- complete interview
- render structured report sections

The frontend intentionally remains simple. It is a test harness, not the final product UI.

## Known Limitations

This POC is significantly more structured than the initial version, but it is not yet a full production interviewer.

Known gaps:

- Not true bidirectional streaming yet.
- Candidate audio is still sent after a local turn boundary.
- No server-side voice activity detection yet.
- No interruption/barge-in handling.
- No durable per-turn execution-step table yet.
- No tenant-level report retention policy.
- No auth.
- No proctoring.
- No billing.
- No background Celery report chain.
- No full HTML/PDF report renderer yet.
- Question generation can still be improved with stronger model prompts and eval loops.

## Debugging

Inspect latest sessions:

```bash
docker exec frontrow-postgres psql -U postgres -d frontrow -c \
"select interview_id, payload->>'status' status, payload->>'candidate_id' candidate, created_at, updated_at from interview_sessions order by updated_at desc limit 10;"
```

Inspect latest reports:

```bash
docker exec frontrow-postgres psql -U postgres -d frontrow -c \
"select interview_id, payload->>'fit_score' fit_score, payload->>'verdict' verdict, payload->>'question_count' question_count, payload->>'evidence_count' evidence_count from interview_reports order by updated_at desc limit 10;"
```

Inspect Redis state:

```bash
docker exec frontrow-redis redis-cli keys 'frontrow:*'
```

Read one Redis session:

```bash
python - <<'PY'
import json, redis
r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
state = json.loads(r.get("frontrow:<interview_id>:session"))
print(state["status"], len(state["turns"]))
print(state["conversation_summary"])
print(state["open_threads"])
PY
```

## Current Design Direction

The intended architecture is:

```text
FastAPI lifecycle
  -> Redis live state
  -> Haystack intelligence pipeline
  -> Gemini audio/text provider
  -> Postgres durable artifacts
  -> evidence-led report
```

The key principle is that the interviewer should not simply pick the next uncovered skill. It should respond to the candidate’s answer, remember recent context, respect candidate intent, manage time, gather evidence, and then produce an auditable report.

The most important next milestone is true streaming:

```text
browser mic stream
  -> backend realtime audio session
  -> partial intent/transcript
  -> streaming interviewer response
  -> interruption-aware orchestration
```

That is the path to making the experience feel genuinely live rather than turn-based.
