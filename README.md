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
