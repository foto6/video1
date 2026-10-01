# Creator R24 exact-pin closed-loop runner

R24 executes a real-artifact rehearsal from a source MP4 and brief through bounded R22 candidate planning, exact-pinned Media R15 renders/exports, exact-pinned Growth R18 candidate decision, at most two targeted re-edit rounds, terminal editor bundle construction, and R23 publish-handoff preparation.

No provider is instantiated or driven. No live social post, credential lookup, CAPTCHA/2FA path, or provider mutation occurs.

## Exact dependencies

Media:
- repository: foto6/video2
- exact SHA: a17f782da8144d1e890ac83195396a3192df93c2
- exact-head CI: 36860193113 SUCCESS
- contract: media.render_export.v1
- manifest blob: 945acb01ff0269d89b91463aa8d862f500e055b2
- schema blob: 6353d32d785a2a1f1441bac4cfd0271b46b41d4a

Growth:
- repository: foto6/video3
- exact SHA: 2d3bf275c5b456d53384073fb7ec1ed992e6b996
- exact-head CI: 36859378847 SUCCESS
- contract: growth.candidate_decision.v1
- manifest blob: 05e778e7a67556b66cb407e2c65a2f7bb391dbab
- schema blob: 75a3efbb8a4e14789508dae11ae8db92723d0e27

The runner checks each checkout's HEAD and recomputes each contract manifest/schema Git blob SHA before work. A moving branch, stale checkout, altered manifest, or altered schema fails closed.

## Command

```bash
creator-closed-loop-r24 \
  --source ./source.mp4 \
  --brief "Make the proof concise" \
  --media-checkout ../video2-r15 \
  --growth-checkout ../video3-r18 \
  --out ./closed-loop-out \
  --candidates 2
```

Both sibling paths are read-only dependencies. R24 writes only under its own output directory.

## Artifact exchange

Creator writes `creator.media_r15_render_request.r24.v1` JSON per candidate. The Media bridge imports the exact checked-out Media producer and executes the real R11/R12/R15 runtime:

- deterministic timeline + creative plan;
- real ffmpeg render;
- real QA probe;
- real `media.artifact_manifest.v1`;
- real `media.render_export.v1` sidecar;
- byte-level render hash verification.

The Media bridge performs an exact duplicate submit before processing and rejects any idempotency regression. On restart it recovers an existing canonical `final.mp4` + R15 sidecar instead of rendering again.

Creator writes `creator.growth_r18_decision_request.r24.v1`. The Growth bridge imports the exact checked-out Growth R18 implementation, builds source/render-bound `growth.critic_export.v1` structural conformance inputs, and invokes the real `build_candidate_decision()` implementation. The resulting `growth.candidate_decision.v1` is consumed without sibling implementation imports inside Creator.

The structural critic inputs are explicitly synthetic/conformance evidence; the rendered MP4s and Media R15 exports are real artifacts.

## Bounded editor behavior

- initial candidates: 2-4;
- maximum targeted re-edit rounds: 2;
- Growth `winner` produces a final R22 bundle;
- Growth `tie` after round 2 remains tie;
- Growth `insufficient_evidence` stops immediately;
- configured `human_review_required` converts a terminal unresolved tie after the second re-edit round into human review.

Only a winner receives an R23 `creator.editor_publish_handoff.v1` artifact. The handoff is preparation-only: R24 does not instantiate a publish provider or call submit/status/recover.

## Restart and lineage

The durable `creator.closed_loop_rehearsal_ledger.r24.v1` makes repeated identical events idempotent and rejects conflicting duplicates.

Every boundary checks:
- source SHA and duration;
- semantic/directive digests;
- stable candidate/plan digest;
- exact Media producer SHA;
- R15 `final.mp4` bytes == render-export SHA;
- Growth source SHA and candidate set;
- monotonically increasing Growth decision revision;
- winner render SHA copied byte-for-byte into canonical `final.mp4`;
- final bundle digest;
- R23 handoff digest.

Re-running the same output directory recovers existing Media R15 render sidecars, providing the restart/lost-ack recovery proof without a second render effect.

## Safety

The rehearsal uses no credentials and performs no provider/network side effect. Opaque R23 credential references are inert metadata only. No HUMAN_LEVEL or live-publishing claim is made.


## Exact-pin source path binding

The exact Media R15 producer at `a17f782da8144d1e890ac83195396a3192df93c2` has two relevant path semantics:

- `src/runtime/path-policy.js::resolveSandboxedPath` resolves sources against the configured `sandboxRoot` and permits an absolute path only when it remains inside that sandbox.
- `src/ffmpeg.js::compileFfmpegCommand` passes each timeline `source.uri` directly to ffmpeg rather than substituting the path-policy resolved value.

Therefore a timeline URI such as `inputs/source.mp4` is validation-safe but execution-cwd-sensitive. R24 now copies the source to `<candidate sandbox>/inputs/source.mp4`, verifies the copied SHA-256 and byte size exactly, asserts the canonical copy is still inside the candidate sandbox, and binds `source.uri` to that canonical sandbox-contained absolute path.

This does not permit external absolute paths or traversal. Media R15's existing sandbox check remains authoritative. The focused integration regression changes the caller cwd to an unrelated directory before invoking the exact-pinned render and proves both first execution and idempotent resume still resolve the same source.
