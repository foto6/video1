# Creator Orchestrator

Provider-neutral, durable content-production control plane for YouTube/TikTok workflows.

Pipeline:

`research -> idea -> script -> assets -> voice -> edit -> critic -> publish queue -> analytics feedback`

The core includes a durable JSON-backed state machine, stable idempotency keys, retry/recovery state, immutable artifact lineage, evaluation hooks, explicit Runway/Descript/Metricool/vidIQ boundaries, and the frozen Growth `1.0` + Media `media.render.v1` integration boundary.

## Autonomous Content Cycle Simulator v2

Round 2 adds a deterministic local campaign simulator that runs multiple sequential jobs, feeds cycle N analytics into cycle N+1 as validated Growth feedback, supports restart after every stage, bounded critic revisions, explicit failure injection, media dry-run fingerprints, fake provider contract harnesses, campaign-wide DAG validation, and a final metrics/report artifact.

Sample campaign:

`fixtures/campaign.autonomous.v2.json`

Deterministic expected output:

`fixtures/campaign.autonomous.v2.expected.json`

Run the demo:

```bash
PYTHONPATH=src python -m creator_orchestrator.demo \
  fixtures/campaign.autonomous.v2.json \
  /tmp/creator-round2-demo
```

Real publishing remains disabled. The simulator has no live-publish mode; Metricool remains queue/dry-run only.

## Run tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

See `docs/ARCHITECTURE.md` and `docs/AUTONOMOUS_CYCLE_SIMULATOR_V2.md`.


## Durable external operations

Opt-in resumable adapters can persist provider-operation receipts across `prepared -> accepted -> result_obtained -> committed` without changing the synchronous adapter path. See `docs/EXTERNAL_OPERATION_RECOVERY.md`.


## Exact producer integration

Wave 4 adds strict `growth.creator_seed.v1` ingestion and concrete `media.job.v1` durable resume/poll integration using pinned producer fixtures. See `docs/EXACT_GROWTH_CREATOR_MEDIA_DURABLE_INTEGRATION.md`.


## Reproducible campaign checkpoints

`creator.campaign_checkpoint.v1` exports canonical content-addressed campaign state, durable stage/operation receipts, Growth/Media identities, lineage and producer provenance for idempotent restore/resume. Deterministic boundary fixtures and a reproducibility report live under `fixtures/checkpoints/`. See `docs/CAMPAIGN_CHECKPOINT_V1.md`.
