# Frontrow AI Interview POC: Codex Operating Guide

## Project Mission

This project explores a humane, adaptive AI interview service. The intended service uses FastAPI, WebSockets, Redis, Postgres, Gemini audio understanding, and Haystack-style per-turn workflows.

The primary goal is not to build a rigid question bank. The goal is to build an interview brain that preserves context, evaluates evidence, chooses the next interviewing move, and asks natural role-aware follow-up questions.

## Required Context Before Work

Before making substantial changes, read these docs:

1. `docs/interview-poc/01-ai-interview-workflow-concept.md`
2. `docs/interview-poc/02-platform-service-ai-workflow-reference.md`
3. `docs/interview-poc/03-interview-service-poc-implementation-guide.md`
4. `.codex/steering/project-brief.md`
5. `.codex/steering/architecture-principles.md`
6. `.codex/workflows/validation-workflow.md`
7. `.codex/knowledge/current-ai-brew-interview-flow.md`
8. `.codex/knowledge/revamp-migration-notes.md`
9. `.codex/knowledge/service-ai-workflow-directory-adaptation.md`

## Operating Principles

- Treat the live interview as a stateful session, not one monolithic pipeline.
- Use bounded workflows for initialization, each interview turn, and final report generation.
- Keep WebSocket/session management in normal FastAPI/asyncio code.
- Use Haystack-style pipelines for structured decision workflows.
- Persist active state in Redis and durable state/report artifacts in Postgres.
- Generate questions dynamically from role, resume, answer evidence, and interview state.
- Do not hardcode question banks.
- Do encode interviewer behavior policies, rubrics, and validation rules.
- Keep every next-question decision explainable through structured state and evidence.

## Implementation Bias

- Use `uv` for environment isolation and package management.
Prefer simple, inspectable POC components first:

- deterministic state objects,
- explicit pipeline inputs/outputs,
- small prompts with version names,
- model-client abstractions,
- traceable decision payloads,
- test fixtures for strong/weak/refusal answers.

Avoid building a complex agent framework before proving the turn loop.

## Useful Local Codex Files

- `.codex/README.md`: index of the local Codex kit.
- `.codex/knowledge/interview-domain-model.md`: core domain model and vocabulary.
- `.codex/prompts/`: reusable prompt contracts.
- `.codex/workflows/validation-workflow.md`: checks to run before considering work complete.
- `.codex/hooks/auto-spawn-hooks.md`: guidance for when to delegate research/implementation subtasks.
- `.codex/skills/frontrow-interview-poc/SKILL.md`: project-specific skill instructions.

## Current POC Shape

The intended architecture is:

```text
FastAPI/WebSocket session manager
  -> Redis active interview state
  -> per-turn Haystack pipeline
  -> Gemini audio understanding
  -> evidence extraction and skill-state update
  -> next-move planner
  -> question generator
  -> next question over WebSocket
  -> Postgres final persistence
  -> report generation pipeline
```

