# Exact Growth -> Creator -> Media Durable Integration

## Frozen producer inputs

Wave 4 consumes producer contracts directly from the pinned heads below. Creator does not import either sibling repository at runtime.

- Growth: `foto6/video3@5c38b8844e91cc8e4f82ccf5e1aa135d32204b36`
  - handoff: `growth.creator_seed.v1`
  - producer batch model: `growth.feedback_batch.v1`
  - source fixture: `fixtures/creator_next_cycle_seed_v1.json`
  - Git blob: `6c663665313cacd10a34f84af153b2546a8dc2c0`
  - SHA-256: `58e100ab79b8a52b0f1286dc0af2c83179fc918b40d82808731f234046839224`
- Media: `foto6/video2@cc542d626622c780fba2d03d094815d3dca240f9`
  - transport: `media.job.v1`
  - embedded planning request: `media.render.v1`
  - source fixture: `fixtures/creator-media/media.job.v1.consumer.json`
  - Git blob: `678042975df835d258a249d3ec235d6f06b8c089`
  - SHA-256: `02d6d0cc39ef746974c91cba54dfe2e84477bf68fd014cccd18525bc2f739cae`

Copied bytes and metadata live under `fixtures/upstream/`; `manifest.json` is the local provenance manifest.

## Growth consumer

`validate_growth_creator_seed()` strictly validates the exact `growth.creator_seed.v1` vocabulary. It preserves CreatorFeedback `1.0`, canonical order, observational/non-causal interpretation, producer payload digest, and the producer's `fb1:` batch identity derivation.

`JsonGrowthSeedLedger` owns Creator-side exactly-once seed persistence. The producer `idempotency_key` is the durable key. An identical replay returns the same immutable artifact without appending a second row. Reusing the key with changed payload bytes fails closed.

The persisted artifact kind is `growth_feedback_batch`. It can be passed directly to `Orchestrator.create_job()`, which now accepts already-persisted immutable artifacts in addition to existing `SeedArtifactInput` values.

## Media job consumer

`MediaJobV1ResumableAdapter` is the concrete Creator consumer for the frozen `media.job.v1` transport.

Exact action shapes:

- submit: `{contractVersion, action, idempotencyKey, request}`
- status: `{contractVersion, action, jobId}`
- resume/poll: `{contractVersion, action, jobId}`
- cancel: `{contractVersion, action, jobId, reason}`

The embedded request remains exact `media.render.v1`. The older planning-only `MediaRenderPlanAdapter` is unchanged, and `GenericResumableMediaAdapter` remains available for backward compatibility.

Creator supplies both the stable `idempotencyKey` and stable logical Media `jobId`. Once Media acceptance is durable, Creator only issues `status`, `resume_or_poll`, or `cancel` against that same job. Creator does not implement render, process, probe, QA, or finalization retries; the response must report `retryOwner: "media"`.

If the submit response times out after Media may have accepted the request, Creator persists the already-known requested `jobId` as the uncertain accepted handle and polls that job rather than creating or submitting a fresh Media job.

The only irreducible crash window is after Media accepts the submit but before Creator can persist the returned receipt. Recovery resends the exact same submit envelope with the same idempotency key and job id. Media idempotency must return the same job; the fake gate proves the accepted render side effect remains one.

## Final artifact rule

A live `succeeded` Media response must contain exactly `finalArtifact {outputPath,size,sha256}`. Creator records it as `media_final_artifact` with `qaPassed: true`, Media-owned retry telemetry, and parent lineage through the exact Media job request artifact.

Dry-run success records a planning artifact and does not manufacture a final artifact.

## Deterministic integration gate

`run_exact_growth_creator_media_gate()` performs a deterministic two-cycle boundary scenario:

1. consume the committed Growth cycle-N seed;
2. replay it and prove Creator persists one seed for that key;
3. run cycle N+1 Creator research/idea/script/assets/voice;
4. submit one Media job and persist its accepted job id;
5. crash/restart Creator;
6. observe a pending Media job, then resume/poll the same job;
7. accept Media's QA-final artifact, including Media-owned retry telemetry;
8. run critic, queue-only publish staging, and analytics;
9. derive a simulation-only next Growth handoff from analytics and persist that next distinct seed;
10. validate the campaign DAG across prior analytics -> Growth seed -> Creator artifacts -> Media final artifact -> analytics -> next Growth seed.

Expected deterministic output is frozen at `fixtures/exact_growth_creator_media_gate_v1.expected.json`.

## Fault matrix

`tests/test_exact_growth_creator_media.py` covers:

- identical Growth replay and restart;
- conflicting Growth key reuse;
- crash after Creator seed commit and replay;
- crash after Media accepted work but before acceptance receipt persistence;
- crash after acceptance receipt persistence;
- caller response timeout after Media acceptance;
- exact status/pending observation and repeated resume/poll;
- restart after Media success before artifact commit;
- conflicting Media idempotency key;
- cancel race;
- exact producer fixture hashes;
- deterministic end-to-end lineage gate.

The earlier generic resumable adapter/recovery tests remain in place to preserve compatibility.

## Safety

No social publishing or account mutation is added. Metricool remains queue/dry-run only, `RealPublishingDisabled` remains enforced, and no merge behavior is introduced.
