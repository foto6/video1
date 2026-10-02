# Creator R26 — Real-review closed loop

R26 replaces the R24 structural/synthetic Growth decision inside the execution loop with a strict external review boundary. Creator does not create a model verdict. It accepts only an externally captured, provenance-bound Growth R23 `growth.creator_reedit_handoff.v1` event, executes supported edit directives through the exact Media R15 runtime, and stops after at most two re-edit rounds.

## Exact authorities

Creator starts from R24 exact-green `215dc6ef924da45072c9f2c648edd3b3d80e645c`.

Media execution is pinned to:

- repository: `foto6/video2`
- producer SHA: `a17f782da8144d1e890ac83195396a3192df93c2`
- CI: `36860193113`
- contract: `media.render_export.v1`
- manifest blob SHA-1: `945acb01ff0269d89b91463aa8d862f500e055b2`
- schema blob SHA-1: `6353d32d785a2a1f1441bac4cfd0271b46b41d4a`

External review ingestion is pinned to Growth R23:

- repository: `foto6/video3`
- producer SHA: `26f769abceb43a63677ea8f7ba028369db371696`
- exact-head CI: `36981672628`
- handoff contract: `growth.creator_reedit_handoff.v1`
- adapter contract: `growth.web_video_critic_reedit_adapter.v1`
- contract blob SHA-1: `ced853aad722aad4c7a88e9a41756baa1b2892a6`
- schema blob SHA-1: `ba9ada04488760147136dcaaf012206405c04653`
- adapter blob SHA-1: `a4f5b1219c874ae13c05651e584dd7fbf5d4449a`

The runner verifies those checkouts and committed blobs before any Media render.

## External review boundary

The CLI consumes `creator.external_real_review_event.r26.v1`. The envelope identifies the exact Growth R23 producer and contains one unmodified `growth.creator_reedit_handoff.v1`.

Every accepted review is checked against the current candidate:

- original source ID, SHA-256 and byte size;
- candidate ID, render SHA-256 and byte size;
- Media producer SHA and render-export digest;
- attachment SHA-256, size and attachment identity;
- review-bundle digest;
- critic input and output digests;
- Growth handoff ID/digest and re-edit round;
- exact Bridge R26 and Media R18 authorities carried by Growth R23;
- uncertainty/coverage boundaries;
- no human-ground-truth, live-platform, provider-mutation, upload or release-authority escalation.

A same-invocation duplicate review is rejected. Across process restart, an exact already-durable review is a replay no-op; a conflicting payload for the same durable round fails closed. Reviews must begin at round 0 and be contiguous.

## Real Media edits

R26 submits every initial/re-edit candidate through the exact Media R15 `media.job.v1` runtime and emits a canonical `media.render_export.v1` sidecar. Re-edit input is the exact previously reviewed candidate MP4, so timestamped review evidence remains in the coordinate system of the artifact the reviewer actually saw.

The R26 Media bridge maps only Growth R23's supported operation allowlist:

- `trim` / `cut`: remove the bounded reviewed interval;
- `crop_scale_reframe`: apply a bounded punch-in/reframe to the reviewed interval;
- `speed_change`: apply a deterministic 1.08x speed delta to the reviewed interval;
- `fade_transition`: apply bounded audio/video fades around the interval;
- `text_overlay`: add a bounded deterministic emphasis overlay;
- `subtitles_captions`: add a bounded emphasis caption;
- `audio_duck_mix`: reduce the reviewed audio interval by 4 dB; it fails if the input has no audio;
- `intro_outro_cta`: add a bounded CTA overlay.

The model's free-form proposed edit is never executed. Unsupported operations, invalid timestamps, an output outside the 15–60 second Creator publish profile, stale bytes, or technical QA failure stop the loop.

Each Media candidate has a request-bound recovery receipt. If Creator loses the ACK after Media has produced the MP4 and sidecar, restart recovers the same result with zero new logical Media effects.

## Terminal policy

Only Growth R23 state `winner` can materialize `final.mp4`, an R22-compatible final editor bundle, and the existing R23 editor-to-publish handoff. `tie`, `insufficient_evidence`, and `human_review` are non-publishable and produce no publish handoff.

A `targeted_reedit` at rounds 0 or 1 creates one next candidate. A request for another re-edit at round 2 is rejected. No path can create a third re-edit round.

The publish handoff is preparation only. R26 instantiates no provider adapter, stores no credential material, performs no social post, and does not bypass login, CAPTCHA, or 2FA.

## One-command runner

First run, with no review yet:

```bash
creator-real-review-r26 run \
  --source /path/to/final-or-source.mp4 \
  --brief "Make the edit concise" \
  --media-checkout /path/to/video2-at-a17f782d \
  --growth-r23-checkout /path/to/video3-at-26f769ab \
  --out /tmp/creator-r26
```

This renders the current candidate and exits successfully in `WAITING_FOR_REAL_REVIEW`, writing `review-request-r0.json` with the exact source/render/attachment provenance that an external capture must satisfy.

After a genuine external Growth R23 event is available:

```bash
creator-real-review-r26 run \
  --source /path/to/final-or-source.mp4 \
  --brief "Make the edit concise" \
  --media-checkout /path/to/video2-at-a17f782d \
  --growth-r23-checkout /path/to/video3-at-26f769ab \
  --out /tmp/creator-r26 \
  --review /path/to/external-review-r0.json
```

If that review requests a targeted edit, the same invocation produces the new real MP4 and writes `review-request-r1.json`. Re-run with both review files after the next external review. The same pattern is bounded at round 2.

`--allow-test-fixture` exists only for deterministic CI. A test fixture can verify transport, lineage, Media execution and restart behavior, but the output remains `BLOCKED_OR_TEST_ONLY` and is never evidence that a live model reviewed the video.

## Current live-review gate

Implementation is complete, but `REAL_REVIEW_EXECUTED` is not claimed in this milestone because this agent chat contains no genuine externally captured Growth R23 attached-video review event bound to an R26-produced candidate.

The exact blocker is:

`MISSING_EXTERNAL_GROWTH_R23_REAL_REVIEW_EVENT`

Required evidence is an external `creator.external_real_review_event.r26.v1` containing Growth R23 SHA `26f769abceb43a63677ea8f7ba028369db371696` and exact source/render/attachment/critic provenance matching a generated `review-request-rN.json`.

No live provider mutation or social publish is part of R26.
