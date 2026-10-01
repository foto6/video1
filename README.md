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
