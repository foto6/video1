# Creator R22 bounded autonomous editor loop

R22 adds a bounded, restart-safe editorial loop without changing R11-R21 contracts.

Flow:

`source + brief -> R18 semantic director -> 2-4 stable candidate plans -> media.render_export.v1 adapter -> growth.critic_export.v1 adapter -> winner/tie/insufficient_evidence -> at most two targeted re-edit rounds -> final bundle or human-review pack`.

## Producer pins

Growth critic is source-bound to the observed green producer:

- repository: `foto6/video3`
- branch: `agent/growth-r16-benchmark-export-20261001`
- producer SHA: `cb50a3d78a18e6db1ebef1be69fdf11ff2e27385`
- CI: `36832188760 SUCCESS`
- contract: `growth.critic_export.v1`
- manifest blob: `8f76d27c893658b3838eb2dcbe696a926a60dab3`
- schema blob: `8b6f67dfaa015a824acd09e9a70121c8198ec72a`
- implementation blob: `be8342d3dd2d722855eaaf6902c9800da261b4c3`

Media was inspected rather than guessed. The only branch named for benchmark render export is:

- repository: `foto6/video2`
- branch: `agent/media-r15-benchmark-render-export-20261001`
- observed green HEAD: `e2b6af0d647c3677a13cdc4189bb8c85ffbca980`
- CI: `36832896059 SUCCESS`

That exact tree does **not** contain `media.render_export.v1`. R22 therefore does not claim a production Media render-export pin. Real producer mode fails closed until an exact green producer SHA plus contract/schema is supplied. Deterministic CI/rehearsal uses a clearly labeled synthetic `MediaRenderExportAdapter`.

## Bounded behavior

- initial candidates: exactly 2-4;
- maximum targeted re-edit rounds: exactly 2;
- candidate IDs are content-addressed from loop identity, ordinal, plan, parent candidate and concrete deltas;
- duplicate durable event keys are idempotent only when payloads match exactly;
- conflicting duplicates fail closed;
- render and critic operations recover by idempotency key before submit;
- accepted-but-unacknowledged synthetic operations survive restart without duplicate logical effects.

A re-edit is never generic prose. It is a structured delta such as:

- `tighten_hook_window` with an explicit lead-in and result-by target;
- `compress_span` with a bounded time range and reduction percentage;
- `move_cut_to_semantic_boundary` with tolerance;
- `reframe_subject` with target center and crop-loss bound;
- `remove_unmatched_broll` with semantic-match threshold;
- `reduce_caption_density` with line/character/time constraints;
- `preserve_continuity_span` with a no-cut constraint;
- `reduce_motion_intensity` with zoom/punch-in limits;
- `rebalance_voice_music` with dB deltas;
- `retime_payoff_or_cta` with explicit ending bounds.

## Decision boundary

Media technical QA is a hard gate. Growth critic evidence is heuristic and non-human.

A candidate is comparison-eligible only when enough critic dimensions are available above the configured confidence floor. Hard failures reject the candidate before comparison.

The loop emits:

- `winner` only when sufficient evidence separates the top two beyond tie epsilon and pairwise evidence does not contradict the scalar comparison;
- `tie` when top candidates fall within tie epsilon;
- `insufficient_evidence` when evidence is sparse or contradictory.

Tie/insufficient states trigger bounded targeted re-edits while rounds remain. After round 2, or when no viable candidate remains, R22 emits `creator.autonomous_edit_human_review.r22.v1`; it never invents a winner.

A winner emits `creator.autonomous_edit_final_bundle.r22.v1`.

Both outputs bind source SHA/ID, brief digest, semantic-analysis digest, semantic-directives digest, Media render/timeline/artifact digests, Growth critic evidence and the durable ledger digest.

## Rehearsal

Run:

```bash
creator-editor-loop-r22 --work-dir /tmp/creator-r22
```

The deterministic rehearsal uses four initial plans, forces a tie in round 0, another tie in round 1, then a reproducible winner in round 2. It injects one lost Media acknowledgement and one lost Growth acknowledgement. Restart recovery must preserve one logical effect per idempotency key.

Additional scenarios:

```bash
creator-editor-loop-r22 --work-dir /tmp/r22-insufficient --scenario insufficient --no-lost-ack
creator-editor-loop-r22 --work-dir /tmp/r22-contradictory --scenario contradictory --no-lost-ack
```

Both terminate in human review.

## Claim boundary

R22 performs no publishing and makes no `HUMAN_LEVEL` claim. Synthetic rehearsal evidence is conformance evidence only.
