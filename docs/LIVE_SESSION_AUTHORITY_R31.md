# Creator R31 live session authority / continuation binding

R31 upgrades the R30 continuation boundary to the exact multi-round authorities currently green on 2026-10-02.

## Frozen authorities

- Media R23: `foto6/video2@78c6982a91d7e3e8c037cd9ce740ee077babdccc`, CI `37007419237 SUCCESS`, contract `media.review_session_package.r23.v1`.
- Growth R28: `foto6/video3@629a2b9ddf59b84eee4e87b257c161dad42831dc`, CI `37006476121 SUCCESS`, round contract `growth.multiround_review_round_result.r28.v1`.
- Bridge R32: `foto6/WebAIBridge@805bf628d3d2844549b54db1112736fae0200fc7`, CI `37006524677 SUCCESS`, round contract `bridge.r32_live_review_session_round_result.v1`.

The committed authority profile records contract/schema/implementation Git blob IDs. Runtime checkouts are accepted only at those exact SHAs and blobs. Branch names are not authority.

## Continuity

The command validates one review round as a single chain:

`Bridge R32 round -> Growth R28 session ledger/round result -> exact Creator envelope -> reviewed candidate bytes -> real Media re-edit -> Media R23 next-round package`.

It binds review round, Growth session identity, Bridge request/operation/response/capture digests, nested R21 package/prompt/sealed-mapping digests, selected envelope/handoff identity, candidate/render SHA and size, Media application digest, changed output MP4 SHA/size, and the R23 session package identity/digests.

For a Growth action envelope marked `targeted_reedit`, the envelope is deliberately the reviewed candidate that lost the pairwise choice and needs repair. R31 therefore verifies that Growth R28's `selected_result` is the *other* candidate; a terminal `winner` envelope must match `selected_result` exactly.

## Bounded continuation

Review rounds are exactly 0, 1, 2. At most two targeted re-edits are allowed.

A targeted re-edit invokes the exact Media R19 implementation contained in the R23 checkout, verifies `media.editorial_reedit_application.v1`, `media.render_export.v1`, changed real MP4 bytes, then invokes the exact R23 exporter. The exporter builds the R21 round and R22 self-contained operator artifact internally and emits `media.review_session_package.r23.v1`.

The durable R31 journal records session authority identity, review response/capture, candidate/render, edit result, application digest and next R23 package/session identities. Exact replay is idempotent. Any changed response, envelope or package for the same durable key fails closed.

Only a terminal Growth winner with `terminal_winner=true` can create canonical `final.mp4` and the existing editor-publish handoff. Tie, insufficient evidence and human review are non-publishable.

## Operator command

With a genuine Growth R28 session directory:

```bash
creator-live-session-r31 continue \
  --media-r23-checkout ../video2-r23 \
  --media-r23-authority ./conformance/creator.live_session_authority.r31.v1/authority-profiles.json \
  --growth-r28-checkout ../video3-r28 \
  --growth-session-dir ./growth-session \
  --review-round 0 \
  --bridge-r32-round-result ./bridge-round-0.json \
  --selected-envelope ./creator-envelope.json \
  --candidate-root ./candidate-root \
  --candidate-context ./candidate-context.json \
  --out ./r31-out
```

If the genuine Bridge/Growth round files are not supplied, the same command can be invoked without the two review arguments and stops at `WAITING_GENUINE_CAPTURE`.

## Rehearsal and safety

`creator-live-session-r31 rehearsal --out .r31-rehearsal` creates and probes a real vertical MP4 but intentionally stops at the external review boundary. It does not fabricate a model response.

R31 performs no browser mutation and invokes no social provider. It contains no credential or CAPTCHA/2FA automation and makes no human-parity claim.
