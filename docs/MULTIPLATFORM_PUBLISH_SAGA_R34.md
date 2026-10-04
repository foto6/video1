# Creator R34 multi-platform publish saga

R34 orchestrates one approved short-form winner across Instagram Reels, TikTok and YouTube Shorts while preserving R33 exactly-once safety independently for each platform.

Independent QA-R3 has now accepted the exact R33 parent as `PUBLISH_TRANSACTION_SOURCE_READY`. R34 therefore binds that parent acceptance and reports `SOURCE_READY_PENDING_R34_QA`. R34 itself is **not** independently accepted and is never labeled LIVE_READY.

## Frozen parent

R34 freezes the parent candidate at:

- Creator R33 SHA `9556108f423a15a40614a8bc9d590e6dc2e49746`
- CI `37203622591 SUCCESS`
- artifact ID `11304071297`
- artifact digest `sha256:adbfb6d257332220e2be2f9d8f134a87f8bcc6b6e064dfac7f469fd95d690d6d`
- child contract `creator.publish_transaction.r33.v1`

Independent parent acceptance is frozen to:

- QA repo `foto6/boss`
- exact QA SHA `2a48c909bfb5785409b591253f6085642b962d0d`
- exact QA CI `37207701514 SUCCESS`
- QA artifact `11305557095`, `hard-wave-acceptance-r3-2a48c909bfb5785409b591253f6085642b962d0d`
- QA artifact digest `sha256:4c5cb2c476643a03865ec37c084650db4c98c84c3aed04aafeb35b81b4e9fba0`
- disposition `ACCEPTED / PUBLISH_TRANSACTION_SOURCE_READY`
- QA status blob `4e71a7a46ddb71031b7a6aa622efaa63209fef02`
- QA authority fixture blob `68f304b786df348d72a44be5baced1c1f3aa3d8c`
- QA runtime/tests blobs `34f8be83d8c9e50ee2e4127d04aba66b8c943fd2` / `b9e329132bc68616874e5d43cb8a81da261ba7b9`

The checked-in `parent-qa-r3-acceptance.json` is an exact source-bound acceptance record. Any changed QA SHA, CI run, artifact ID/digest, QA blob pin, or different R33 authority fails closed.

It also consumes the exact R32 winner/publish-handoff authority already frozen by R33.

## Durable structure

The saga contract is `creator.multiplatform_publish_saga.r34.v1`.

Each platform owns an independent R33 append-only transaction ledger:

`PREPARED -> VALIDATED -> COMMIT_ELIGIBLE -> COMMITTING -> RECONCILIATION_REQUIRED | COMMITTED | ABORTED`

The saga ledger stores immutable saga identity plus synchronization events. Status is always derived from the child ledgers, so a crash after a child commit but before saga synchronization recovers the child as committed without a second provider effect.

Saga-level states are:

- `ALL_PENDING`
- `PARTIALLY_COMMITTED`
- `RECONCILIATION_REQUIRED`
- `ALL_COMMITTED`
- `TERMINAL_BLOCKED`

Default release policy is `all_required`: global success is false until Instagram, TikTok and YouTube are all `COMMITTED`. An explicit `explicit_partial` policy may set a lower threshold; it is never inferred.

## Identity and conflict rules

Each child idempotency key binds:

- exact `final.mp4` SHA-256 and size;
- platform;
- caption/title/thumbnail hashes;
- release-window start/deadline/revision;
- provider adapter and account;
- destination;
- configuration reference and configuration revision;
- release policy.

The child request is then bound again by R33. Reopening the same saga with changed copy, winner, provider/account/config, or schedule revision conflicts rather than silently mutating identity.

## Schedule gate

The release window is deterministic identity, not mutable runtime decoration. Commit is rejected before the window and after the deadline. Status reports `WAIT_FOR_RELEASE_WINDOW` or `BLOCKED_RELEASE_DEADLINE_PASSED` without touching the fake provider.

A changed schedule revision creates a changed saga/child intent. Reusing the prior durable saga path with that changed intent fails closed.

## Partial commit and reconciliation

A platform with lost acknowledgement after dispatch becomes `RECONCILIATION_REQUIRED`. Its status reports:

- `nextSafeAction=READ_ONLY_RECONCILE_ONLY`
- `replayAuthorized=false`

A successful Instagram post does not authorize a TikTok replay while TikTok is unknown. Pending YouTube remains its own independent transaction.

Read-only provider lookup may promote unknown to `COMMITTED` only when R33 validates authoritative evidence bound to the exact transaction, idempotency key and request digest. The deterministic harness includes a TikTok timeout-after-dispatch followed by authoritative `duplicate_confirmed` evidence.

If lookup is unavailable, the child remains `RECONCILIATION_REQUIRED`.

## Abort and compensation

R34 never pretends a committed external post can be rolled back locally.

A committed R33 child cannot be relabeled `ABORTED`. R34 compensation is metadata/workflow state only:

- `providerDeleteContractAvailable=false`
- `providerDeleteExecuted=false`
- `localRollbackClaimed=false`
- `externalPostStillCommitted=true`

Verified provider-specific deletion is out of scope.

## Deterministic chaos rehearsal

The R34 rehearsal exercises:

1. crash/restart before the release window;
2. three validated/eligible platform children;
3. Instagram committed;
4. TikTok timeout after dispatch -> unknown;
5. blind TikTok retry rejected;
6. TikTok read-only lookup -> `duplicate_confirmed`;
7. YouTube still pending, then committed;
8. separate lookup-unavailable saga remaining blocked;
9. separate validation-rejection saga becoming `TERMINAL_BLOCKED`;
10. compensation metadata recorded without changing Instagram's committed state.

No real provider adapter or network path is allowed in R34.

Run:

```bash
creator-multiplatform-publish-r34 readiness
creator-multiplatform-publish-r34 chaos-rehearsal --out .r34-chaos
creator-multiplatform-publish-r34 status \
  --saga-dir .r34-chaos/partial-saga \
  --at-time 2026-10-05T12:30:00Z
```

The evidence artifact includes the saga ledger, every child R33 transaction ledger, intermediate status evidence, the chaos report, the evidence manifest, conformance files and static readiness report.


## Acceptance boundary after QA-R3

Parent R33 is now accepted only for the exact authority above. This does not change R34 product behavior, provider safety, scheduling, reconciliation, or compensation semantics.

R34 self-status remains `SOURCE_READY_PENDING_R34_QA` with blocker `WAITING_R34_INDEPENDENT_QA`. The fake-provider-only boundary remains intact: `providerNetworkEffects=0`, `livePublish=false`, and unknown provider outcomes remain non-replayable until read-only reconciliation proves an exact outcome.
