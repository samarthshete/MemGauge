# MemGauge Eval Gate — ✅ PASS

- **Run ID:** `0a955512-0a9f-4ee1-9be3-54492d5517f4`
- **Dataset:** `all`
- **Total cases:** 40
- **Result:** passed

## Metrics

| Metric | Current | Baseline | Better |
| --- | --- | --- | --- |
| Recall@5 | 0.875 | 0.875 | higher |
| Precision | 0.500 | 0.500 | higher |
| Staleness rate | 0.125 | 0.125 | lower |
| False-fact rate | 0.125 | 0.125 | lower |
| Search p95 (ms) | 8.79 | 28.77 | lower |
| Add p95 (ms) | 32.65 | 57.61 | lower |

## Failure modes

| Failure mode | Count |
| --- | --- |
| false_fact | 5 |
| none | 27 |
| retrieval_miss | 3 |
| stale_fact | 5 |

## Regression gate

| Check | Status | Detail |
| --- | --- | --- |
| Recall@5 holds | ✅ | 0.875 ≥ 0.825 (baseline − 0.05) |
| Search p95 within budget | ✅ | 8.79 ms ≤ 35.96 ms (baseline × 1.25) |
| No new false facts | ✅ | 0.125 ≤ 0.125 (baseline) |

