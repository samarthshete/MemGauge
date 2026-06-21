"""Run the MemGauge evaluation benchmark as a CI regression gate.

Connects to the configured Postgres/Neo4j/Redis services, runs an evaluation
against the mock backend, writes a Markdown summary to ``report.md`` and stdout,
compares the run against ``data/baseline.json``, and exits non-zero when the run
regresses (``passed`` is false).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from app.eval.report import read_baseline
from app.eval.runner import run_eval

REPORT_PATH = Path("report.md")

# (key, label, direction) — direction documents whether higher or lower is better.
METRIC_ROWS = (
    ("recall_at_5", "Recall@5", "higher"),
    ("precision", "Precision", "higher"),
    ("staleness_rate", "Staleness rate", "lower"),
    ("false_fact_rate", "False-fact rate", "lower"),
    ("p95_search_ms", "Search p95 (ms)", "lower"),
    ("p95_add_ms", "Add p95 (ms)", "lower"),
)


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key.endswith("_ms"):
        return f"{float(value):.2f}"
    return f"{float(value):.3f}"


def _gate_checks(summary: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Mirror app.eval.runner._compare_to_baseline so the report explains the verdict."""

    recall_floor = baseline["recall_at_5"] - 0.05
    p95_ceiling = baseline["p95_search_ms"] * 1.25
    false_fact_ceiling = baseline["false_fact_rate"]
    return [
        {
            "name": "Recall@5 holds",
            "detail": f"{summary['recall_at_5']:.3f} ≥ {recall_floor:.3f} (baseline − 0.05)",
            "ok": summary["recall_at_5"] >= recall_floor,
        },
        {
            "name": "Search p95 within budget",
            "detail": f"{summary['p95_search_ms']:.2f} ms ≤ {p95_ceiling:.2f} ms (baseline × 1.25)",
            "ok": summary["p95_search_ms"] <= p95_ceiling,
        },
        {
            "name": "No new false facts",
            "detail": f"{summary['false_fact_rate']:.3f} ≤ {false_fact_ceiling:.3f} (baseline)",
            "ok": summary["false_fact_rate"] <= false_fact_ceiling,
        },
    ]


def build_markdown(summary: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    status = "✅ PASS" if summary["passed"] else "❌ FAIL"
    lines: list[str] = []
    lines.append(f"# MemGauge Eval Gate — {status}")
    lines.append("")
    lines.append(f"- **Run ID:** `{summary['run_id']}`")
    lines.append(f"- **Dataset:** `{summary['dataset']}`")
    lines.append(f"- **Total cases:** {summary['total_cases']}")
    lines.append(f"- **Result:** {'passed' if summary['passed'] else 'regressed'}")
    lines.append("")

    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Current | Baseline | Better |")
    lines.append("| --- | --- | --- | --- |")
    for key, label, direction in METRIC_ROWS:
        current = _format_value(key, summary.get(key))
        baseline_value = _format_value(key, (baseline or {}).get(key))
        lines.append(f"| {label} | {current} | {baseline_value} | {direction} |")
    lines.append("")

    lines.append("## Failure modes")
    lines.append("")
    counts = summary.get("failure_mode_counts", {})
    if counts:
        lines.append("| Failure mode | Count |")
        lines.append("| --- | --- |")
        for mode in sorted(counts):
            lines.append(f"| {mode} | {counts[mode]} |")
    else:
        lines.append("_No cases recorded._")
    lines.append("")

    lines.append("## Regression gate")
    lines.append("")
    if baseline is None:
        lines.append("_No baseline found — this run initialized `data/baseline.json`._")
    else:
        lines.append("| Check | Status | Detail |")
        lines.append("| --- | --- | --- |")
        for check in _gate_checks(summary, baseline):
            mark = "✅" if check["ok"] else "❌"
            lines.append(f"| {check['name']} | {mark} | {check['detail']} |")
    lines.append("")

    return "\n".join(lines) + "\n"


async def _main() -> None:
    parser = argparse.ArgumentParser(description="MemGauge evaluation regression gate")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    # Read the committed baseline before running so the report compares against
    # the prior reference (run_eval may rewrite it when none exists).
    baseline = read_baseline()
    summary = await run_eval(dataset=args.dataset, set_baseline=args.set_baseline)

    markdown = build_markdown(summary, baseline)
    REPORT_PATH.write_text(markdown, encoding="utf-8")
    print(markdown)

    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(_main())
