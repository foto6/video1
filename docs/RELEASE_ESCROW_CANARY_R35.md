# Creator R35 release escrow / canary transaction controller

R35 adds `creator.release_escrow_canary.r35.v1` above the exact accepted R34 multi-platform publish saga. It is a durable staging and canary controller for a future live publisher, but this milestone remains **FAKE_PROVIDER / SOURCE_READY ONLY**.

No credential access, browser/provider mutation, network publish, live social post, destructive compensation, or merge is authorized.

## Exact frozen authorities

Creator R34 is frozen as one immutable authority tuple:

- repo `foto6/video1`
- SHA `77dfe83d582eac98e60728974efc77345612b364`
- CI `37209289425 SUCCESS`
- artifact `11305609870`
- artifact digest `sha256:366dc6b7f43982c23489f7119a04805b4be9b8eed2717f61a9db3a0e6ece1032`
- contract `creator.multiplatform_publish_saga.r34.v1`
- exact runtime/tests/schema/manifest/authority/readiness blob pins.

Hard Wave QA R5 independently accepted that exact tuple at:

- `foto6/boss@1583c853108b0fb88507448eb8b4c61f0f07b0bc`
- CI `37211964139 SUCCESS`
- artifact `11306289580`
- observed artifact digest `sha256:846c97206fb332d0ffa1011f44b884b3148736ba9ca96a756b4ae585eab50bfa`.

R5's authority-uniqueness rule is also frozen: a later same-SHA run/artifact is not interchangeable with the accepted tuple. Tuple drift fails closed.

Growth R33 is accepted only as read-only advisory policy input:

- repo `foto6/video3`
- SHA `8bedb5ad79023006b87b17933863ff915ab5e046`
- CI `37210963972 SUCCESS`
- artifact `11306727215`
- digest `sha256:132845c0aaa6d4fec5aaf60e1ade60d779183f2a637a9513e4176bd2ee569660`
- contract `growth.adaptive_portfolio_governor.r33.v1`
- exact authority/contract/schema/policy/implementation/test blob pins.

The Growth boundary remains shadow-only. A Growth recommendation can never substitute for explicit release authorization.

## Immutable release intent

A release operation binds:

- source SHA;
- session/tournament/winner candidate lineage;
- exact final winner MP4 SHA-256 and size;
- exact R34 authority and R34 saga identity;
- exact Growth R33 authority and advisory decision digest;
- declared Instagram/TikTok/YouTube platform set;
- deterministic canary platform and expansion order;
- release-window start/deadline/revision;
- platform account/provider/config identities;
- copy/title/thumbnail hashes inherited from R34/R33;
- operator authorization digest;
- release-policy digest;
- stable `r35release:<sha256>` operation identity.

Same release identity with changed bytes, copy/config/account/platform set, Growth decision, policy or schedule is a hard conflict.

## Durable phase machine

Legal phases are:

`PREPARED -> ESCROWED -> PREFLIGHT_GREEN -> CANARY_ELIGIBLE -> CANARY_COMMITTING -> CANARY_CONFIRMED -> EXPANSION_ELIGIBLE -> EXPANSION_COMMITTING -> FULLY_CONFIRMED`

Exceptional fail-closed phases are:

- `HUMAN_REVIEW_REQUIRED`
- `RECONCILIATION_REQUIRED`
- `TERMINALLY_BLOCKED`.

Illegal skips raise before provider invocation.

## Escrow and preflight

`PREPARED` and `ESCROWED` cannot cause provider effects. Escrow freezes the exact winner render SHA/size and metadata digest. Replays with drift conflict.

Preflight validates the exact R34/Growth authorities and all three R34 child transactions, but does not make any provider call. If the clock crosses the release deadline while preflight is running, the release becomes terminally blocked before canary eligibility.

## Canary

The canary is deterministic and must be one platform explicitly declared by policy. The default fixture selects Instagram Reels.

Canary eligibility requires an explicit operator-authorization digest. The Growth advisory digest is deliberately not accepted as authorization.

Before the fake provider boundary, R35 persists a `CANARY_COMMITTING` effect-boundary event. It then delegates exactly-once behavior to the existing R34/R33 child transaction.

- known timeout before dispatch -> safe `CANARY_ELIGIBLE` resume;
- confirmed result -> `CANARY_CONFIRMED`;
- lost ACK / unknown result / invalid provider proof -> `RECONCILIATION_REQUIRED`;
- unknown result forbids blind retry;
- only read-only outcome lookup may promote unknown to confirmed.

A process restart after send-before-ack reloads the durable reconciliation state and does not invoke commit again.

## Expansion

Expansion cannot become eligible until the canary has durable confirmation. Only the declared non-canary platform identities are eligible.

Each expansion platform preserves its exact R34/R33 transaction/idempotency/account identity. One platform entering reconciliation blocks further expansion until the unknown outcome is resolved; it never silently re-targets another platform.

The controller reaches `FULLY_CONFIRMED` only after every required platform is durably committed under the default all-required policy.

## Schedule and identity chaos

R35 fails closed for:

- stale release window after restart;
- preflight crossing deadline;
- changed policy revision/digest after escrow;
- changed Growth decision;
- changed winner bytes/size;
- changed account identity before commit;
- changed platform set;
- changed R34 or Growth authority tuple;
- replayed release ID with changed payload.

## Compensation

Automatic delete/repost is outside scope.

R35 can record metadata-only compensation workflow state only when the caller explicitly supplies proof that the provider contract supports reversible metadata. Even then, the external post remains marked committed and R35 records:

- `providerDeleteExecuted=false`
- `repostExecuted=false`
- `externalPostStillCommitted=true`.

Unknown or partial commit can never trigger destructive cleanup.

## Deterministic chaos harness

Run:

```bash
creator-release-escrow-r35 readiness
creator-release-escrow-r35 chaos-rehearsal --out .r35-chaos
creator-release-escrow-r35 status --release-dir .r35-chaos/clean-full-confirmation
```

The chaos rehearsal executes at least 25 deterministic cases, including clean full confirmation, timeout-before/after dispatch, delayed confirmation, duplicate confirmation, provider-ID conflict, wrong account, render/config/platform/Growth/R34 drift, release-ID replay conflict, deadline crossings, restarts at escrow/canary/expansion boundaries, unknown expansion isolation and compensation constraints.

Every status includes exact durable evidence digests, unresolved operations, next permitted action and `realProviderEffectAuthorized=false`.

Final R35 disposition is `SOURCE_READY_NO_LIVE_PROVIDER`.
