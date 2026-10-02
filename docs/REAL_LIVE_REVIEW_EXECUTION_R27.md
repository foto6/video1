# Creator R27 real live-review -> Media R19 re-edit execution

R27 upgrades the R26 real-review boundary to execute actionable review directives through exact Media R19. It does not synthesize a model judgment inside Creator and does not perform a social-provider mutation.

## Exact dependency evidence

### Media R19 — exact-green and executable

- repository: `foto6/video2`
- branch: `agent/media-r19-editorial-runtime-production-20261002`
- producer SHA: `31409de4bef473417a33a8c698507f7cfb1905e1`
- CI: `36984502487 SUCCESS`
- application contract: `media.editorial_reedit_application.v1`
- request contract: `media.editorial_reedit_request.r19.v1`
- application contract blob: `6b3350c5f1524fe49a49d5637514e2fb1a808bcf`
- application manifest blob: `502c32253d370e9b4e3d53f4a70de317f89dd21b`
- application schema blob: `7cabf91f08ae11b68cc4a7eec88d358a46730289`
- implementation blob: `8110a086b5b319bd2601860845c6afbf97681921`
- runner blob: `7dbec612621aa42baaf2946cdac61d070e3ff41f`
- render-export manifest/schema blobs: `945acb01ff0269d89b91463aa8d862f500e055b2` / `6353d32d785a2a1f1441bac4cfd0271b46b41d4a`

R27 verifies all of those before invoking the producer. Media R19 itself verifies exact candidate bytes, source bytes, render-export sidecar, Growth handoff, directive identity, bounded intervals and replay identity. R27 additionally verifies the returned application sidecar, render export, technical QA, new MP4 SHA/size and byte change.

### Growth R25 — not yet available at implementation time

The named branch exists:

- repository: `foto6/video3`
- branch: `agent/growth-r25-real-capture-ingest-20261002`
- observed HEAD: `dc0741d5b11c1f7464ac9a6c5db80c0a4535df08`
- observed CI: `36987057963 SUCCESS`

That HEAD is still the Growth R24 producer. It contains `growth.live_video_review_capture.v1` but no R25-specific Creator-ready external review envelope contract/schema. R27 therefore refuses to label any payload as Growth R25 production evidence until a new exact-green producer SHA and its exact contract/blob pins are available.

For CI only, the Creator-owned envelope `creator.growth_r25_external_review.r27.v1` supports an explicit fixture mode. Fixture mode is rejected unless `--allow-test-fixture` is passed and always reports `REAL_REVIEW_INGESTED=false`.

### Media R20 dynamic review package — not yet available

The named branch `agent/media-r20-r19-creator-integration-20261002` currently points to the same exact R19 head `31409de4bef473417a33a8c698507f7cfb1905e1` and exposes no R20-specific dynamic blinded review-package contract.

After a successful R19 targeted re-edit, R27 therefore emits `next-review-request.json` with:

`BLOCKED_MEDIA_R20_DYNAMIC_PACKAGE_UNAVAILABLE`

rather than silently falling back to R18/R17/static packaging.

## Durable cycle

The durable R27 ledger records:

1. exact candidate context and producer pins;
2. external review envelope identity/digest;
3. Media R19 re-edit intent/result;
4. terminal outcome when applicable.

A same review event is idempotent. A same durable key with different review content fails closed. If Media R19 completes and Creator loses the acknowledgement before recording it, a restart invokes the same Media R19 replay identity; Media verifies existing sidecar/output bytes and returns `replayed=true` with zero new logical effects.

Maximum targeted re-edit rounds remain **2**. A `targeted_reedit` at round 2 is rejected rather than producing round 3.

## Input lineage

The runner consumes a strict `creator.reviewed_candidate_context.r27.v1` containing:

- source ID/SHA/size;
- loop/brief/semantic/ledger digests;
- candidate ID and current round;
- exact current MP4 path/SHA/size;
- exact current `media.render_export.v1` path/SHA;
- exact candidate render producer SHA;
- canonical timeline and export spec.

The external review envelope must bind the same source, candidate, render bytes, render-export bytes, attachment bytes/identity, critic output digest and round.

## State boundary

Readiness reports these stages independently:

- `SOURCE_READY`
- `REAL_REVIEW_INGESTED`
- `REAL_REEDIT_EXECUTED`
- `PUBLISH_HANDOFF_READY`

Current production state is:

`SOURCE_READY / BLOCKED_WAITING_REAL_CAPTURE`

because no genuine Bridge R29 -> Growth R25 Creator-ready artifact is available here and the Growth R25 producer contract is not yet exact-green.

Fixture-driven exact Media R19 execution is conformance evidence only. It never sets the real-review or real-reedit stage booleans.

## Terminal behavior

- `targeted_reedit`: execute exact Media R19 once, verify new bytes, then produce the next review boundary.
- `winner`: copy the exact reviewed MP4 to canonical `final.mp4`; an existing R23 publish handoff may only be materialized from the winner and a matching external release authorization.
- `tie`, `insufficient_evidence`, `human_review`: remain non-publishable.

No provider is invoked by R27. No credentials, CAPTCHA or 2FA automation are present.

## Commands

Readiness:

```bash
creator-live-review-r27 readiness --out r27-readiness.json
```

Execution after a genuine pinned Growth R25 envelope exists:

```bash
creator-live-review-r27 run \
  --media-r19-checkout ../video2-r19 \
  --growth-r25-checkout ../video3-r25 \
  --candidate-root ./candidate-package \
  --candidate-context ./candidate-context.json \
  --review-envelope ./growth-r25-review.json \
  --out ./r27-run
```

The command exits nonzero while the production Growth R25 gate is unavailable or on any provenance/schema invariant violation.
