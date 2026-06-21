"""Integration tests for evaluation API behavior."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_eval_run_persists_and_reports_pass_fail_logic(
    app_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.eval.report as report_module
    import app.eval.runner as runner_module
    from app.eval.runner import _compare_to_baseline

    dataset_path = tmp_path / "phase8_eval.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "phase8-eval-001",
                "user_id": "phase8-eval-user",
                "seed_memories": [
                    {
                        "memory_id": "phase8-memory",
                        "text": "PhaseEightEval likes plum tea.",
                    }
                ],
                "query": "What does PhaseEightEval like?",
                "expected_memory_id": "phase8-memory",
                "target_failure_mode": "none",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setitem(runner_module.DATASETS, "phase8", [dataset_path])
    monkeypatch.setattr(runner_module, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(report_module, "BASELINE_PATH", baseline_path)

    run_response = await app_client.post(
        "/v1/eval/run",
        json={"dataset": "phase8", "set_baseline": True},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()

    assert run_payload["dataset"] == "phase8"
    assert run_payload["total_cases"] == 1
    assert run_payload["passed"] is True
    assert baseline_path.exists()

    runs_response = await app_client.get("/v1/eval/runs")
    assert runs_response.status_code == 200
    stored = runs_response.json()["items"][0]
    assert stored["id"] == run_payload["run_id"]
    assert stored["dataset_name"] == "phase8"
    assert stored["passed"] is True

    report_response = await app_client.get(f"/v1/eval/report/{run_payload['run_id']}")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["run"]["id"] == run_payload["run_id"]
    assert report["cases"][0]["case_id"] == "phase8-eval-001"

    failed, baseline_id = _compare_to_baseline(
        {
            "recall_at_5": 0.0,
            "p95_search_ms": run_payload["p95_search_ms"] * 2 + 1,
            "false_fact_rate": run_payload["false_fact_rate"] + 1,
        },
        run_payload,
        set_baseline=False,
    )
    assert failed is False
    assert baseline_id == run_payload["run_id"]
