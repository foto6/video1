# Creator R33 exactly-once publish transaction

R33 adds `creator.publish_transaction.r33.v1`, a provider-neutral crash-safe transaction layer between an R32 winner handoff and the existing Instagram Reels, TikTok Direct Post, and YouTube Shorts provider adapters.

This milestone does **not** perform a real publish and does not make provider-network calls.

## Exact upstream authority

Every transaction freezes Creator R32 at:

- SHA `f0dc1d27da6452f1de32cd887651805b47a1735d`
- CI `37199512624 SUCCESS`
- artifact ID `11302367811`
- artifact digest `sha256:6803db334974b8dbea1c30c107ec5af00fe2cb892ed67e68540c2b2d74b18599`
- contract `creator.autonomous_tournament.r32.v1`
- exact R32 runtime/schema/manifest/authority-profile blob identities
- exact existing `creator.editor_publish_handoff.v1` schema/manifest/runtime blobs

A changed SHA, CI/artifact identity, contract binding, winner handoff, source/session/tournament/round, candidate, consensus, or final MP4 identity fails closed.

## Transaction states

The durable state machine is:

`PREPARED -> VALIDATED -> COMMIT_ELIGIBLE -> COMMITTING -> COMMITTED`

Unknown provider outcome changes `COMMITTING` to `RECONCILIATION_REQUIRED`. `PREPARED` or `VALIDATED` can be `ABORTED`. An unknown side effect cannot be relabeled aborted. If read-only reconciliation proves provider absence, the transaction returns to `COMMIT_ELIGIBLE` and may then be explicitly retried or aborted under the durable absence proof.

Required validation cannot be skipped.

## Immutable transaction identity

A transaction binds:

- final `final.mp4` SHA-256 and byte size;
- source/session/tournament/review-round/winner/consensus/publish-handoff lineage;
- the exact R32 authority above;
- provider adapter, platform, account reference, destination and opaque credential/config/authorization references;
- hashes of caption, title and thumbnail;
- publish-policy hash;
- provider metadata digest;
- planned publish-time metadata;
- stable transaction ID and idempotency key.

The dry-run provider request is canonical JSON and its digest is durable. The same key plus changed winner, caption, provider, configuration or schedule is a hard conflict.

Changing the schedule after prepare uses `schedule_revision_spec()`, which emits an explicit revision, parent transaction, new transaction ID and new idempotency key. It never mutates a committed identity.

## Provider metadata validation

R33 freezes the constraints implemented by the current Creator production adapters:

- common Creator short-form profile: MP4, exact 9:16, 15–60 seconds, H.264/HEVC-family video;
- Instagram: <=1 GiB, 23–60 fps, width <=1920, AAC/no audio, public HTTPS media URL, profile/account destination binding;
- TikTok: <=4 GiB, 23–60 fps, dimensions 360..4096, public HTTPS pull URL, privacy destination;
- YouTube: <=256 GiB and public/private/unlisted privacy destination.

R33 validates these locally. It does not contact accounts or provider APIs. Configuration availability is represented only by opaque non-secret references.

## Commit safety

`begin_commit()` persists `COMMITTING` before any adapter call. The durable commit record includes an attempt number and stable attempt ID.

Immediately before a fake-provider dispatch, R33 persists a provider-invocation intent. Therefore:

- a crash at the `COMMITTING` boundary while `invocationStarted=false` is safe to resume;
- a restart after invocation intent is conservatively routed to reconciliation, even if the actual provider call may not have happened;
- a caught timeout known to occur before dispatch returns to `COMMIT_ELIGIBLE`;
- timeout after dispatch becomes `RECONCILIATION_REQUIRED`;
- no commit call is allowed from `RECONCILIATION_REQUIRED`;
- a `COMMITTED` transaction returns durable state without invoking the adapter again.

This milestone accepts only `FakeProviderHarness` adapters. A non-fake adapter raises `LivePublishForbidden`.

## Reconciliation

Provider-side operation/post IDs are stored only after an authoritative proof is validated against transaction ID, idempotency key and request digest.

Read-only lookup may prove:

- committed / duplicate-confirmed -> `COMMITTED`;
- authoritative absence -> `COMMIT_ELIGIBLE`;
- unknown / unsupported lookup -> remain `RECONCILIATION_REQUIRED`.

Unknown outcome never causes blind submit retry.

## Multi-platform isolation

Instagram, TikTok and YouTube are independent child ledgers. `batch_status()` separates committed, blocked/reconciliation-required and aborted children. One child's failure never authorizes a second effect on another child.

## Deterministic fake-provider rehearsal

The harness covers:

- clean success;
- timeout before dispatch;
- timeout after dispatch + successful read-only reconciliation;
- duplicate/already-exists confirmed;
- unknown with no lookup.

Run:

```bash
creator-publish-transaction-r33 readiness
creator-publish-transaction-r33 rehearsal --out .r33-rehearsal
creator-publish-transaction-r33 status --ledger .r33-rehearsal/tiktok.jsonl
```

The rehearsal commits one fake Instagram transaction, reconciles one fake TikTok timeout-after-dispatch, leaves one fake YouTube transaction blocked because outcome cannot be proven, and proves a known timeout-before-dispatch can be retried safely. It records zero real-provider effects, no network use and no credentials.

Readiness is always `SOURCE_READY_NO_LIVE_PUBLISH` for R33.
