# Optional OTLP Collector Verification

By default, MemGauge exports spans to stdout using OpenTelemetry's console
exporter. R6 verifies that path. To prove remote OTLP export, run the optional
collector override.

## Config Check

```bash
make otlp-config-check
```

This validates the base compose file plus `docker-compose.otel.yml`.

## Live Collector Run

```bash
make otlp-live-check
```

Expected evidence:

- the API is healthy under the OTLP override;
- a protected memory add succeeds;
- `otel-collector` logs contain exported span data for `memory.add`;
- the default stack is restored after the check.

## Current Status

The default local stack has verified console span export. The optional local
collector override is also verified: `make otlp-live-check` exported a
`memory.add` span to `otel-collector` and restored the default stack afterward.

Production collector endpoints remain environment-specific. Set
`OTEL_EXPORTER_OTLP_ENDPOINT` to the target collector and re-run the same smoke
flow in that environment.
