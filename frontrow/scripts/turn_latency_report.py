#!/usr/bin/env python3
"""Parse structured turn_latency log lines and print p50/p95 per segment.

Usage:
    # From a log file:
    python scripts/turn_latency_report.py < server.log

    # Filter by interview:
    python scripts/turn_latency_report.py --interview int_abc123 < server.log

    # From a JSON-lines file (one turn_latency JSON per line):
    python scripts/turn_latency_report.py --jsonl < latency.jsonl

The script looks for lines containing 'turn_latency {' and extracts the JSON
payload. It then computes p50 and p95 for each timing segment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys


def percentile(data: list[int], pct: int) -> int:
    """Compute the pct-th percentile of a sorted list."""
    if not data:
        return 0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return int(sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f]))


TURN_LATENCY_RE = re.compile(r"turn_latency\s+(\{.+\})")

SEGMENTS = [
    ("backend_total_ms", "Backend total"),
    ("turn_pipeline_ms", "Turn pipeline"),
    ("audio_assembly_ms", "Audio assembly"),
    ("answer_understanding_ms", "Answer understanding"),
    ("gemini_analyze_ms", "Gemini analyze"),
    ("question_generator_ms", "Question generation"),
    ("evidence_extractor_ms", "Evidence extraction"),
    ("skill_state_updater_ms", "Skill state update"),
    ("next_move_planner_ms", "Next-move planner"),
    ("target_skill_selector_ms", "Target skill select"),
    ("turn_aggregator_ms", "Turn aggregation"),
    ("state_save_ms", "State save"),
]


def extract_entries(lines: list[str], *, jsonl: bool = False) -> list[dict]:
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if jsonl:
            try:
                obj = json.loads(line)
                if obj.get("event") == "turn_latency":
                    entries.append(obj)
            except json.JSONDecodeError:
                continue
        else:
            m = TURN_LATENCY_RE.search(line)
            if m:
                try:
                    entries.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    continue
    return entries


def report(entries: list[dict], interview_filter: str | None = None) -> None:
    if interview_filter:
        entries = [e for e in entries if e.get("interview_id") == interview_filter]

    if not entries:
        print("No turn_latency entries found.")
        return

    interviews = {e.get("interview_id", "?") for e in entries}
    print(f"Turns: {len(entries)}  |  Interviews: {', '.join(sorted(interviews))}")
    print()
    print(f"{'Segment':<25s}  {'p50 ms':>8s}  {'p95 ms':>8s}  {'min':>6s}  {'max':>6s}")
    print("-" * 60)

    for key, label in SEGMENTS:
        values = [e.get(key, 0) for e in entries]
        if not any(values):
            continue
        p50 = percentile(values, 50)
        p95 = percentile(values, 95)
        lo = min(values)
        hi = max(values)
        print(f"{label:<25s}  {p50:>8d}  {p95:>8d}  {lo:>6d}  {hi:>6d}")

    print()
    print("Per-turn breakdown:")
    for e in entries:
        tid = e.get("turn_index", "?")
        total = e.get("backend_total_ms", 0)
        understand = e.get("answer_understanding_ms", 0)
        qgen = e.get("question_generator_ms", 0)
        save = e.get("state_save_ms", 0)
        rest = total - understand - qgen - save
        print(
            f"  turn {tid:>3}: total={total:>5d}  "
            f"understand={understand:>5d}  qgen={qgen:>5d}  "
            f"save={save:>5d}  rest={rest:>5d} ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn latency p50/p95 report")
    parser.add_argument("--interview", help="Filter to a specific interview_id")
    parser.add_argument("--jsonl", action="store_true", help="Input is JSON-lines")
    args = parser.parse_args()

    lines = sys.stdin.read().splitlines()
    entries = extract_entries(lines, jsonl=args.jsonl)
    report(entries, interview_filter=args.interview)


if __name__ == "__main__":
    main()
