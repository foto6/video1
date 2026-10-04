# Creator Orchestrator

Provider-neutral, durable content-production control plane for YouTube/TikTok workflows.

Pipeline:

`research -> idea -> script -> assets -> voice -> edit -> critic -> publish queue -> analytics feedback`

The core includes a durable JSON-backed state machine, stable idempotency keys, retry/recovery state, immutable artifact lineage, evaluation hooks, explicit Runway/Descript/Metricool/vidIQ boundaries, and the frozen Growth `1.0` + Media `media.render.v1` integration boundary.

## Autonomous Content Cycle Simulator v2

Round 2 adds a deterministic local campaign simulator that runs multiple sequential jobs, feeds cycle N analytics into cycle N+1 as validated Growth feedback, supports restart after every stage, bounded critic revisions, explicit failure injection, media dry-run fingerprints, fake provider contract harnesses, campaign-wide DAG validation, and a final metrics/report artifact.

Sample campaign:

`fixtures/campaign.autonomous.v2.json`

Deterministic expected output:

`fixtures/campaign.autonomous.v2.expected.json`

Run the demo:

```bash
PYTHONPATH=src python -m creator_orchestrator.demo \
  fixtures/campaign.autonomous.v2.json \
  /tmp/creator-round2-demo
```

Real publishing remains disabled. The simulator has no live-publish mode; Metricool remains queue/dry-run only.

## Run tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

See `docs/ARCHITECTURE.md` and `docs/AUTONOMOUS_CYCLE_SIMULATOR_V2.md`.


## Durable external operations

Opt-in resumable adapters can persist provider-operation receipts across `prepared -> accepted -> result_obtained -> committed` without changing the synchronous adapter path. See `docs/EXTERNAL_OPERATION_RECOVERY.md`.


## Exact producer integration

Wave 4 adds strict `growth.creator_seed.v1` ingestion and concrete `media.job.v1` durable resume/poll integration using pinned producer fixtures. See `docs/EXACT_GROWTH_CREATOR_MEDIA_DURABLE_INTEGRATION.md`.


## Reproducible campaign checkpoints

`creator.campaign_checkpoint.v1` exports canonical content-addressed campaign state, durable stage/operation receipts, Growth/Media identities, lineage and producer provenance for idempotent restore/resume. Deterministic boundary fixtures and a reproducibility report live under `fixtures/checkpoints/`. See `docs/CAMPAIGN_CHECKPOINT_V1.md`.


## Durable human approval gate

`release.authorization.v1` binds a queued artifact hash and complete campaign lineage to explicit external approval, exact destination scope, expiry and idempotency. Only local simulated release execution is supported; live external mutation remains disabled. See `docs/RELEASE_AUTHORIZATION_V1.md`.


## First MVP: one-command vertical render

Creator R17 turns one local source video plus a short brief into a finished vertical MP4 through the exact pinned Media R13 producer. Publishing, Growth, analytics, and credentials remain disabled.

Install this checkout once:

\`\`\`bash
python -m pip install -e .
\`\`\`

Linux:

\`\`\`bash
creator-mvp --input ./source.mp4 --brief "Turn this into a concise proof-first vertical short" --out ./mvp-out --style clean --media-repo ../video2
\`\`\`

Windows PowerShell:

\`\`\`powershell
creator-mvp --input ".\source.mp4" --brief "Turn this into a concise proof-first vertical short" --out ".\mvp-out" --style clean --media-repo "..\video2"
\`\`\`

The output directory contains exactly the operator-facing artifacts \`final.mp4\`, \`preview.mp4\`, \`qa.json\`, and \`run-summary.json\`. If Media R13 is checked out as sibling \`../video2\`, the \`--media-repo\` argument can be omitted.

External AI is not needed for the baseline: when unavailable, the command explicitly records \`deterministic_local_fallback\` and never labels that text as model output. See \`docs/MVP_ONE_COMMAND_R17.md\` for exact Media pins, exit codes, cleanup semantics, and E2E evidence.


## Semantic auto-director

Creator R18 adds source-bound semantic directing before the existing R17 Media R13 render. The same \`creator-mvp\` command now supports evidence-based automatic style selection:

\`\`\`bash
creator-mvp --input ./source.mp4 --brief "Turn this into a concise proof-first vertical short" --out ./mvp-out --style auto --media-repo ../video2
\`\`\`

\`--style auto\` is the default. Explicit \`clean\`, \`aggressive\`, \`cinematic\`, or \`hybrid\` still wins over the auto-director, with material disagreement recorded in \`director-report.json\`.

R18 never invents missing ASR/CV/VLM semantics. Local ffmpeg shot/silence evidence is used when available; unavailable semantic categories are listed explicitly. The output now retains the original R17 artifacts plus \`director-report.json\`.

Readiness is \`SEMANTIC_PIPELINE_READY\`; human-level editing quality remains \`HUMAN_LEVEL_UNPROVEN\`. See \`docs/SEMANTIC_DIRECTOR_R18.md\`.


## Optional Gemini native-video semantics

R18B adds a concrete Google Gemini native-video provider behind the existing semantic adapter boundary. It is disabled by default.

```bash
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-3.8-flash"
creator-mvp --input ./source.mp4 --brief "Find the proof" --out ./mvp-out --style auto --semantic-provider gemini --gemini-mode static --gemini-fps 2 --media-repo ../video2
```

The real MP4 is uploaded as video input; it is not replaced by contact-sheet text. Static FPS/clipping are configurable. Agentic mode is optional and requires an explicit model-capability flag. CI uses only `FakeGeminiVideoTransport` and performs no Gemini network or paid calls.

Live smoke is separately gated:

```bash
CREATOR_GEMINI_VIDEO_ENABLE=1 GEMINI_API_KEY="..." creator-gemini-video-smoke --input ./source.mp4 --live
```

Without all live gates it returns `BLOCKED` and does not attempt network access. Human-level quality remains `HUMAN_LEVEL_UNPROVEN`. See `docs/GEMINI_NATIVE_VIDEO_R18B.md`.


## Content-aware one-command MVP

R19 makes semantic directing part of the normal `creator-mvp` path. Both style and semantic provider selection default to `auto`:

```bash
creator-mvp --input ./source.mp4 --brief "Make a concise proof-first short" --out ./mvp-out --media-repo ../video2
```

If Gemini native-video is explicitly configured with `CREATOR_GEMINI_VIDEO_ENABLE=1` and `GEMINI_API_KEY`, auto mode attempts it. Otherwise Creator records a deterministic-local semantic fallback; it never presents fallback evidence as model understanding.

In addition to the R17 render outputs, runs now emit `semantic-timeline.json`, `editorial-directives.json`, `style-decision.json`, and the benchmark-consumable `content-aware-run.json`. Manual `--style` overrides still win and remain provenance-bound.

R19 claims content-aware evidence only. Human-level quality remains `HUMAN_LEVEL_UNPROVEN`. See `docs/CONTENT_AWARE_MVP_R19.md`.


## Canonical benchmark semantic export

R20 adds the benchmark-owned Creator producer export required by `boss.human_editing_gate.v1`:

`creator.semantic_export.v1.json`

It is emitted directly from the R19 runtime semantic/director state and contains exactly the benchmark-supported fields. The export binds the exact Creator Git commit, source SHA, brief digest, semantic/directive digests, explicit unavailable evidence, and a generation mode that distinguishes Gemini evidence from deterministic local fallback.

A benchmark corpus may pass its frozen ID with `--source-id`; otherwise Creator derives a deterministic source ID from the source SHA. Existing R19 artifacts and one-command behavior remain unchanged.

See `docs/SEMANTIC_EXPORT_R20.md` and `conformance/creator.semantic_export.v1/`.


## Production publish execution

R21 adds executable Instagram Reels, TikTok Direct Post, and YouTube Shorts transports behind the unchanged R12 durable provider contract. Production credentials remain external and Creator state stores only opaque credential references.

No provider is live-enabled merely by installing R21. Each path performs account/media/capability preflight and stops for interactive authorization, expired/revoked credentials, or unverified provider access.

For side-effect-free end-to-end validation:

```bash
creator-publish-sandbox --media ./final.mp4 --authorization ./release.authorization.v1.json --platform tiktok --account-id sandbox-account --destination privacy:SELF_ONLY --credential-ref vault-ref://sandbox/tiktok --caption "Sandbox publish" --cta "Learn more" --out ./publish-sandbox
```

See `docs/PUBLISH_EXECUTION_R21.md` and `reports/CREATOR_R21_PUBLISH_READINESS.json`.


## Bounded autonomous editor loop

R22 adds a durable editorial tournament loop over the existing semantic director: 2-4 stable candidate plans, render-export consumption, Growth critic comparison, at most two concrete re-edit rounds, then either a final bundle or an explicit human-review pack.

The Growth critic consumer is pinned to `growth.critic_export.v1` at `foto6/video3@cb50a3d78a18e6db1ebef1be69fdf11ff2e27385`. The observed green Media benchmark branch at `e2b6af0d647c3677a13cdc4189bb8c85ffbca980` does not yet contain the required `media.render_export.v1` producer contract, so production Media use is fail-closed; the R22 rehearsal is explicitly synthetic.

Run the deterministic rehearsal:

```bash
creator-editor-loop-r22 --work-dir /tmp/creator-r22
```

It exercises two targeted re-edit rounds plus lost-ack restart recovery. Tie, contradictory, or insufficient evidence cannot fabricate a winner after the configured bound. No publishing or `HUMAN_LEVEL` claim is part of R22. See `docs/AUTONOMOUS_EDITOR_LOOP_R22.md`.


## Editor-to-publish handoff

R23 adds `creator.editor_publish_handoff.v1`, which accepts only a terminal R22 winner, binds its exact `final.mp4` SHA and release authorization, persists publish intent, then delegates to the unchanged R12/R21 recover-before-submit provider flow.

Synthetic validation command:

```bash
creator-editor-publish-r23 --media ./final.mp4 --editor-bundle ./terminal-result.json --authorization ./release.authorization.v1.json --platform tiktok --account-id account-r23 --destination privacy:SELF_ONLY --credential-ref vault-ref://tiktok/r23 --authorization-ref oauth-grant-ref://tiktok/r23 --caption "R23 synthetic handoff" --out ./r23-out
```

The command uses synthetic providers only and cannot perform a live social post. See `docs/EDITOR_PUBLISH_HANDOFF_R23.md`.


## Exact-pin real-artifact closed loop

R24 can execute the R22/R23 closed loop against explicit immutable sibling checkouts:

```bash
creator-closed-loop-r24 --source ./source.mp4 --brief "Make the proof concise" --media-checkout ../video2-r15 --growth-checkout ../video3-r18 --out ./r24-out --candidates 2
```

The runner refuses any checkout not exactly at Media R15 `a17f782d...` or Growth R18 `2d3bf275...`, verifies the pinned contract blobs, renders real MP4 candidates through the Media runtime, consumes Growth's actual candidate-decision implementation, enforces at most two targeted re-edit rounds, and prepares an R23 handoff only for an eligible winner. It never invokes a publish provider.


## Real live-review execution

R27 executes externally supplied review directives through exact Media R19 and separates source readiness from genuine capture execution. The production gate currently remains `BLOCKED_WAITING_REAL_CAPTURE`: Growth R25 has not yet produced an exact-pinned Creator-ready envelope, and Media R20 has not yet produced the dynamic next-round blinded package contract.

`creator-live-review-r27 readiness` reports `SOURCE_READY`, `REAL_REVIEW_INGESTED`, `REAL_REEDIT_EXECUTED`, and `PUBLISH_HANDOFF_READY` independently.

CI uses an explicitly labeled fixture envelope only to prove the exact Media R19 application/replay boundary. Fixture evidence never sets the real-review/re-edit stages. See `docs/REAL_LIVE_REVIEW_EXECUTION_R27.md`.


## Dynamic live-review loop

R28 replaces R27's frozen review dependency snapshot with exact runtime authority profiles. The current profiles pin Media R20 `b22174db3c772a49a21fb9f8b1d40828bf258005` and Growth R25 `2c441ebaa017c7da72461316401aeaf445e3d6e5`, including contract/schema/implementation Git blobs.

For a validated `targeted_reedit`, Creator executes the exact Media R19 runtime present at the R20 head, verifies the changed MP4 plus `media.editorial_reedit_application.v1` and `media.render_export.v1`, then invokes the exact Media R20 dynamic blinded-package builder for the next round. Replays recover the same edit/package identities and the loop enforces at most two re-edit rounds.

Readiness:

```bash
creator-dynamic-live-review-r28 readiness --out ./r28-readiness.json
```

The current production state is `BLOCKED_WAITING_DYNAMIC_REVIEW_CAPTURE`: Media R20, Growth R25, and Bridge R29 are exact-green, but no exact-green dynamic Growth R26 / Bridge R30 capture authority or genuine next-round capture is available here. Creator does not substitute fixture/model evidence for that missing capture.

Only a terminal external-review winner can produce the existing R23 publish handoff, and R28 never invokes a social provider. See `docs/DYNAMIC_LIVE_REVIEW_LOOP_R28.md`.


## Coordinator live-review continuation (R30)

R30 consumes an exact Growth R27 coordinator index plus a selected canonical Creator envelope, verifies exact Growth R27 / Bridge R31 / Media R22 authority, executes at most two real Media re-edits, and materializes the next blinded operator package through Media R22. It performs no browser or social-provider mutation.

Use `creator-coordinator-r30 continue ...` for genuine coordinator evidence or `creator-coordinator-r30 rehearsal --out .r30-rehearsal` for a real-MP4 source-ready rehearsal that deliberately stops at `WAITING_GENUINE_CAPTURE`. See `docs/COORDINATOR_CONTINUATION_R30.md`.


## Live session authority / continuation (R31)

R31 freezes Media R23 `78c6982a91d7e3e8c037cd9ce740ee077babdccc`, Growth R28 `629a2b9ddf59b84eee4e87b257c161dad42831dc`, and Bridge R32 `805bf628d3d2844549b54db1112736fae0200fc7` by exact producer SHA, CI run, contracts, schemas, and implementation blobs.

The continuation command consumes a Growth R28 multi-round session ledger, matching Bridge R32 round result, and exact Creator envelope. A targeted re-edit runs the real Media R19 path inside the exact R23 checkout and immediately creates the next `media.review_session_package.r23.v1`. Only a terminal winner can create `final.mp4` and the existing publish handoff; no social provider is invoked.

```bash
creator-live-session-r31 readiness --out ./r31-readiness.json
creator-live-session-r31 rehearsal --out ./r31-rehearsal
```

Without a genuine live session capture, readiness intentionally remains `WAITING_GENUINE_CAPTURE`. See `docs/LIVE_SESSION_AUTHORITY_R31.md`.


## Autonomous tournament coordinator (R32)

R32 adds `creator.autonomous_tournament.r32.v1`: a crash-safe tournament state machine for 2–4 edit candidates, three independent blinded reviews, consensus, at most two targeted re-edits, the next review round, and a winner-only publish-handoff boundary.

The current exact-green authority floor is Media R24 `244acdf154741e669991b17df3ef2a47e2dfdfa9`, Growth R29 `3e4a8ad6d73b058c953abeadba7a60abe567adbc`, and Bridge R34 `4e2a37545cc0cdd940cf6e86d40e0d620d6c94ae`. The expected R25/R30/R35 contracts are not present at the observed heads, so runtime status is deliberately `AUTONOMOUS_LOOP_SOURCE_READY` / `WAITING_UPSTREAM_GREEN`; branch names are not accepted as authority.

The deterministic chaos rehearsal uses frozen contract fixtures only and proves crash/restart, lost-Send acknowledgement reconciliation, no blind retry, one targeted re-edit, second-round winner selection, and byte-stable winner-handoff replay:

```bash
creator-autonomous-tournament-r32 readiness
creator-autonomous-tournament-r32 chaos-rehearsal --out .r32-chaos
creator-autonomous-tournament-r32 status --ledger .r32-chaos/autonomous-tournament-ledger.jsonl
```

No browser/provider mutation, live publish, credentials, or human-ground-truth claim is performed. See `docs/AUTONOMOUS_TOURNAMENT_R32.md`.


## Exactly-once publish transaction safety (R33)

R33 inserts a provider-neutral crash-safe transaction coordinator between the R32 winner handoff and the existing Instagram Reels, TikTok Direct Post and YouTube Shorts adapters. It freezes Creator R32 at `f0dc1d27da6452f1de32cd887651805b47a1735d`, CI `37199512624`, artifact `11302367811`, digest `sha256:6803db334974b8dbea1c30c107ec5af00fe2cb892ed67e68540c2b2d74b18599`.

The transaction states are `PREPARED -> VALIDATED -> COMMIT_ELIGIBLE -> COMMITTING -> COMMITTED`, with `RECONCILIATION_REQUIRED` for ambiguous provider outcome and `ABORTED` only where no side effect can have occurred or provider absence has been proven. Unknown outcome never triggers blind retry.

R33 has no real-provider execution path. CI and the deterministic rehearsal use only the explicit fake-provider harness and record zero network/provider effects:

```bash
creator-publish-transaction-r33 readiness
creator-publish-transaction-r33 rehearsal --out .r33-rehearsal
creator-publish-transaction-r33 status --ledger .r33-rehearsal/youtube_shorts.jsonl
```

Readiness is `SOURCE_READY_NO_LIVE_PUBLISH`. See `docs/PUBLISH_TRANSACTION_R33.md`.


## Multi-platform publish saga (R34)

R34 coordinates one R32 winner across Instagram Reels, TikTok and YouTube Shorts using three independent R33 exactly-once child transactions. It freezes the exact R33 candidate `9556108f423a15a40614a8bc9d590e6dc2e49746` / CI `37203622591` / artifact `11304071297`. Independent QA-R3 at `foto6/boss@2a48c909bfb5785409b591253f6085642b962d0d`, CI `37207701514 SUCCESS`, artifact `11305557095` / `sha256:4c5cb2c476643a03865ec37c084650db4c98c84c3aed04aafeb35b81b4e9fba0` accepts that exact R33 authority as `PUBLISH_TRANSACTION_SOURCE_READY`. R34 itself remains `SOURCE_READY_PENDING_R34_QA`, not LIVE_READY.

Saga states distinguish `ALL_PENDING`, `PARTIALLY_COMMITTED`, `RECONCILIATION_REQUIRED`, `ALL_COMMITTED`, and `TERMINAL_BLOCKED`. Unknown provider outcome is never replay-authorized; only read-only reconciliation may promote it to committed with exact R33 evidence. Committed external posts are never locally rolled back—R34 compensation is metadata only.

The default release policy requires all three platforms before global success. Release-window start/deadline/revision and per-platform config revision are part of stable intent identity.

```bash
creator-multiplatform-publish-r34 readiness
creator-multiplatform-publish-r34 chaos-rehearsal --out .r34-chaos
creator-multiplatform-publish-r34 status --saga-dir .r34-chaos/partial-saga --at-time 2026-10-05T12:30:00Z
```

R34 is fake-provider only and performs zero provider-network effects. See `docs/MULTIPLATFORM_PUBLISH_SAGA_R34.md`.
