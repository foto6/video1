# Creator R19 content-aware one-command MVP

R19 makes the existing `creator-mvp` operator path content-aware by default.

## Default flow

```text
local source video
  -> ffprobe/source hash
  -> R18 semantic analysis
  -> source-bound auto style + directives
  -> exact Media R13 render
  -> Media technical/creative QA
  -> final operator artifacts
```

`--style auto` remains the default. Explicit `--style clean|aggressive|cinematic|hybrid` still wins and the override is written into `style-decision.json`.

Semantic provider selection now defaults to `--semantic-provider auto`.

- If `CREATOR_GEMINI_VIDEO_ENABLE=1` and `GEMINI_API_KEY` are present, Creator attempts the R18B Gemini native-video provider.
- If Gemini is not configured, unavailable, times out, or returns invalid output, Creator uses deterministic/local R18 evidence and records `fallback=true` plus the reason.
- `--semantic-provider local` explicitly selects local evidence and is not mislabeled as model understanding.
- `--semantic-provider gemini` explicitly attempts Gemini but still fails closed to the local baseline if provider evidence is unavailable.

No fallback is represented as Gemini/model understanding.

## Operator command

Linux:

```bash
creator-mvp --input ./source.mp4 --brief "Make a concise proof-first short" --out ./mvp-out --media-repo ../video2
```

Windows PowerShell:

```powershell
creator-mvp --input ".\source.mp4" --brief "Make a concise proof-first short" --out ".\mvp-out" --media-repo "..\video2"
```

The operator may still add `--style clean` or another manual style.

## Outputs

R19 preserves the R17 outputs and adds benchmark/review artifacts:

- `final.mp4`
- `preview.mp4`
- `qa.json`
- `run-summary.json`
- `semantic-timeline.json`
- `editorial-directives.json`
- `style-decision.json`
- `director-report.json`
- `content-aware-run.json`

The first three semantic artifacts are persisted before Media render. They remain available if downstream rendering fails.

## Explainable style decision

`style-decision.json` uses `creator.style_decision.r19.v1` and records:

- selected/effective editorial mode;
- confidence;
- source semantic features;
- all rejected alternatives with scores and score deltas;
- supporting rationale per alternative;
- exact source SHA/semantic-analysis binding;
- manual override provenance and material disagreement.

No human-level or aesthetic-superiority claim is made.

## Editorial directives

`editorial-directives.json` uses `creator.editorial_directives.r19.v1`. It binds the source SHA, semantic timeline digest, style-decision digest, and the R18 directives/hints passed to the exact Media R13 creative-plan compiler.

Media technical and creative QA remain authoritative. R19 does not bypass either gate.

## Benchmark envelope

`content-aware-run.json` uses `creator.content_aware_run.r19.v1` and binds:

- source SHA/duration/dimensions/FPS;
- semantic provider/model/mode identity and fallback state;
- semantic timeline digest;
- style-decision digest;
- directives digest;
- exact Media R13 producer SHA and contract/blob pins;
- Media render/timeline/artifact-manifest digests;
- final/preview file digests;
- technical/creative QA digests and pass states.

The envelope explicitly records `contentAwareEvidence=true`, `humanLevelQualityClaimed=false`, and `aestheticSuperiorityClaimed=false`.

## Real E2E evidence

R19 CI generates and renders three actual MP4 fixtures through the exact Media R13 producer:

- talking-head-like static composition;
- fast-cut action source;
- landscape screen-like source.

The local fallback path is used with Gemini credentials disabled. Tests prove the talking-head-like fixture selects `clean_podcast`, the fast-cut source selects `cinematic_minimal`, their semantic directives differ, all R19 artifacts exist, Media QA passes, and the landscape source remains correctly source-bound.

A separate regression renders the fast-cut source with `--style clean` and proves the manual override wins while the auto-director's rejected choice and disagreement remain recorded.

## Scope

Publishing, Growth, analytics, credentials, human-level claims, and aesthetic-superiority claims remain out of scope.
