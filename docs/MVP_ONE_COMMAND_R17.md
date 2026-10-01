# Creator R17 first MVP one-command pipeline

R17 is the first operator-oriented MVP. It deliberately does not add publishing, Growth, analytics, credentials, or another orchestration layer.

## What the command does

One invocation performs:

\`local video validation -> brief normalization -> deterministic local script/edit request -> exact Media R13 preflight -> Media render -> Media R13 result-envelope ingest -> technical QA -> creative QA -> atomic artifact export\`

The only operator outputs are:

- \`final.mp4\`
- \`preview.mp4\`
- \`qa.json\`
- \`run-summary.json\`

The managed render workspace is beneath \`<out>/.creator-mvp-work/<run-id>\`. It is marked with an ownership file before any cleanup is permitted. A rerun may clean only that marked directory; it never deletes, renames, or modifies the source video. Successful runs clean the managed workspace unless \`--keep-work\` is supplied.

## Exact Media R13 dependency

Before rendering, Creator validates a local read-only checkout of:

\`foto6/video2@ad4e0ba487a3cabc84dd339d412e19a0db0f9add\`

The CLI verifies:

- exact Git HEAD;
- no tracked/staged modifications;
- every Media R13 compatibility blob from R16;
- Creator's own vendored copies of those blobs;
- availability of \`node\`, \`git\`, \`ffmpeg\`, and \`ffprobe\`.

The thin bridge imports only the exact Media checkout's public \`src/index.js\` exports. It submits a real \`media.job.v1\` render, exercises duplicate-submit idempotency, obtains \`media.artifact_manifest.v1\`, evaluates Media creative QA, and asks Media itself to build \`media.creator_consumer_compat.r13.v1\`.

Creator then validates that producer-built envelope again using its pinned R13 contract/schema bundle and verifies that the final MP4 bytes match \`finalContent\`.

No sibling Media implementation is copied into Creator.

## Local deterministic fallback

External AI generation is not required for the MVP baseline. The brief is normalized locally and a small deterministic script/hook/beat structure is produced under \`creator.mvp_local_script.r17.v1\`.

Every run records:

\`generationMode=deterministic_local_fallback\`

and:

\`externalAiUsed=false\`

The fallback is therefore never represented as model-generated content.

Styles map directly to the pinned Media creative-plan presets:

- \`clean -> clean_podcast\`
- \`aggressive -> aggressive_shortform\`
- \`cinematic -> cinematic_minimal\`

## Exit codes

| Code | Meaning | Operator action |
| ---: | --- | --- |
| 0 | Success | Use the four exported files. |
| 2 | Bad input | Check video/brief/style; input must contain video and be at least 5 seconds. |
| 3 | Missing dependency | Install the named tool or provide the exact Media checkout with \`--media-repo\`. |
| 4 | Media mismatch | Reset Media to exact R13 SHA and verify pinned blobs; do not continue with a drifted checkout. |
| 5 | Render failed | Inspect the Media/ffmpeg error; rerun after correcting the source or dependency. |
| 6 | Technical QA failed | Do not use the render; correct the source/render problem. |
| 7 | Creative QA failed | Do not use the render; choose safer content/style or inspect guardrail evidence. |
| 8 | Insufficient evidence | Source-bound Media provenance was incomplete; do not accept the output. |
| 9 | Internal failure | Inspect the reported error and managed work directory. |

## Linux

Prerequisites: Python 3.11+, Node 20+, git, ffmpeg/ffprobe, this Creator checkout, and the exact Media R13 checkout.

After installing Creator with \`python -m pip install -e .\`, the pipeline itself is one command:

\`\`\`bash
creator-mvp --input ./source.mp4 --brief "Turn this into a concise proof-first vertical short" --out ./mvp-out --style clean --media-repo ../video2
\`\`\`

If \`../video2\` is the exact sibling checkout, \`--media-repo\` may be omitted.

## Windows PowerShell

After installing Creator with \`py -m pip install -e .\`:

\`\`\`powershell
creator-mvp --input ".\source.mp4" --brief "Turn this into a concise proof-first vertical short" --out ".\mvp-out" --style clean --media-repo "..\video2"
\`\`\`

The command does not access unrelated user directories and has no live-publish mode.

## Machine-readable readiness

\`reports/CREATOR_R17_MVP_READINESS.json\` defines the six required gates:

\`input_ok, media_pin_ok, render_ok, technical_qa_ok, creative_qa_ok, artifact_export_ok\`

At runtime the same six booleans are emitted into both \`qa.json\` and \`run-summary.json\`.

## E2E evidence

\`tests/test_creator_mvp_r17.py\` creates an actual MP4 plus audio with ffmpeg, runs the complete local pipeline against the exact Media R13 checkout, verifies \`final.mp4\` and \`preview.mp4\` exist, probes the final as 1080x1920 at 30fps, validates both QA reports, confirms the source file digest is unchanged, and checks that the managed workspace is cleaned.
