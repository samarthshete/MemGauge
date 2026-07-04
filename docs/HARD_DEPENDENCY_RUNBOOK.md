# Hard Dependency Outage Runbook

This runbook verifies the hard dependency health behavior for Postgres and Neo4j.
It is intentionally separate from `make r7-resilience`, which covers Redis
fail-open behavior.

## Command

Start the normal stack first:

```bash
make stack-up
```

Then run:

```bash
make hard-dependencies
```

The script stops `postgres` and `neo4j` one at a time, verifies `/healthz`
returns `503` with the correct dependency marked `down`, restarts the service,
and waits for `/healthz` to return to all up before continuing.

It does not drop volumes.

## Expected Output

```text
Hard dependency check against api=http://127.0.0.1:18000
  ok initial-health: postgres/neo4j/redis all up
  .. stopping postgres
  ok postgres-down-health: /healthz returned 503 with postgres=down
  .. restarting postgres
  ok postgres-recovery: /healthz recovered to all up
  .. stopping neo4j
  ok neo4j-down-health: /healthz returned 503 with neo4j=down
  .. restarting neo4j
  ok neo4j-recovery: /healthz recovered to all up
HARD DEPENDENCIES: PASS
```

## Limit

This verifies health/degradation and recovery for hard dependencies. It does not
claim search continues while Postgres or Neo4j is down; those are required
persistence dependencies for memory operations.
