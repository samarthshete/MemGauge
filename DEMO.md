# MemGauge — 90-second demo

**Problem (say this):** "When an agent's memory silently regresses — wrong recall,
stale facts, hallucinated facts — you find out in production; MemGauge catches it
in CI."

Prereqs: `docker compose up --build` is running (API on `http://127.0.0.1:18000`,
Grafana on `http://127.0.0.1:13000`). Total spoken time ≈ 90s.

---

### 0:00 — Add a memory + show the OTel span/log (≈20s)

```bash
curl -s -X POST localhost:18000/v1/memories \
  -H 'content-type: application/json' \
  -d '{"text":"Ada likes black coffee.","user_id":"demo"}' | jq
```

Then point at the API container logs — each request emits a structured JSON log
with `trace_id` and a `memory.add` OTel span:

```bash
docker compose logs --tail=5 api
```

> Say: "Every operation is traced and logged with a trace id."

### 0:20 — Search with score breakdown (≈20s)

```bash
curl -s 'localhost:18000/v1/memories/search?q=What%20does%20Ada%20drink%3F&user_id=demo' | jq '.items[0] | {content, score, signals}'
```

> Say: "Retrieval is transparent — vector, keyword, and graph signals, not a black box."

### 0:40 — Grafana latency panel (≈10s)

Open `http://127.0.0.1:13000` → **MemGauge** dashboard → show the operation
latency (p95) and eval recall/pass panels.

> Say: "p95 latency and the latest eval result are live in Grafana."

### 0:50 — Trigger a regression (≈25s)

Force a deliberate retrieval regression and run the gate:

```bash
# break retrieval: return only the top-1 result
sed -i.bak 's/\[:top_k\]/[:1]/' app/memory/retrieval.py

make seed
python scripts/run_eval_ci.py --dataset all ; echo "exit=$?"
```

> Say: "Recall@5 collapses, the gate exits non-zero, and it writes a report."

```bash
sed -n '1,20p' report.md          # shows "❌ FAIL" + the failing Recall@5 check
```

### 1:15 — Restore + close (≈15s)

```bash
mv app/memory/retrieval.py.bak app/memory/retrieval.py   # revert
python scripts/run_eval_ci.py --dataset all ; echo "exit=$?"   # exit=0, ✅ PASS
```

> Close: "That red check is the whole point — MemGauge gates agent-memory quality
> in CI. The repo is **MemGauge**."

---

**Reset after the demo:** `git checkout -- app/memory/retrieval.py` (or confirm the
`.bak` was restored), and `docker compose down` when finished.
