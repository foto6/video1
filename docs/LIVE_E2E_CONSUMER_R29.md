# Creator R29 — live E2E consumer

R29 is the Creator-side consumer for the exact-green dynamic review wave. It does not create or simulate a browser/model review. It accepts only a provenance-bound Growth R26 Creator envelope produced from the coordinator's live review path.

## Exact authorities

Creator verifies immutable checkouts and Git blobs before accepting input:

- Media R21: `foto6/video2@d753e9e4c1f4448386608a1425232dbc1dba87ea`, CI `36994000619`.
- Growth R26: `foto6/video3@e844ed2daaaca9e9694fe1e0fb6b8b7bfac69cbc`, CI `36994388154`.
- Bridge R30: `foto6/WebAIBridge@ceaee873231a8552c5b7324083baa800eec566a8`, CI `36993885456`.

All pinned contract/schema/implementation blob IDs are recorded in `conformance/creator.live_e2e_consumer.r29.v1/authority-profiles.json`. Branch names are not authority.

## Accepted live input

The consumer accepts only `growth.dynamic_creator_external_review_envelope.r26.v1` from the exact Growth R26 producer. It verifies the exact Media R21 package authority and Bridge R30 capture authority contained in the envelope, including:

- package digest and sealed-mapping digest;
- capture digest and assistant-response digest;
- review round and selected candidate identity;
- source ID/SHA/size;
- candidate ID/round;
- reviewed render SHA/size;
- attachment SHA/size/MIME;
- Growth critic/handoff digest and allowlisted directive identities.

Stale producer SHA, changed Git blobs, package or mapping drift, altered render bytes, wrong attachment identity, selected-candidate drift, round regression, duplicate conflicting events, or invalid directive IDs fail closed.

## Targeted re-edit execution

A `targeted_reedit` may execute only for review rounds 0 or 1. Creator passes the exact reviewed MP4 plus Growth's allowlisted operations to the exact editorial runtime present in Media R21. Creator requires real output evidence:

- changed `final.mp4` SHA and size;
- `media.editorial_reedit_application.v1`;
- `media.render_export.v1`;
- editorial plan/timeline;
- passing technical QA;
- every directive applied.

Media R21 currently embeds the R19 runtime's frozen `growth.creator_reedit_handoff.v1` validator. R29 therefore uses a narrow compatibility adapter *after* validating the Growth R26 dynamic envelope. The adapter copies only the exact allowlisted operations, timestamps, evidence, confidence and uncertainty. The original Growth R26 handoff remains authoritative and its digest is journaled. The compatibility handoff digest is separately recorded as Media execution provenance; it is never represented as the current live-review authority.

## Next review round

After a successful re-edit, R29 immediately invokes the exact Media R21 `media.review_round_request.r21.v1` / `media.review_round_bundle.r21.v1` boundary. The package compares the reviewed baseline with the new challenger, binds the R19 application sidecar, preserves the exact source/brief lineage, and emits the transport-neutral package for the next live capture. R29 does not fall back to the old static R18 package or the R20 package builder.

## Replay and terminal behavior

The journal is `creator.live_e2e_consumer_ledger.r29.v1`. The same review event is idempotent; a changed event for the same round is a conflict. The Media runtime's deterministic replay identity prevents a lost acknowledgement from producing a second edit effect.

At most two re-edit rounds are permitted. Only a terminal `winner` may create canonical `final.mp4` and the existing R23 publish handoff. `tie`, `insufficient_evidence`, `human_review`, and `reedit_limit_reached` remain non-publishable. R29 never invokes a social provider.

## Operator command

After the coordinator has materialized the exact checkouts, current candidate evidence, and a genuine Growth Creator envelope:

```bash
creator-live-e2e-r29 consume \
  --media-checkout /path/to/video2-r21 \
  --growth-checkout /path/to/video3-r26 \
  --bridge-checkout /path/to/WebAIBridge-r30 \
  --candidate-root /path/to/materialized-candidate-root \
  --candidate-context /path/to/candidate-context.json \
  --growth-output /path/to/growth.dynamic_creator_external_review_envelope.r26.v1.json \
  --out /path/to/r29-out
```

A release authorization and publish-target JSON may be supplied only for a terminal winner; this materializes the existing publish handoff but still performs no provider operation.

Current readiness is `SOURCE_READY / BLOCKED_WAITING_LIVE_GROWTH_OUTPUT`. No genuine coordinator-run Growth dynamic envelope is available in this Creator agent context, so R29 does not claim `REAL_REVIEW_INGESTED` or `REAL_REEDIT_EXECUTED`.
