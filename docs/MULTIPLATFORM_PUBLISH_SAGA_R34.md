# Creator R34 multi-platform publish saga

R34 orchestrates one approved short-form winner across Instagram Reels, TikTok and YouTube Shorts while preserving R33 exactly-once safety independently for each platform.

This milestone is source-ready only. The parent R33 candidate is exact-green but **QA-R3 is still pending**, so R34 readiness is `SOURCE_READY_WAITING_PARENT_QA`. R34 must not relabel R33 as accepted.

## Frozen parent

R34 freezes the parent candidate at:

- Creator R33 SHA `9556108f423a15a40614a8bc9d590e6dc2e49746`
- CI `37203622591 SUCCESS`
- artifact ID `11304071297`
- artifact digest `sha256:adbfb6d257332220e2be2f9d8f134a87f8bcc6b6e064dfac7f469fd95d690d6d`
- child contract `creator.publish_transaction.r33.v1`

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
