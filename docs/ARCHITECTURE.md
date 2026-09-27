# Creator Orchestrator Architecture

## Scope

The Creator Orchestrator is a provider-neutral control plane for:

`research -> idea -> script -> assets -> voice -> edit -> critic -> publish queue -> analytics feedback`

The nine-stage order remains authoritative. Real publishing is disabled; the publish stage is queue/dry-run only.

## Durable job state

`Job` persists stage index, aggregate stage attempts, per-idempotency-key attempts, completed idempotency keys, artifacts, evaluations and errors. `JsonJobStore` uses fsync plus atomic replacement so a restart can resume a job without replaying earlier completed stages.

Per-idempotency-key attempt counts bound transient retries independently from aggregate stage attempts. This matters for critic revisions: rewinding a successful stage creates a new logical idempotency key without consuming the retry budget of the earlier revision.

## Round-1 seed and Media contracts

Optional immutable seed artifacts are created before stage 0 and therefore participate in stage-0 idempotency lineage.

Supported seed kinds:

- `growth_feedback`: strict Growth `CreatorFeedback` with `contract_version: "1.0"`.
- `media_timeline_v1`: caller-supplied timeline with `version: 1`.

Creator never synthesizes missing timeline durations or source metadata. The opt-in `MediaRenderPlanAdapter` sends exactly the frozen B2 request fields for `media.render.v1` with `dryRun: true`. Media remains authoritative for timeline validation and render fingerprinting.

## Autonomous Content Cycle Simulator v2

Round 2 adds a separate deterministic campaign runtime rather than replacing the default pipeline.

`CampaignRunner` executes multiple sequential Creator jobs. Cycle N analytics are deduplicated into a validated Growth 1.0 payload that becomes a `growth_feedback` seed for cycle N+1. The next-cycle seed has a parent edge to the prior `analytics_feedback` artifact, allowing campaign-wide lineage validation across job boundaries.

`JsonCampaignStore` persists current cycle, job IDs, completed cycles, feedback payloads, handled critic decisions, analytics event digests and the final report artifact. `CampaignRunner.step()` performs at most one durable transition/stage attempt, so the process can be reconstructed between any two stages.

### Bounded revisions

Critic decisions are immutable `critic_decision` artifacts. A reject can rewind to a configured pre-critic stage. Historical artifacts are never deleted. `maxCriticRevisions` bounds the loop and turns excess rejects into a terminal campaign failure.

### Failure injection

The simulator can inject retryable failures in research, script, assets, voice, media, critic, queue and analytics. Injection uses persisted aggregate stage-attempt numbers, so restart does not repeatedly reproduce a first-attempt failure.

### Provider harnesses

Local deterministic fakes cover Runway, Descript, Metricool, vidIQ and Media Engine. Runway/Descript/Metricool/vidIQ fakes enforce stable idempotency semantics. The Media fake accepts only the exact `media.render.v1` six-field dry-run request and returns a deterministic render fingerprint.

### Publishing safety

There is no live-publishing field in the simulator contract. Unknown campaign/media fields fail closed. Queue execution always uses `action=queue_only` and `dry_run=True`; `FakeMetricool` rejects any other mode. Existing `RealPublishingDisabled` behavior is retained.

## Artifact lineage

Artifacts are immutable. `validate_artifact_dag()` verifies unique IDs, parent existence, duplicate/self-parent errors and cycles, and returns deterministic roots/leaves/topological order. Round-2 campaign validation spans all cycle jobs and the final campaign report.

## Campaign report

The final `campaign_report` artifact records stage attempts, retries, critic rejects, artifact counts, cycle transitions, duplicate analytics suppressions, render fingerprints, simulated performance feedback and a lineage summary.

## Recovery model

- Job state survives restart at every stage.
- Retry state is keyed by the stable logical idempotency key.
- Critic rewind state is derivable from persisted critic artifacts plus campaign handled-decision IDs.
- Cycle transition state and Growth feedback are persisted before the next job is created.
- Terminal job/campaign states are idempotent on repeated execution.

See `docs/AUTONOMOUS_CYCLE_SIMULATOR_V2.md` for the deterministic demo and test matrix.


## Durable external-operation handoff

Resumable asynchronous adapters use the same stage idempotency key plus a `JsonOperationLedger` receipt with `prepared`, `accepted`, `result_obtained`, and `committed` states. Once an accepted external handle is persisted, restart paths poll that handle rather than resubmitting the logical operation. A durable provider result can be committed after restart without another provider call.

This is opt-in through the structural `ResumableAdapter` protocol; ordinary synchronous adapters retain `execute(context)` unchanged. Creator's `OperationResumePolicy` bounds read-only polling/resume attempts separately from the existing synchronous `RetryPolicy`. Provider-internal retry policy remains provider-owned.

The protocol-neutral `GenericResumableMediaAdapter` demonstrates the handoff while continuing to submit the frozen `media.render.v1` planning request with `dryRun: true`. Its generic submit/read client shape is not a video2 runtime contract. See `docs/EXTERNAL_OPERATION_RECOVERY.md`.


## Exact Growth -> Creator -> Media durable integration

Wave 4 pins the current Growth `growth.creator_seed.v1` and Media `media.job.v1` producer contracts. Creator consumes Growth batch identity exactly once through `JsonGrowthSeedLedger` and uses `MediaJobV1ResumableAdapter` for exact submit/status/resume_or_poll/cancel transport. Media remains retry owner for render/process/probe/QA/finalization.

The existing `media.render.v1` planning adapter and generic resumable adapter remain backward compatible. Cross-repo fixture provenance and the deterministic two-cycle gate are documented in `docs/EXACT_GROWTH_CREATOR_MEDIA_DURABLE_INTEGRATION.md`.


## Reproducible campaign checkpoint/export

Wave 6 adds the exact-only `creator.campaign_checkpoint.v1` format. It canonicalizes durable campaign/job/stage state, Growth seed identities, external-operation receipts, accepted Media jobs, artifact DAG and analytics identities while excluding process timestamps and failing closed on provider-secret fields. Import is idempotent for an identical checkpoint and refuses conflicting campaign identity. Restored accepted Media receipts continue the existing same-handle poll/resume rule and cannot resubmit unless the receipt proves the operation remained only `prepared`.

See `docs/CAMPAIGN_CHECKPOINT_V1.md` and `fixtures/checkpoints/reproducibility_report_v1.json`.


## Durable human release approval

Wave 7 adds `release.authorization.v1` as a post-campaign release boundary. Creator can prepare a content-addressed candidate/approval request but only explicit external decisions can enter the authorization ledger. Final execution rechecks artifact hash, complete campaign lineage, scope, expiry and revocation before permitting a local-simulated adapter call.

Release ledger events are mirrored into immutable job artifacts, so the existing CampaignCheckpoint v1 schema exports authorization lineage without adding provider secrets or transient state. Checkpoint import rebuilds pending/approved/revoked ledger state from those artifacts. Live release adapters remain disabled.
