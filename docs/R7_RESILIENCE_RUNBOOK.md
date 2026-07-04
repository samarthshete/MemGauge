# R7 Resilience Runbook

R7 proves the current robustness behavior against a live local stack:

- bad memory input returns 422;
- deleting a missing memory returns 404;
- Redis dependency failure makes `/healthz` return 503/degraded;
- memory search still works while Redis is down because cache reads/writes fail
  open;
- Redis is restarted and `/healthz` recovers to all up.

## Command

Start the normal stack first:

```bash
make stack-up
```

Then run:

```bash
make r7-resilience
```

The script temporarily stops only the compose `redis` service and always attempts
to restart it in a `finally` block.

## Verified Evidence

Observed on 2026-06-29:

```text
R7 resilience check against api=http://127.0.0.1:18000
  ok healthz-initial: postgres/neo4j/redis all up
  ok bad-input-422: POST /v1/memories rejects missing text/messages
  ok missing-memory-404: DELETE missing memory returns 404
  ok seed-memory: stored id=9c37fc2f-3e28-4698-ae80-7df233ee8a87
  ok search-before-redis-stop: search returned 1 item(s), cache=miss
  .. stopping redis service for fail-open check
  ok healthz-redis-down: /healthz returns 503 with redis down
  ok search-redis-down-fail-open: search returned 1 item(s), cache=miss
  .. restarting redis service
  ok recovery: redis restarted and /healthz is healthy
R7 RESILIENCE: PASS
```

## Limits

This verifies Redis fail-open behavior plus representative 422/404/503 paths.
It does not intentionally stop Postgres or Neo4j, because those are hard
dependencies for memory search and would require a broader recovery drill.
