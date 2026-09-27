# release.authorization.v1

## Boundary

Creator may prepare a release candidate and an approval request after a campaign is complete and a queue-only release artifact exists. Creator cannot approve that request itself.

No release adapter call is permitted unless Creator has durably recorded a matching external `release.authorization.v1` approval that is still valid at the final authorization check.

This milestone does not enable live publishing. The only executable release adapter is the local, idempotent `FakeLocalReleaseAdapter` with `execution_mode = "local-simulated"`. Any other execution mode fails before adapter invocation.

## Immutable candidate binding

A release candidate binds:

- campaign ID;
- completed Creator job ID;
- queued release artifact ID;
- canonical SHA-256 of that immutable artifact;
- canonical SHA-256 of the entire completed campaign lineage;
- exact destination scope;
- creation timestamp;
- content-addressed candidate ID.

The campaign-lineage hash covers all non-release artifacts from every cycle job plus the campaign report artifact. Release approval/receipt artifacts are excluded so recording an approval cannot mutate the object being approved.

The destination scope is exact:

`{provider, destination, action: "release"}`

Any scope change produces a different binding and is rejected against an existing approval.

## Approval request

Creator-generated `release.approval_request.v1` is deterministic from the candidate identity. It contains no approval decision.

The request is durably committed before any decision can be recorded. Repeating the same candidate/scope returns the same request.

## Explicit external decision

`release.authorization.v1` is strict and rejects unknown versions or extra fields.

Fields:

- `contractVersion`
- `decisionId`
- `idempotencyKey`
- `requestId`
- `campaignId`
- `candidateId`
- `artifactId`
- `artifactHash`
- `lineageHash`
- `destinationScope`
- `decision`
- `authorizationId`
- `expiresAt`
- `decidedAt`
- `decisionSource`
- `approverRef`

`decisionSource` must be exactly `external`. Creator exposes validation/recording APIs but no function that synthesizes an approval.

Allowed decisions are:

- `approved`: creates an active authorization and requires a future expiry;
- `denied`: terminal deny decision with null authorization/expiry;
- `revoked`: revokes the active authorization ID while preserving its immutable expiry/binding.

Identical repeats of the same decision idempotency key are no-ops. Reusing a decision idempotency key with different bytes fails closed.

## Durable ledger

`ReleaseAuthorizationLedger` is an append-only logical event ledger stored under `release-authorizations/`.

Durable events are:

1. `candidate_prepared`
2. `approval_requested`
3. `decision_recorded`
4. optional `dry_run_planned`
5. optional `dry_run_completed`
6. `execution_prepared`
7. `receipt_committed`

Each event has a contiguous sequence number and canonical event digest. The ledger is rewritten atomically with fsync.

Every event is mirrored as an immutable `release_*` artifact on the completed Creator job. If a process stops after the ledger write but before the job artifact write, the next ledger operation re-synchronizes missing lineage artifacts.

States derived from the event ledger are `pending`, `approved`, `denied`, and `revoked`. Execution state is independently `none`, `prepared`, or `committed`.

## Final authorization check

Before any simulated release side effect, Creator recomputes:

- the exact queued artifact hash;
- the complete campaign lineage hash;
- destination scope;
- active authorization binding;
- expiry at caller-supplied current time.

The call fails closed if any binding changed, approval is absent/denied/revoked/expired, scope differs, or the adapter is not local-simulated.

Creator persists `release.execution_prepared.v1` with a stable execution idempotency key before invoking the local adapter.

## Side-effect idempotency

The local adapter receives the stable release execution idempotency key.

If a process stops after the simulated side effect but before Creator commits its receipt, retry calls the adapter with the same key. The fake returns the same logical operation and does not increment its accepted side-effect count.

After `release.side_effect_receipt.v1` is committed, later calls return the durable receipt without invoking the adapter again.

This gives at most one accepted simulated side effect and one committed receipt per authorized logical release, including crash recovery.

## Dry-run contract

Dry-run never calls a release adapter.

`release.dry_run_plan.v1` binds the same candidate hash, campaign lineage and destination scope and declares `externalSideEffects: false`.

`release.dry_run_result.v1` records the current approval state and `externalSideEffects: 0`.

The deterministic reference is:

`fixtures/release.authorization.v1.dry_run.expected.json`

Repeated construction with the same fixed timestamp produces exactly the same plan/result hashes.

## CampaignCheckpoint v1 integration

The existing `creator.campaign_checkpoint.v1` top-level schema is unchanged.

Authorization lineage is exported through the job's immutable release artifacts and therefore participates in the existing job-state hashes and `artifactLineage` hash. Checkpoint validation semantically validates release event digests, sequence, request/candidate binding and decision state.

On import, Creator scans restored release lineage artifacts and rebuilds `release-authorizations/`. Pending, approved and revoked states are therefore preserved without adding transient process state to the checkpoint.

An approved checkpoint can resume through the restored authorization; Creator does not manufacture a new approval during import.

## Fault boundaries

Focused tests cover restart after:

- durable approval-request creation;
- durable approval decision commit;
- final authorization check / execution preparation;
- simulated side effect before receipt commit;
- receipt commit.

They also cover artifact mutation, wrong destination scope, expiry, revocation, external-input enforcement, conflicting decision idempotency, strict version/field rejection, live-adapter rejection and checkpoint round trips.

## Existing safety invariants

The existing queue stage remains `queue_only` / dry-run. `RealPublishingDisabled` is unchanged. Growth, Media, critic/revision, CampaignCheckpoint v1, and all existing simulator contracts remain intact.
