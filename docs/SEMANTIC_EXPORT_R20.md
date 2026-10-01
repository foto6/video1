# Creator R20 canonical human-benchmark semantic export

R20 is an additive export layer over the green R19 content-aware MVP. It does not change semantic analysis, auto-style selection, edit directives, Media hints, rendering, or QA behavior.

## Benchmark authority

Consumer authority is pinned to:

- repository: `foto6/boss`
- branch: `agent/human-editing-gate-supervisor-20261001-v2`
- benchmark head: `e0763bebf2aad9402f8de8c60edb1b9eb8c4be8e`
- protocol: `boss.human_editing_gate.v1`
- protocol blob: `8eb2e400f9997e1fefa5ebb9500d8e13d54f51ed`

That protocol requires the canonical Creator producer file `creator.semantic_export.v1.json`.

## Canonical file

Every successful semantic phase emits:

`creator.semantic_export.v1.json`

with exactly these top-level keys:

`contract_version, repository, commit_sha, source_id, source_sha256, brief_digest, analysis_contract, director_report_contract, semantic_timeline, unavailable_evidence, auto_style, effective_style, style_confidence, edit_directives, analysis_digest, directives_digest, generation_mode`.

No additional top-level fields are accepted by the validator/schema.

The JSON Schema is:

`conformance/creator.semantic_export.v1/schema.json`

The runtime validator is:

`creator_orchestrator.semantic_export.validate_semantic_export`

## Exact binding

The export is constructed directly from the R19 runtime semantic analysis and director objects. It does not scrape tests, fixture files, or reports.

Bindings are checked before export:

- `commit_sha` is the exact running Creator Git HEAD;
- `source_sha256` matches the source bytes and R18 semantic source;
- source duration matches semantic analysis;
- `brief_digest` matches the normalized brief used by semantic analysis;
- director report and style selection bind to the exact analysis digest;
- `directives_digest` is recomputed from exported edit directives;
- validator callers may require exact expected analysis/directive digests.

An optional `--source-id` allows a frozen benchmark corpus ID to pass through unchanged. Without it, Creator generates a deterministic `creator-source-<sha-prefix>` identifier.

## Timestamp validation

The validator recursively checks every `startMs/endMs` pair in `semantic_timeline`. Timestamps must be integer milliseconds, nonnegative, nonempty, and end no later than the ffprobe-bound source duration.

Malformed, partial, or out-of-range timestamp evidence fails closed.

## Unavailable evidence and generation mode

`unavailable_evidence` is explicit, sorted, and unique.

`generation_mode` distinguishes:

- `gemini_native_video`
- `deterministic_local`
- `deterministic_local_fallback`

A failed/unconfigured Gemini attempt therefore cannot be mistaken for model understanding.

The export has no human-ground-truth field and does not represent model, fixture, or deterministic evidence as human labels.

## One-command integration

The existing R19 UX remains valid:

```bash
creator-mvp --input ./source.mp4 --brief "Create a source-bound short" --out ./mvp-out --media-repo ../video2
```

For a benchmark corpus entry:

```bash
creator-mvp --input ./source.mp4 --brief "Create a source-bound short" --source-id corpus-001 --out ./mvp-out --media-repo ../video2
```

R19 outputs and `content-aware-run.json` are preserved. The R20 canonical export is additional and is also referenced from the run summary/content-aware envelope.

## E2E evidence

R20 tests generate real MP4s for:

- talking-head-like source;
- fast-cut/action source;
- landscape/screen-like source.

Each goes through the normal R19 semantic director, exact Media R13 render, and QA path. Each must emit a canonical semantic export whose source SHA, brief digest, exact Creator commit, semantic digest, directive digest, generation mode, and source ID validate.

Separate regressions fail closed on:

- changed Creator commit binding;
- changed source SHA binding;
- out-of-bounds semantic timestamps;
- missing required keys.

## Claim boundary

R20 does not create a 30-source benchmark corpus, human references, ratings, rater agreement, or parity evidence. Those remain benchmark-owned work.

`HUMAN_LEVEL_UNPROVEN` remains the applicable quality claim boundary until the independent human benchmark supplies the required evidence.
