# Creator Orchestrator

Provider-neutral, durable content-production control plane for YouTube/TikTok workflows.

Pipeline:

`research -> idea -> script -> assets -> voice -> edit -> critic -> publish queue -> analytics feedback`

The MVP includes a durable JSON-backed state machine, stable stage idempotency keys, retry/recovery state, immutable artifact lineage, evaluation hooks, explicit Runway/Descript/Metricool/vidIQ boundaries, and tests.

Real publishing is intentionally disabled. The Metricool boundary is queue/dry-run only.

## Run tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

See `docs/ARCHITECTURE.md` for design and recovery semantics.
