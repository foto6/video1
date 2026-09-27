# Durable External Operation Handoff

## Goal

This handoff closes the normal restart gap between a Creator stage submitting asynchronous provider work and committing that provider result into Creator artifact lineage.

It is additive to the existing nine-stage state machine. Synchronous adapters keep the original `Adapter.execute(context)` contract and do not need synthetic asynchronous behavior.

## Creator-owned receipt states

For an adapter that structurally implements `ResumableAdapter`, Creator persists a receipt under the existing stage idempotency key:

1. **prepared** — immutable submission payload persisted; no accepted external handle is known.
2. **accepted** — a stable external operation handle has been persisted.
3. **result_obtained** — a provider result has been read and the complete `StepResult` is durable locally, but artifacts are not yet committed to the job.
4. **committed** — the stage result has been committed to job artifact lineage and the stage transition is durable.

`JsonOperationLedger` uses fsync plus atomic replacement, independently from the job JSON file but keyed by the same Creator job/stage/idempotency tuple.

## Submit/resume behavior

Creator owns only submission/resume orchestration:

- persist the prepared request;
- submit when no accepted handle exists;
- persist the returned stable handle immediately;
- on restart, poll/read that same handle;
- persist the obtained `StepResult`;
- commit that result through the normal artifact/evaluation/stage path;
- mark the receipt committed after the job commit.

After an accepted handle is durable, Creator never calls submit again for that logical stage operation. A restart at `accepted` resumes by read-only polling. A restart at `result_obtained` commits the durable result without another provider call.

If the job commit succeeds but the receipt's final `committed` marker is interrupted, the next `run_next` reconciles completed stage idempotency keys and advances the receipt to `committed`.

## Idempotent provider submission

There is an unavoidable machine-level interval between a remote system accepting a submit request and Creator persisting the returned handle. Therefore a resumable provider integration must accept the Creator stage idempotency key on submission and make repeated submission of the same key return the same logical operation rather than creating duplicate side effects.

That provider-side idempotency is distinct from provider-internal transport/retry behavior. Creator does not own the provider's internal retries.

## Poll/resume policy

`OperationResumePolicy` bounds Creator read/resume attempts. Pending results and polling timeouts leave the job in `waiting_retry` with the accepted handle intact.

This policy is deliberately separate from the existing `RetryPolicy`, which remains the bounded retry policy for ordinary synchronous stage adapters. A polling timeout therefore does not consume or trigger synchronous provider retry semantics.

## Protocol-neutral Media bridge

`GenericResumableMediaAdapter` is a Creator-local bridge over the generic `ResumableOperationClient` shape:

- `submit_operation(request, idempotency_key=...)`
- `read_operation(external_operation_id)`

These method names are not a video2 runtime contract. They exist only to prove the Creator durable handoff while Media's durable runtime protocol evolves.

The submitted planning payload is still exactly the frozen `media.render.v1` request with `dryRun: true`. The existing synchronous `MediaRenderPlanAdapter` and Round-1 fixtures remain unchanged.

## Recovery proof

`tests/test_external_operation_recovery.py` covers:

- crash after `prepared` but before submit;
- crash after accepted handle persistence;
- crash after successful result persistence but before artifact commit;
- duplicate resume with multiple read-only polls;
- provider polling timeout and restart;
- conflicting request reuse under the same stage idempotency key;
- fresh local store/orchestrator reconstruction at each boundary;
- exact `media.render.v1` dry-run request shape.

The fake resumable Media client counts one accepted side-effect submission and permits any number of read-only polls. Reusing a key with different request bytes fails closed.

## Publishing safety

This mechanism adds no publishing capability. The autonomous campaign simulator remains queue-only, `RealPublishingDisabled` remains enforced, and the resumable Media bridge is planning-only with `dryRun: true`.
