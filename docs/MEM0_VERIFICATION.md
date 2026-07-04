# Optional Real Mem0 Verification

The default MemGauge workflow is intentionally secret-free and uses
`MEMGAUGE_BACKEND=mock`. The real `mem0` backend is optional and must be verified
only on a local machine where you are willing to use your own API keys.

Do not commit `mem0ai`, `.env`, `MEM0_API_KEY`, or `OPENAI_API_KEY`.

## Preflight

```bash
pip install mem0ai
export MEMGAUGE_BACKEND=mem0
export OPENAI_API_KEY=...     # local OSS Mem0 path
# or:
export MEM0_API_KEY=...       # hosted Mem0 platform path

make mem0-preflight
```

`make mem0-preflight` prints whether the optional package and required
environment variables are present. It never prints secret values.

## Verification

Use the same stores and eval harness as the mock backend:

```bash
make stack-up
MEMGAUGE_BACKEND=mem0 make eval
```

Expected behavior:

- the eval completes without import/key errors;
- Mem0 results are mirrored into the same Postgres `memories` /
  `memory_events` tables;
- graph facts are mirrored into Neo4j through `Neo4jClient`;
- `report.md` records the measured recall, latency, stale-fact, and false-fact
  rates for the real backend.

## Current Status

Unverified in the secret-free repo workflow. This is intentional: the public
default must run with zero external keys.
