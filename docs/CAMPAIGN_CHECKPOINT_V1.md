# CampaignCheckpoint v1

## Purpose

`creator.campaign_checkpoint.v1` is Creator's canonical production checkpoint/export format. It is designed for reproducible campaign recovery, not long-horizon chaos testing.

The bundle captures only durable facts required to reproduce and resume a campaign:

- campaign identity and current cycle index;
- canonical campaign configuration and durable campaign state;
- every durable Creator job and fixed nine-stage record;
- immutable Growth seed ledger records and seed identities;
- external-operation receipts;
- accepted `media.job.v1` job identities;
- immutable artifact lineage;
- analytics handoff identities;
- exact producer-fixture provenance;
- content hashes for all major sections and the whole bundle.

It does not contain process IDs, locks, in-memory caches, wall-clock receipt timestamps, provider credentials, or transient runtime state.

## Canonical content addressing

Canonical JSON uses UTF-8, sorted object keys, compact separators, no NaN/Infinity, and a trailing newline for serialized checkpoint files.

`checkpointHash` is the SHA-256 of the complete canonical bundle body excluding the `checkpointHash` field itself.

Each checkpoint also contains:

- campaign config hash;
- per-job durable-state hashes;
- durable stage-record hash;
- Growth seed-record hash;
- external-operation receipt hash;
- artifact-lineage hash;
- analytics-handoff hash;
- producer-pin hash.

Job `created_at`/`updated_at` and operation receipt wall-clock timestamps are deliberately excluded because they do not affect execution semantics and would make equivalent restores non-reproducible. Immutable artifact timestamps remain part of artifact identity/provenance.

Artifact records carry explicit ordinal values. Canonical validation rejects reordered job, stage, Growth, receipt, Media, lineage, analytics, or producer-pin records even if a caller recomputes the outer checkpoint hash.

## Growth seed identity

Exact Growth handoff rows from `JsonGrowthSeedLedger` are preserved as `growthSeedRecords`. `growthSeedIdentities` records:

- producer `idempotencyKey`;
- seed digest;
- immutable artifact ID;
- Growth `batchId`;
- identity source.

If a job contains an exact `growth_feedback_batch` artifact, its identity must agree with the ledger. Conflicting seed identities fail closed.

The checkpoint does not weaken existing `growth.creator_seed.v1` validation or CreatorFeedback `1.0`.

## Durable stage records

Each job stores the artifact sequence exactly, with an explicit ordinal, plus attempts, logical idempotency attempts, completed stage keys, evaluations, current stage index and state.

The top-level `stageRecords` section provides one record for every stage in the existing nine-stage order:

`research -> idea -> script -> assets -> voice -> edit -> critic -> publish_queue -> analytics`

A checkpoint import reconstructs the existing `JsonJobStore` representation rather than introducing a second orchestration state machine.

## External operations and Media identity

External-operation receipts preserve:

- Creator job/stage/idempotency identity;
- adapter identity;
- `prepared | accepted | result_obtained | committed` state;
- canonical submit request and request fingerprint;
- accepted external operation handle;
- durable acceptance metadata;
- poll count and last poll/reconciliation metadata;
- durable obtained result when present.

Receipt wall-clock timestamps are normalized away in the checkpoint and restored to a fixed non-semantic timestamp.

For concrete `media.job.v1` receipts at or beyond `accepted`, `acceptedMediaJobs` additionally binds:

- Creator stage idempotency;
- Media `jobId`;
- Media `idempotencyKey`;
- receipt state;
- request fingerprint.

The accepted external handle must equal the submitted Media `jobId`.

### Resume invariant

Import preserves the existing receipt state exactly. The existing Orchestrator recovery rule therefore remains authoritative:

- `prepared`: submission may occur because durable state proves no accepted handle exists;
- `accepted`: Creator may only poll/resume the same external operation;
- `result_obtained`: Creator commits the durable result without provider submission/poll;
- `committed`: no provider side effect is repeated.

Focused tests export an already-accepted `media.job.v1` operation, restore it into a fresh local store, and prove the same provider job is polled with submit count remaining exactly one.

Media remains owner of render/probe/QA/finalization retries.

## Artifact lineage and analytics identity

Every committed campaign artifact, plus a terminal campaign report artifact when present, contributes to `artifactLineage`.

Each lineage record binds:

- artifact ID;
- kind;
- producer;
- ordered parent IDs;
- canonical artifact hash.

The complete lineage must form a valid DAG. Missing artifacts, unknown parents, duplicate IDs, cycles, or altered artifact hashes fail validation.

Analytics handoffs record analytics artifact ID, canonical artifact hash, and sorted event IDs.

## Producer provenance

Checkpoint export/import validates `fixtures/upstream/manifest.json` against the actual copied bytes.

Current frozen pins remain:

- Growth `foto6/video3@5c38b8844e91cc8e4f82ccf5e1aa135d32204b36`
  - fixture Git blob `6c663665313cacd10a34f84af153b2546a8dc2c0`
  - SHA-256 `58e100ab79b8a52b0f1286dc0af2c83179fc918b40d82808731f234046839224`
- Media `foto6/video2@cc542d626622c780fba2d03d094815d3dca240f9`
  - fixture Git blob `678042975df835d258a249d3ec235d6f06b8c089`
  - SHA-256 `02d6d0cc39ef746974c91cba54dfe2e84477bf68fd014cccd18525bc2f739cae`

No sibling repository is imported at runtime.

## Export/import/resume APIs

Public package APIs:

- `export_campaign_checkpoint(...)`
- `write_campaign_checkpoint(...)`
- `load_campaign_checkpoint(...)`
- `validate_campaign_checkpoint(...)`
- `import_campaign_checkpoint(...)`
- `resume_campaign_from_checkpoint(...)`
- `validate_producer_pins(...)`
- `compute_checkpoint_hash(...)`
- `build_reproducibility_report(...)`

Importing the same checkpoint into the same destination is an idempotent `duplicate`. A different checkpoint/config for an existing campaign fails closed rather than overwriting durable state.

## Migration policy

Version policy is exact-only:

- current supported version: `creator.campaign_checkpoint.v1`;
- any unknown/future version is rejected;
- no field dropping;
- no best-effort downgrade;
- no silent migration.

A future checkpoint version must ship an explicit, tested migration tool before Creator accepts it.

## Secret policy

Checkpoint export recursively rejects secret-like fields such as passwords, authorization headers, API keys, access/refresh tokens, cookies, or credentials. It also rejects common token-bearing URL/string patterns.

Secrets are never redacted into a different execution payload because that would make a supposedly reproducible checkpoint lossy. Export fails instead.

## Deterministic fixture bundle

`scripts/generate_checkpoint_fixtures.py` generates:

- `00_created.checkpoint.json`
- `01_research.checkpoint.json`
- `02_idea.checkpoint.json`
- `03_script.checkpoint.json`
- `04_assets.checkpoint.json`
- `05_voice.checkpoint.json`
- `06_edit.checkpoint.json`
- `07_critic.checkpoint.json`
- `08_publish_queue.checkpoint.json`
- `09_analytics.checkpoint.json`
- `10_terminal.checkpoint.json`

under `fixtures/checkpoints/`.

The source campaign is `fixtures/campaign.checkpoint.v1.source.json`.

Running the generator twice without code/fixture changes produces byte-identical files.

## Reproducibility report

`fixtures/checkpoints/reproducibility_report_v1.json` is machine-readable and contains every fixture checkpoint hash, intermediate lineage hash, job state hashes, final checkpoint hash, final lineage hash and producer-pin hash.

Property tests restore every boundary checkpoint into a fresh state root, continue execution, export again, and require the exact same terminal checkpoint hash and final lineage hash as uninterrupted execution.

## Safety

Checkpointing does not add publishing capability. The simulator remains queue-only, `RealPublishingDisabled` remains enforced, critic/revision behavior is unchanged, and existing exact Growth/Media integration continues to use the current frozen contracts.
