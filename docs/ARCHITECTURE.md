# Creator Orchestrator Architecture

## Scope

The MVP is a provider-neutral control plane for:

`research -> idea -> script -> assets -> voice -> edit -> critic -> publish queue -> analytics feedback`

It deliberately does **not** publish content. The publish stage emits a queue manifest and the Metricool adapter refuses non-dry-run execution.

## Durable state machine

`Job` persists the current stage index, attempts, artifacts, evaluations, errors, and completed idempotency keys. `JsonJobStore` writes each update through fsync plus atomic replace, so a process restart can resume from the durable record.

Stage transitions are monotonic. A stage result is evaluated, merged into artifact lineage, marked with its idempotency key, and only then advances the stage index.

## Idempotency and retries

Each logical stage receives a stable SHA-256 idempotency key derived from job id, stage, and prior artifact lineage. Provider clients are required to use that key for deduplication. Retryable failures enter `waiting_retry`; attempt counters survive restarts. Exhausted or non-retryable failures become terminal.

The MVP cannot provide distributed exactly-once semantics across an external provider and the local store. The adapter boundary makes this explicit: providers must implement their own idempotent request semantics using the supplied key.

## Artifact lineage

Every output is an immutable `Artifact` with producer, URI, metadata, and parent artifact IDs. This allows downstream outputs and critic/evaluation records to be traced back to source research, scripts, assets, voice, and edits.

## Evaluation hooks

Evaluation hooks run after a stage returns and before the state transition is committed. Hooks can attach score/notes and reject progress. The `critic` remains a first-class pipeline stage, while hooks support cross-cutting policy or quality checks.

## Provider boundaries

- **Runway**: `RunwayClient` / `RunwayAssetAdapter`
- **Descript**: `DescriptClient` / voice and edit adapters
- **Metricool**: `MetricoolClient` / queue-only publish adapter
- **vidIQ**: `VidIQClient` / research and analytics adapters

No SDK is imported by the orchestration core. Clients can be implemented via MCP, HTTP APIs, local services, or test doubles without changing state-machine logic.

## Safe publishing posture

Real publishing is disabled in code. `MetricoolPublishQueueAdapter(dry_run=False)` raises `RealPublishingDisabled`. The default assembly has no provider clients attached and creates deterministic dry-run artifacts only.

## Recovery model

A process can reload a job from disk and call `run_next` again. A retryable provider failure preserves attempt count and stage. Terminal jobs are no-ops on repeated execution.
