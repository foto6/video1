# Creator R32 autonomous tournament coordinator

R32 defines `creator.autonomous_tournament.r32.v1`, a durable coordinator state machine for:

`SOURCE -> 2–4 EDIT CANDIDATES -> THREE BLINDED REVIEWS -> CONSENSUS -> TARGETED RE-EDIT (<=2) -> NEXT REVIEW ROUND -> WINNER -> PUBLISH HANDOFF`.

No live browser, provider, social publish, credential, CAPTCHA/2FA, or human-ground-truth path exists in this milestone.

## Authority boundary

The session freezes immutable source/brief hashes plus exact current producer evidence:

- Media R24: `foto6/video2@244acdf154741e669991b17df3ef2a47e2dfdfa9`, CI `37195239582 SUCCESS`, canonical live-review contract/schema/manifest/implementation/exporter/verifier blobs pinned in the conformance authority profile.
- Growth R29: `foto6/video3@3e4a8ad6d73b058c953abeadba7a60abe567adbc`, CI `37195373334 SUCCESS`, exact-session contract/authority/implementation fixture blobs pinned.
- Bridge R34: `foto6/WebAIBridge@4e2a37545cc0cdd940cf6e86d40e0d620d6c94ae`, CI `37196102639 SUCCESS`, exact-ID routing/workflow/rehearsal/readiness blobs pinned.

The expected R25/R30/R35 branch refs currently resolve to those same older producer heads and their trees do **not** contain `media.multicandidate_round.r25.v1`, `growth.consensus_review.r30.v1`, or `bridge.multiagent_dispatch.r35.v1`. They are therefore not authoritative. R32 finishes as `AUTONOMOUS_LOOP_SOURCE_READY` with blocker `WAITING_UPSTREAM_GREEN`.

Development/chaos execution uses explicitly labeled `frozen_contract_fixture` envelopes targeting those three expected contracts. It never reports them as live producer integration.

## Durable ledger

`creator.autonomous_tournament_ledger.r32.v1` is append-only JSONL. Every transition records:

- session/tournament identity and review/re-edit round in the new state;
- frozen authority digest;
- operation/idempotency ID;
- exact input/output artifact digests;
- previous-state digest and new-state digest;
- request digest;
- event digest.

`timestampMetadata` is deliberately excluded from event identity. Changing timestamps cannot change state/event identity.

Exact replay of the same event is idempotent. The same event/operation with changed package, prompt, capture, consensus, edit, or authority fails closed.

## State and bounds

Review rounds are 0..2. Targeted re-edits are limited to two. Candidate packages require 2–4 candidates and reject duplicate render bytes, stale source, undeclared edit graphs, candidate-set drift, and sealed-mapping tampering.

There is no legal SOURCE -> publish transition.

## Bridge dispatch semantics

Every round creates exactly three independent reviewer dispatch identities. The operation ID binds:

- session;
- review round;
- reviewer index;
- exact conversation ID;
- package digest.

A lost/unknown Send produces `RECONCILIATION_REQUIRED`. Consensus advancement and publication remain blocked until authoritative recovery returns the exact operation/capture. R32 never blind-retries an unknown Send.

## Consensus semantics

The frozen R30 contract fixture binds the exact three capture digests and candidate package. Only `CONSENSUS_ACCEPTED` may produce a targeted re-edit or winner.

`HUMAN_REVIEW_REQUIRED`, tie, insufficient evidence, malformed capture sets, duplicate reviews, stale package/round, and authority drift are non-publishable.

## Targeted re-edit

Timestamped directives are allowlisted to:

- `trim_span`
- `move_cut`
- `reframe_subject`
- `caption_emphasis`
- `audio_mix`

Directives must stay inside source duration and target a declared edit-graph node. The generated request carries parent render/graph identity plus an explicit digest of unaffected graph nodes so unaffected lineage remains preserved.

The chaos adapter emits a labeled `media.editorial_reedit_application.v1` compatibility fixture; it is not claimed as a real Media R25 execution.

## Winner path

Only `WINNER_READY` can emit a publish handoff. The handoff carries `contractVersion=creator.editor_publish_handoff.v1`, canonical `final.mp4` identity, source/consensus lineage, and `livePublish=false`. It is a frozen contract fixture for the deterministic rehearsal and never triggers the R21 provider runtime.

## Chaos rehearsal

Run:

```bash
creator-autonomous-tournament-r32 chaos-rehearsal --out .r32-chaos
```

The deterministic rehearsal executes:

1. four initial candidates;
2. crash after package persistence;
3. one reviewer dispatch then restart;
4. a second Send whose acknowledgement is lost;
5. reconciliation before any consensus;
6. third independent reviewer;
7. crash after all reviews;
8. first accepted consensus requesting concrete targeted re-edit;
9. one bounded re-edit and restart before the next package;
10. four second-round candidates;
11. three second-round reviews;
12. second accepted consensus selecting a winner;
13. persisted publish-handoff identity;
14. restart and exact replay proving no duplicate handoff/effect.

Expected logical effects: six review Sends, one re-edit, zero provider/social publish effects.

## Status

```bash
creator-autonomous-tournament-r32 status
creator-autonomous-tournament-r32 status --ledger .r32-chaos/autonomous-tournament-ledger.jsonl
creator-autonomous-tournament-r32 readiness
```

The status command reports exact state, blockers, next permitted action, frozen authority digest, and required next-wave authority evidence.
