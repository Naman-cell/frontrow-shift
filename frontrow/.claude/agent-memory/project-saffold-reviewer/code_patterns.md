---
name: code-patterns
description: Recurring patterns, conventions, and gotchas found in frontrow-shift reviews
metadata:
  type: project
---

## Validator placement
Pydantic `@field_validator` used in model classes (`interview.py`, `state.py`). Validators defined as inner closures when they need helper functions (see `split_long_skills`).

## skill_id slugification
Canonical pattern in `seed_skills_from_role()` (state.py): strip special chars via regex, replace whitespace with underscore, lowercase, truncate to 60 chars, collapse double underscores, strip trailing underscores. Hyphens are intentionally kept (not in strip set).

## Score thresholds (1-4 scale)
- `score_label()`: >=3.5 exceeds, >=2.5 meets, >=1.5 below, else well_below (uses underscore_case: "exceeds_expectation")
- `skill_band()`: compares against seniority target ± 0.5/0.25/1.0
- `score_band()`: similar but generic (not skill-specific)
- score_4=0 maps to "well below expectation" — intentional, means unassessed skill treated as gap

## Known sharp edge: 8-char minimum in split_long_skills
`split_long_skills` in `interview.py` applies a >= 8 char minimum to extracted labels. This correctly filters JD section headers but also silently drops legitimate short skill names (AWS, SQL, Java, Docker, Redis, CI/CD, Git). This is a REGRESSION from the old code which kept short names as-is. Only affects skills passed as part of a longer JD blob that gets split; standalone short skills in the list are affected too.

## Test style
Async tests use `@pytest.mark.asyncio`. Tests in `tests/test_pipelines/`. Three bugs (stop detection, planner loop, question dedup) have dedicated tests in `test_bug_fixes.py`. The three coder-agent fixes (skill splitting, score labels, skill_id cleanup) have NO dedicated unit tests.

## Tempfile pattern for OpenAI Whisper
Canonical pattern: `fd, path = tempfile.mkstemp(suffix=ext)` + `try/finally: os.unlink(path)`. Write via `os.fdopen(fd, "wb")`, read back via `open(path, "rb")`. This avoids Windows file-lock issues with `NamedTemporaryFile(delete=True)`. fd ownership passes to `os.fdopen` atomically (CPython closes fd on failure).

## Dual-path background analysis scheduling
`_schedule_background_analysis` must be called in ALL interview-end branches inside `process_turn`: (1) `should_end_interview`, (2) `completed` from `_apply_question_mode`, and (3) normal-turn path. The early-exit branch (user_leave/overtime/is_complete at top of process_turn) fires BEFORE audio is captured so no scheduling is needed there. Guard: `if audio_for_background and output.state.turns`.

## background_gemini_ms metric
Must be measured inside the `_run()` closure of `_schedule_background_analysis` using `perf_counter()` bracketing the `analyze_answer()` call — NOT copied from `gemini_analyze_ms` in runtime_metrics. Stored to `state.runtime_metrics["background_gemini_ms"]` after re-fetching state inside closure.

## Components.py operator-precedence gotcha
In `_extract_label()`, the condition `2 <= len(label) <= 60 and ... and " " not in label or (" " in label ...)` has no length guard on the `or` branch — a label >60 chars with a space and <=6 words slips through. Low real-world impact since such labels would be rare in JD data.

## Fast-pipeline architecture (Whisper + Mock + Gemini questions)
`InterviewSessionManager` carries two pipelines when fast-transcription is enabled:
- `turn_processing_pipeline` — full Gemini audio analysis (used for bg task + normal path)
- `fast_turn_processing_pipeline` — Mock analysis + Gemini question_generation_service

Selection logic: `audio_for_background` is truthy only when both `transcription_service` is set AND `payload.audio_base64` was present. The fast pipeline is chosen iff `audio_for_background and self.fast_turn_processing_pipeline`.

Background analysis always calls `self.turn_processing_pipeline.audio_understanding_service` (not the fast pipeline service).

## Guard consistency at all three scheduling sites (FIXED in Round 3)
All three `_schedule_background_analysis` call sites in `process_turn` now use `if audio_for_background and output.state.turns:` (lines 200, 251, 290). The former defect at line 290 (only `if audio_for_background:`, no turns check) was resolved. The `and output.state.turns` guard prevents `turn_index = len([]) - 1 = -1` when turns is unexpectedly empty.

## background_gemini_ms is always 0 in the current turn's latency log (by design)
The metric is written by the background task after `process_turn` returns. The latency log emitted in `process_turn` will always show 0 for `background_gemini_ms`; the value appears in `state.runtime_metrics` for the NEXT turn's latency spread.

## ruff E501 in factory.py
One remaining pre-existing E501 violation: line 28 (89 chars, function signature). The 109-char whisper condition on line 58 was resolved in Round 3 by extracting it into a `whisper_ready` local variable. Project ruff config has 88-char limit.
