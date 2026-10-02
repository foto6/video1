# Creator R28 dynamic live-review loop

R28 upgrades Creator's real-review path from R27's frozen dependency snapshot to exact runtime authority profiles and a round-by-round review package cycle.

## Exact authorities

The committed production profiles pin immutable producer heads and Git blobs. Moving branches are never authority.

### Media R20

- repository: `foto6/video2`
- producer SHA: `b22174db3c772a49a21fb9f8b1d40828bf258005`
- exact-head CI: `36988788032 SUCCESS`
- re-edit application contract: `media.editorial_reedit_application.v1`
- dynamic package contract: `media.dynamic_review_package.r20.v1`
- dynamic request contract: `media.dynamic_review_request.r20.v1`
- dynamic package contract/schema/implementation/runner blobs:
  `bf650ad1552686d830965edad3fd62451ec0ec22`,
  `680aa69dfb595f31e93fb2bdfe0fdae2ac5ca25b`,
  `cebaa1083d121844b5f7d5a78196d201f860d8a8`,
  `33c742f1e0314e462fb3e97337bf82883ec80f00`.

R28 also pins the unchanged R19 editorial runtime and canonical render-export contract blobs present at that exact R20 producer head.

### Growth R25

- repository: `foto6/video3`
- producer SHA: `2c441ebaa017c7da72461316401aeaf445e3d6e5`
- exact-head CI: `36988158233 SUCCESS`
- Creator envelope: `growth.creator_external_review_envelope.r25.v1`
- ingest contract: `growth.real_capture_ingest.r25.v1`
- ingest contract/schema/implementation blobs:
  `86a2fe264148a2bf3572158c2a44d66be93ec3af`,
  `b7f8663080b9058ea7db23d4123b8d00bd59e3d9`,
  `ffd0233715e68d8f4374755942bf5de65ac3cfec`.

The nested Creator re-edit handoff remains `growth.creator_reedit_handoff.v1`, and R28 validates its exact historical authority blob IDs carried by R25 rather than rewriting that provenance.

### Bridge R29 observation

The coordinator-supplied exact-green R29 head is `ed9a35290f94607d7577f1ee9301de1bb44334f2`, CI `36989658042 SUCCESS`. It proves the existing-chat capture transport but does not by itself create the next dynamic round capture required after a Media R20 package.

No exact-green Growth R26 or Bridge R30 dynamic-capture authority is available in this execution context. That missing authority is explicit in readiness; it is never replaced by a fixture or assumed moving branch.

## Runtime authority model

`creator.dynamic_review_authority.r28.v1` profiles contain the exact producer SHA, CI run, contract names, and required Git blob IDs. The runner independently checks each supplied checkout with `git rev-parse HEAD` and Git-blob-compatible SHA-1 over every pinned contract/schema/implementation file.

A syntactically valid but stale producer SHA or changed schema/blob therefore fails before review or media mutation.

R25 is supported today because its exact envelope parser is implemented. Future R26-family envelopes are accepted only after a matching exact profile/parser is added; an unknown future contract is rejected instead of guessed.

## Durable round state

`creator.dynamic_live_review_loop_ledger.r28.v1` records, per round:

- exact candidate context and authority-profile digests;
- external review envelope/capture/critic digests;
- reviewed candidate ID/render SHA;
- applied Media result digest and before/after byte hashes;
- next Media R20 package digest/sealed-mapping digest;
- terminal winner lineage when applicable.

The event key is round-stable. Replaying the same review is idempotent; changing the envelope/capture for an already recorded round raises a conflict. Media R19's durable replay identity is reused, so restart/lost acknowledgement does not create another render effect.

Re-edit rounds are bounded to two. A `targeted_reedit` received at round 2 fails closed.

## Targeted re-edit

For `targeted_reedit`, R28:

1. verifies the external Growth envelope against the current candidate bytes/sidecar;
2. runs the exact R19 editorial re-edit runner from the exact Media R20 checkout;
3. requires `media.editorial_reedit_application.v1`;
4. requires every directive to be applied rather than unsupported;
5. requires technical QA pass;
6. verifies the new `final.mp4` SHA/size and `media.render_export.v1`;
7. requires the output bytes to differ from the reviewed candidate;
8. records the application/render-export semantic and file digests.

A re-edit candidate at round > 0 cannot exist without its exact editorial application sidecar.

## Dynamic next-review package

After an accepted re-edit, R28 builds a pairwise package using the exact Media R20 `build-r20-dynamic-review.mjs` boundary. The package compares the reviewed candidate against the new candidate, checks both real byte/sidecar lineages, creates deterministic blinded A/B attachments, and emits the Bridge request boundary.

The Media package itself explicitly performs no model review, browser upload, or provider publish. R28 validates the package producer, package/file digest, sealed mapping, prompt digest, source lineage, and `humanQuality=false`.

Because no exact-green Growth R26/Bridge R30 dynamic capture authority is available here, successful packaging ends at:

`BLOCKED_WAITING_DYNAMIC_REVIEW_CAPTURE`

with `NEXT_REVIEW_PACKAGE_READY=true`, not with fabricated model evidence.

## Terminal outcomes

Only an exact external-review `winner` may materialize a canonical `final.mp4` and, when a separately supplied `release.authorization.v1` is present, the existing R23 publish handoff.

`tie`, `insufficient_evidence`, and `human_review` remain non-publishable. No R28 path invokes an R21 social provider.

## Readiness states

The machine-readable report exposes independently:

- `SOURCE_READY`
- `REAL_REVIEW_INGESTED`
- `REAL_REEDIT_EXECUTED`
- `NEXT_REVIEW_PACKAGE_READY`
- `PUBLISH_HANDOFF_READY`

The committed readiness is source-ready but blocked waiting for a future exact dynamic review capture authority/evidence. CI exercises exact Media/Growth producer checkouts with explicitly test-only review envelopes; those tests never set the real-review flags.

## Commands

Inspect readiness:

```bash
creator-dynamic-live-review-r28 readiness --out ./r28-readiness.json
```

Consume an externally produced exact Growth envelope:

```bash
creator-dynamic-live-review-r28 run \
  --media-checkout ../video2-r20 \
  --growth-checkout ../video3-r25 \
  --media-authority ./media-authority.json \
  --growth-authority ./growth-authority.json \
  --candidate-root ./review-work \
  --candidate-context ./review-work/candidate-context.json \
  --review-envelope ./growth.creator_external_review_envelope.r25.v1.json \
  --bridge-target ./bridge-target.json \
  --out ./r28-out
```

The command never performs a live social publish. No credentials, cookies, CAPTCHA/2FA automation, or human-quality claim are part of R28.
