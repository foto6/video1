# Autonomous Content Cycle Simulator v2

## Purpose

The simulator is a deterministic, local-only campaign runtime layered on the existing Creator Orchestrator. It exercises multiple sequential content jobs without provider credentials, live rendering, account mutation, or social publishing.

It keeps the frozen integration contracts:

- Growth feedback: `contract_version` exactly `1.0`.
- Media planning: `contractVersion` exactly `media.render.v1`, always `dryRun: true`.

The normal nine-stage order is unchanged:

`research -> idea -> script -> assets -> voice -> edit/media -> critic -> publish queue -> analytics`

## Campaign lifecycle

A campaign owns N sequential jobs. After cycle N finishes analytics, the simulator deduplicates analytics events and derives a validated Growth `CreatorFeedback 1.0` payload. That payload is persisted in campaign state and becomes an immutable `growth_feedback` seed of cycle N+1.

The next-cycle seed has a lineage edge back to the prior cycle's `analytics_feedback` artifact. The caller-supplied `media_timeline_v1` remains a separate seed in every cycle. No duration, source, timeline, or render metadata is synthesized from generic Creator artifacts.

## Durability and restart

`CampaignRunner.step()` performs at most one durable transition or stage attempt. Job state is stored by `JsonJobStore`; campaign state is stored by `JsonCampaignStore`. Both stores use fsync plus atomic replacement.

The runner may be reconstructed between any two steps. Persisted state contains:

- current cycle and job IDs;
- completed cycles and Growth feedback payloads;
- critic decisions already handled;
- analytics event digests used for duplicate suppression;
- final campaign report artifact.

Per-logical-operation retry counts are persisted under idempotency keys, while aggregate per-stage attempt counts remain available for campaign metrics. Critic revisions create new logical idempotency keys instead of consuming the retry budget of the prior successful revision.

## Critic/revision loop

The sample campaign uses a deterministic critic. A reject decision is persisted as a `critic_decision` artifact before any rewind. The runner may rewind only to a pre-critic stage. `maxCriticRevisions` bounds the loop; exceeding it marks the campaign failed instead of looping indefinitely.

Old artifacts are never deleted. Revised artifacts append to the lineage DAG with new IDs, so historical attempts remain auditable.

## Failure injection

The fixture can inject retryable failures by cycle, stage and aggregate stage-attempt number. Supported failure aliases are:

- `research`
- `script`
- `assets`
- `voice`
- `media`
- `critic`
- `queue`
- `analytics`

The sample fixture injects at least one failure in every supported alias. Because the attempt counters are persisted, a reconstructed runner does not repeatedly inject a first-attempt failure after restart.

## Provider fakes and contract harnesses

Local fakes implement the current provider interfaces:

- `FakeRunway`
- `FakeDescript`
- `FakeMetricool`
- `FakeVidIQ`
- `FakeMediaEngine`

Runway, Descript, Metricool and vidIQ fakes enforce stable idempotency behavior for repeated logical requests. The Media fake validates the exact six-field `media.render.v1` request, requires `dryRun: true`, and produces a deterministic render fingerprint from timeline + export specification.

The simulator records explicit artifacts for provider-facing work, including `asset_request`, `voice_request`, `media_request`, `publish_queue_item`, and `analytics_feedback`.

## Publishing safety

The simulator exposes no live-publishing configuration. Campaign fixtures reject unknown top-level and media fields, so a live-publishing flag cannot be introduced through configuration.

`SimQueueAdapter` always submits `dry_run=True` and `action=queue_only`. `FakeMetricool` rejects any request where `dry_run` is not exactly true or the action is not `queue_only`. The existing `MetricoolPublishQueueAdapter(dry_run=False)` continues to raise `RealPublishingDisabled`.

## Lineage validation

`validate_artifact_dag()` validates:

- globally unique artifact IDs;
- parent existence;
- duplicate/self parents;
- directed cycles;
- deterministic topological order, roots and leaves.

Campaign validation spans all cycle jobs, so the cross-cycle Growth seed edge is included. The final `campaign_report` artifact depends on each cycle's analytics artifact and is also DAG-validated.

## Campaign report artifact

The final report records:

- attempts by stage;
- retry count derived from persisted logical idempotency attempts;
- critic reject count;
- artifact counts by kind;
- cycle transition count;
- duplicate analytics events suppressed;
- persisted render fingerprints;
- validated simulated Growth feedback per cycle;
- lineage node/edge/root/leaf summary.

## Deterministic demo

Run:

```bash
PYTHONPATH=src python -m creator_orchestrator.demo \
  fixtures/campaign.autonomous.v2.json \
  /tmp/creator-round2-demo \
  --output /tmp/creator-round2-report.json
```

The checked-in expected output is `fixtures/campaign.autonomous.v2.expected.json`.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Round-2 tests cover deterministic multi-cycle completion, reconstruction before every stage, four named recovery scenarios, all eight injected failure stages, bounded critic revisions, provider fake idempotency, dry-run-only queueing, duplicate analytics handling, lineage cycle detection, and expected demo output.
