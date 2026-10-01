# Creator R24 full-lifecycle synthetic rehearsal

R24 is a deterministic, bounded, synthetic lifecycle proof:

source + brief -> R22 semantic/editor loop -> exact-pinned Media R15 render-export contract adapter -> exact-pinned Growth R18 candidate decision -> R22 final bundle -> R23 durable publish handoff -> synthetic R12 provider receipt -> exact-pinned Growth R19 post-publish learning -> next-cycle brief seed.

No live provider request, credential use, real social post, live metrics, Media/Growth mutation, or HUMAN_LEVEL claim occurs.

## Immutable producer pins

- Creator R22: foto6/video1 @ 351df0d455557fb20b47f0fd2ab806c4281ed5ee, CI 36859291553.
- Creator R23: foto6/video1 @ 8914a1207241115a9cb9e1d666a3cf6955ec4190, CI 36861170789.
- Media R15: foto6/video2 @ a17f782da8144d1e890ac83195396a3192df93c2, CI 36860193113.
  - media.render_export.v1 manifest blob 945acb01ff0269d89b91463aa8d862f500e055b2
  - schema blob 6353d32d785a2a1f1441bac4cfd0271b46b41d4a
  - implementation blob 2aee865404d78eeb64e17e9aeae8f44a0c1a746e
- Growth R18: foto6/video3 @ 2d3bf275c5b456d53384073fb7ec1ed992e6b996, CI 36859378847.
  - growth.candidate_decision.v1 manifest blob 05e778e7a67556b66cb407e2c65a2f7bb391dbab
  - schema blob 75a3efbb8a4e14789508dae11ae8db92723d0e27
  - implementation blob 0d977ac0161a1f13facf79c42f97182649b40722
- Growth R19: foto6/video3 @ a802a1c0eed5ae564e7e67236e986bff560c58a9, CI 36861560705.
  - growth.post_publish_learning.v1 manifest blob ee1864329ff80c243e8f2b653a715091374316c8
  - schema blob 8cc7b1ff3ea99da31865df65cb688e57cbbf0882
  - implementation blob 78b839a954cc1375998229e40fcfe1cbfeb5c54a

The six upstream manifest/schema files are vendored byte-for-byte under the R24 conformance directory. Runtime startup recomputes their Git blob SHA-1 and fails closed on drift.

## Synthetic boundary

The Media adapter creates deterministic candidate MP4 fixtures from the supplied source and emits the exact Media R15 contract shape. Its provenance explicitly records syntheticFixtureAdapter=true and actualMediaProducerInvoked=false. The exact Media R15 producer SHA identifies the contract authority, not a claim that the sibling producer was executed.

Provider posting uses only R12 mock providers. R23 still commits durable publish intent first and uses its recover-before-resubmit semantics. The winner rehearsal injects one lost provider acknowledgement and proves one logical accepted effect / one submit.

Metrics are synthetic_fixture only, live_performance_claim_allowed=false, and are lineage-bound to the synthetic publish result. They are never described as live platform observations.

Growth R19 output contains only bounded, explicit, testable hypotheses with causal_claim=false. Its next-cycle brief seed is creator_cycle_eligible=false.

## Branches

The command supports:

- winner: round 0 tie, round 1 tie, round 2 winner, then publish/learning.
- tie: bounded editor rounds terminate without publish.
- insufficient_evidence: terminates without a final bundle or publish.
- human_review_required: exhausts the two re-edit round maximum then requires review.
- provider_auth_required: reaches R23 but stops at waiting-for-credentials with zero provider effects.

## One-command rehearsal

```bash
creator-lifecycle-r24 \
  --source ./source.mp4 \
  --brief "Make the proof concise and test the hook" \
  --out ./r24-out
```

Invariant injection must exit nonzero:

```bash
creator-lifecycle-r24 \
  --source ./source.mp4 \
  --brief "Invariant test" \
  --out ./r24-bad \
  --inject-violation render_hash_mismatch
```

Supported injected violations are render_hash_mismatch, decision_source_hash_mismatch, and metrics_hash_mismatch.

## Durable outputs

The completed winner path writes final.mp4, editor-final-bundle.json, growth-r18-decision.json, editor-publish-handoff.json, provider-receipt.json, growth-publish-result.json, synthetic-metric-snapshot.json, growth-r19-learning.json, next-cycle-brief-seed.json, lifecycle-ledger.jsonl, R23 publish ledgers, and lifecycle-report.json.

The lifecycle report carries all exact producer SHAs/CI IDs, vendored manifest/schema blob evidence, source SHA, final render SHA, editor/decision/handoff/receipt/metric/learning/seed digests, editor re-edit count, provider restart/effect counts, and explicit no-live/no-human-level flags.
