# Creator R18 semantic video director

R18 keeps the R17 one-command MVP intact and inserts one evidence-bound directing step before Media R13 rendering.

The semantic contract is \`creator.semantic_video_analysis.r18.v1\`. The human-reviewable director report is \`creator.semantic_video_director.r18.v1\`.

## Evidence model

Every inference is time-bounded and includes confidence plus source provenance. The semantic timeline can contain:

- transcript segments and sentence boundaries;
- shot boundaries;
- tracked faces/people/salient subjects;
- important products, screens, devices or other objects;
- visual/motion energy;
- audio energy, measured silence, source-bound speech spans, and explicitly unavailable music classification;
- semantic events: hook, setup, proof/demo, explanation, punchline/payoff, CTA candidate, low-information spans.

No absent provider evidence is invented. Missing categories are named in \`unavailableEvidence\`.

The local baseline can use ffmpeg scene detection and silence detection. ASR, CV tracking and VLM semantics are adapter boundaries. They have no repository credentials and default to \`unavailable\` unless an adapter is explicitly supplied.

## Adapter boundaries

R18 defines explicit adapter protocols for:

- ASR;
- scene/shot detection;
- CV saliency/person/object tracking;
- optional VLM semantic analysis.

Every adapter returns \`creator.semantic_adapter_result.r18.v1\` with its availability state, evidence, unavailable categories and reason.

Deterministic fixture adapters exist only for conformance and tests. They are labeled as fixture-provider evidence and do not establish human-level quality.

## Automatic editorial mode

The auto-director chooses among:

- \`clean_podcast\`;
- \`aggressive_shortform\`;
- \`cinematic_minimal\`;
- \`hybrid\`.

The decision emits per-mode scores, rationale, confidence and the exact evidence-derived features that caused the choice. \`hybrid\` uses Media's \`clean_podcast\` preset as a conservative base plus semantic hints/directives; Creator does not invent a fourth Media R13 preset.

An explicit operator style wins. When the auto-director has material confidence and disagrees, \`materialDisagreement=true\` is written to the report instead of silently hiding the disagreement.

The R17 command remains valid:

\`\`\`bash
creator-mvp --input ./source.mp4 --brief "Make this concise" --out ./mvp-out --style clean --media-repo ../video2
\`\`\`

R18 also supports evidence-based automatic selection:

\`\`\`bash
creator-mvp --input ./source.mp4 --brief "Make this concise" --out ./mvp-out --style auto --media-repo ../video2
\`\`\`

\`auto\` is now the default when \`--style\` is omitted.

## Semantic edit directives

R18 generates structured directives before Media render:

- preserve important object/product/screen reveals;
- use source-bound sentence boundaries to avoid mid-sentence cuts;
- compress locally supported low-information spans;
- strengthen the first 1–3 seconds only to the degree hook evidence supports it;
- emphasize source-bound punchline/payoff moments;
- allow B-roll only when proof/object evidence provides a semantic match;
- emphasize captions only from source-bound transcript evidence;
- preserve continuity around demos/screens/products;
- propose loops only when payoff evidence supports them;
- propose CTA only when source-bound CTA evidence exists.

These directives are converted into Media R13 creative hints: sentence boundaries, shot/beat markers, silence ranges, saliency and caption tokens. Media still compiles the final creative plan and retains all R13 technical/creative QA gates.

## Human-reviewable report

Successful or failed downstream render attempts retain \`director-report.json\` in the operator output directory. It includes:

- semantic timeline;
- auto/effective style;
- rationale and confidence;
- key moments;
- spans to preserve/compress;
- continuity ranges;
- B-roll rationale;
- caption emphasis;
- loop/CTA proposals;
- unavailable evidence.

The readiness label is:

\`SEMANTIC_PIPELINE_READY\`

The quality claim remains:

\`HUMAN_LEVEL_UNPROVEN\`

Synthetic fixtures are never treated as a human benchmark.

## Deterministic conformance fixtures

R18 includes:

- talking-head explainer → clean podcast;
- product demo → hybrid;
- story/punchline → aggressive shortform;
- cinematic montage → cinematic minimal;
- static low-energy clip → clean podcast.

The fixture tests validate evidence provenance, chosen mode and semantic directives.

The adapter-backed integration test goes further: it generates a real MP4, runs the exact Media R13 pipeline with sparse fallback evidence, then reruns the same source with ASR/shot/VLM fixture adapters. It proves that semantic evidence changes the effective editorial mode, the Media semantic-hints digest and the actual Media creative-plan digest.

## Safety

Publishing, Growth, analytics and credentials remain disabled. Media R13 stays pinned to \`foto6/video2@ad4e0ba487a3cabc84dd339d412e19a0db0f9add\`. R18 does not modify Media or Growth repositories.
