# Creator R18B Gemini native-video semantic provider

R18B adds one concrete optional provider behind the R18 semantic adapter boundary: Google Gemini native-video understanding. The provider is disabled by default and does not change the local deterministic R18 path.

## Enabling the provider

The normal MVP remains local/no-network unless the operator explicitly selects Gemini:

```bash
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-3.8-flash"
creator-mvp --input ./source.mp4 --brief "Find the product proof and make the edit concise" --out ./mvp-out --style auto --semantic-provider gemini --gemini-mode static --gemini-fps 2 --media-repo ../video2
```

`GEMINI_API_KEY` is required for real transport. It is retained only in process memory and is never written to semantic evidence, request digests, reports, fake-transport calls, logs, or artifacts. `GEMINI_MODEL` is configurable; the code does not treat any model as permanently preferred.

## Native-video path

The live transport uploads the real local MP4 through Gemini's Files API, polls until the remote video is active, then supplies that uploaded video URI as video input to Gemini. It never reduces the source to a contact sheet.

Static mode is the short-form default and supports configurable sampling FPS and clip start/end. Agentic mode is optional. Creator requires both `--gemini-mode agentic` and `GEMINI_AGENTIC_MODEL_SUPPORTED=1`; this avoids claiming an arbitrary configured model supports agentic video.

Current Google references used for the implementation:

- https://ai.google.dev/gemini-api/docs/video-understanding
- https://ai.google.dev/gemini-api/docs/files
- https://ai.google.dev/gemini-api/docs/structured-output

## Structured observations and validation

Gemini is asked for strict JSON carrying the R18 semantic contract version and timestamped transcript segments, people/salient subjects with normalized boxes, important products/screens/interfaces/devices and reveal flags, and hook/setup/proof-demo/explanation/payoff/CTA/low-information events with confidence.

Creator validates exact field sets, semantic contract version, integer millisecond timestamps, every range against ffprobe duration, confidence 0..1, normalized boxes, and event allowlists. Malformed or out-of-range results yield `provider_invalid_output` and contribute no model evidence.

## Provenance separation

Gemini-derived evidence records provider, provider implementation version, configured model, static/agentic mode, semantic request digest, upload identity digest, and static FPS/clipping where applicable. Raw remote URIs and credentials are not persisted. Local ffmpeg evidence remains `deterministic_local`; Gemini observations remain `provider`.

## Failure states and cleanup

Provider results distinguish `provider_unavailable`, `provider_timeout`, `provider_invalid_output`, and `provider_ready`. Uploads, polls, retries, requests, and cleanup are bounded. Remote file deletion is attempted from a finally boundary after every successful upload, including timeout and invalid-output paths.

If Gemini is unavailable, the R18 director continues with deterministic/local evidence and reports unavailable categories rather than inventing replacements.

## CI and proof

CI never uses Google network or paid calls. `FakeGeminiVideoTransport` implements upload/poll/analyze/delete semantics in memory.

The fake-transport integration test proves provider observations change the R18 semantic timeline digest, automatic editorial mode, continuity/B-roll directives, semantic hint digest, and the actual exact Media R13 creative-plan digest compared with local fallback.

## Live smoke

The installed smoke command is intentionally doubly gated:

```bash
export CREATOR_GEMINI_VIDEO_ENABLE=1
export GEMINI_API_KEY="..."
export GEMINI_MODEL="..."
creator-gemini-video-smoke --input ./source.mp4 --live --mode static --fps 1
```

Without `--live`, `CREATOR_GEMINI_VIDEO_ENABLE=1`, and `GEMINI_API_KEY`, it returns `BLOCKED` with `networkAttempted=false`.

## Quality claim

Readiness remains `SEMANTIC_PIPELINE_READY`; human-level editing quality remains `HUMAN_LEVEL_UNPROVEN`. Provider presence alone is not parity evidence.
