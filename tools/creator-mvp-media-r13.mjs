import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const EXPECTED_MEDIA_SHA = "ad4e0ba487a3cabc84dd339d412e19a0db0f9add";
const EXPECTED_COMPAT_VERSION = "media.creator_consumer_compat.r13.v1";
const EXPECTED_PINS = {
  mediaJobConsumerManifest: { path: "conformance/media.job.v1/consumer-manifest.json", gitBlobSha: "96b252acae743f8fe059fd634ee320f92bd9c79c" },
  mediaArtifactManifest: { path: "conformance/media.artifact_manifest.v1/manifest.json", gitBlobSha: "42aed1ca4720cddd4a5e48af076bc73b663322b0" },
  creativePlanManifest: { path: "conformance/media.creative_edit_plan.r12.v1/manifest.json", gitBlobSha: "d031a07f1d392c690942bd5f8288a1713f1af791" },
  creativePlanContract: { path: "conformance/media.creative_edit_plan.r12.v1/contract.json", gitBlobSha: "5298aeb2a9e4e13ed31b1610ce88778b7a911592" },
  shortformEditorManifest: { path: "conformance/media.shortform_editor.r11.v1/manifest.json", gitBlobSha: "07c38a048d23490b8e55924697650e9969bf089f" },
  shortformProfile: { path: "conformance/media.shortform_editor.r11.v1/profile.json", gitBlobSha: "d8f19d9a9d117c5736238159bd5e6d2491370986" },
  compatContract: { path: "conformance/media.creator_consumer_compat.r13.v1/contract.json", gitBlobSha: "ecfeaed347b53ed549124b9d1701ebf70b37eea3" },
  resultEnvelopeSchema: { path: "conformance/media.creator_consumer_compat.r13.v1/schemas/result-envelope.schema.json", gitBlobSha: "119b26b494df77c4ce8d83ffd63791afc112d264" },
  technicalQaSchema: { path: "conformance/media.creator_consumer_compat.r13.v1/schemas/technical-qa.schema.json", gitBlobSha: "1b2f71e443b0038736e8be99f544493965693658" },
  creativeQualitySchema: { path: "conformance/media.creator_consumer_compat.r13.v1/schemas/creative-quality-report.schema.json", gitBlobSha: "c63f95b45f5440aabd8c14dc5fcb8eeae1fc8535" }
};

function parseArgs(argv) {
  const out = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key || !key.startsWith("--") || value === undefined) throw new Error("invalid command arguments");
    out[key.slice(2)] = value;
  }
  for (const required of ["media-repo", "work-dir", "request", "response"]) {
    if (!out[required]) throw new Error("--" + required + " is required");
  }
  return out;
}

function git(repo, args) {
  return execFileSync("git", ["-C", repo, ...args], { encoding: "utf8", windowsHide: true }).trim();
}

function assertExactMedia(mediaRepo) {
  const head = git(mediaRepo, ["rev-parse", "HEAD"]);
  if (head !== EXPECTED_MEDIA_SHA) {
    throw new Error("Media producer SHA mismatch: expected " + EXPECTED_MEDIA_SHA + ", got " + head);
  }
  for (const [name, pin] of Object.entries(EXPECTED_PINS)) {
    const actual = git(mediaRepo, ["hash-object", pin.path]);
    if (actual !== pin.gitBlobSha) {
      throw new Error("Media pinned blob mismatch for " + name + ": expected " + pin.gitBlobSha + ", got " + actual);
    }
  }
  return head;
}

function digestFile(filePath) {
  const bytes = readFileSync(filePath);
  return { sha256: createHash("sha256").update(bytes).digest("hex"), size: statSync(filePath).size };
}

function relativeInside(root, value, label) {
  const resolved = path.resolve(root, value);
  const rel = path.relative(root, resolved);
  if (rel.startsWith("..") || path.isAbsolute(rel)) throw new Error(label + " escaped managed work directory");
  return { resolved, relative: rel.replaceAll("\\", "/") };
}

function sentenceBoundaries(durationMs) {
  const points = new Set([0, durationMs]);
  for (const fraction of [0.25, 0.5, 0.75]) points.add(Math.round(durationMs * fraction));
  return [...points].sort((a, b) => a - b);
}

function beatMarkers(durationMs) {
  const out = [];
  for (let value = 0; value < durationMs; value += 1000) out.push(value);
  if (out.at(-1) !== durationMs) out.push(durationMs);
  return out;
}

const args = parseArgs(process.argv.slice(2));
const mediaRepo = path.resolve(args["media-repo"]);
const workDir = path.resolve(args["work-dir"]);
const requestPath = path.resolve(args.request);
const responsePath = path.resolve(args.response);
mkdirSync(workDir, { recursive: true });

const producerSha = assertExactMedia(mediaRepo);
const manifest = JSON.parse(readFileSync(path.join(mediaRepo, "conformance", "media.creator_consumer_compat.r13.v1", "manifest.json"), "utf8"));
if (manifest.contractVersion !== EXPECTED_COMPAT_VERSION) throw new Error("Media compatibility manifest version mismatch");
if (JSON.stringify(manifest.pins) !== JSON.stringify(EXPECTED_PINS)) throw new Error("Media compatibility manifest pin bundle mismatch");

const media = await import(pathToFileURL(path.join(mediaRepo, "src", "index.js")).href);
for (const name of [
  "MEDIA_CREATOR_CONSUMER_COMPAT_VERSION",
  "MEDIA_JOB_CONTRACT_VERSION",
  "MEDIA_SHORTFORM_PROFILE_VERSION",
  "DeterministicProcessExecutor",
  "FfmpegQaProbe",
  "MediaJobProtocolV1",
  "PersistentRenderJobStore",
  "RenderRuntimeV2",
  "ShortformFfmpegExecutor",
  "artifactManifestDigest",
  "buildCreatorConsumerEnvelope",
  "compileCreativeEditPlan",
  "evaluateCreativeQuality",
  "fingerprint",
  "materializeShortformArtifacts",
  "stableStringify"
]) {
  if (!(name in media)) throw new Error("exact Media R13 export missing: " + name);
}
if (media.MEDIA_CREATOR_CONSUMER_COMPAT_VERSION !== EXPECTED_COMPAT_VERSION) throw new Error("Media runtime compatibility contract version mismatch");

const request = JSON.parse(readFileSync(requestPath, "utf8"));
if (request.contractVersion !== "creator.mvp_pipeline.r17.v1") throw new Error("unsupported Creator MVP request version");
if (request.publishingEnabled !== false || request.growthEnabled !== false || request.analyticsEnabled !== false) {
  throw new Error("MVP request must keep publishing, Growth and analytics disabled");
}
if (!["clean_podcast", "aggressive_shortform", "cinematic_minimal"].includes(request.style?.mediaStyle)) {
  throw new Error("unsupported Media creative style");
}
if (request.semanticDirector?.contractVersion !== "creator.semantic_video_analysis.r18.v1") {
  throw new Error("Creator R18 semantic director contract is required");
}
if (request.semanticDirector?.humanLevelQuality !== "HUMAN_LEVEL_UNPROVEN") {
  throw new Error("Creator R18 must not claim human-level semantic quality");
}
if (!request.semanticDirector?.mediaHints || typeof request.semanticDirector.mediaHints !== "object") {
  throw new Error("Creator R18 semantic Media hints are required");
}

const sourceRef = relativeInside(workDir, request.source?.relativePath, "source");
if (!existsSync(sourceRef.resolved)) throw new Error("managed source missing: " + sourceRef.relative);
const sourceDigest = digestFile(sourceRef.resolved);
if (sourceDigest.sha256 !== request.source.sha256 || sourceDigest.size !== request.source.size) {
  throw new Error("managed source digest/size does not match Creator request");
}
if (!Number.isInteger(request.targetDurationMs) || request.targetDurationMs < 5000 || request.targetDurationMs > 30000) {
  throw new Error("targetDurationMs must be 5000-30000 for Creator MVP");
}
const hook = String(request.script?.hook ?? "").trim();
if (!hook) throw new Error("Creator local script hook is required");
if (request.script?.externalAiUsed !== false || request.script?.generationMode !== "deterministic_local_fallback") {
  throw new Error("MVP baseline script must be explicit deterministic local fallback");
}

process.chdir(workDir);
mkdirSync("outputs", { recursive: true });
mkdirSync("artifacts", { recursive: true });

const source = {
  id: "operator-source",
  uri: sourceRef.relative,
  inMs: 0,
  outMs: request.targetDurationMs,
  sha256: request.source.sha256,
  size: request.source.size
};
const tracks = [
  {
    id: "video",
    kind: "video",
    items: [{ id: "operator-main", startMs: 0, endMs: request.targetDurationMs, role: "body", source }]
  },
  {
    id: "captions",
    kind: "caption",
    items: [{
      id: "brief-hook",
      startMs: 200,
      endMs: Math.min(request.targetDurationMs - 200, 2600),
      text: hook,
      style: { fontSize: 56, y: 1480, maxWidth: 820, box: true, fontColor: "white", boxColor: "black@0.55" }
    }]
  }
];
if (request.source.hasAudio === true) {
  tracks.push({
    id: "audio",
    kind: "audio",
    items: [{
      id: "operator-audio",
      startMs: 0,
      endMs: request.targetDurationMs,
      role: "ambient",
      source,
      gainDb: -1
    }]
  });
}

const baseTimeline = {
  id: "creator-mvp-" + request.runId,
  version: 1,
  profileVersion: media.MEDIA_SHORTFORM_PROFILE_VERSION,
  canvas: { width: 1080, height: 1920, fps: 30, durationMs: request.targetDurationMs },
  tracks
};
const semanticHints = request.semanticDirector.mediaHints;
const creativeHints = {
  sentenceBoundariesMs: Array.isArray(semanticHints.sentenceBoundariesMs) && semanticHints.sentenceBoundariesMs.length
    ? semanticHints.sentenceBoundariesMs
    : sentenceBoundaries(request.targetDurationMs),
  beatMarkersMs: Array.isArray(semanticHints.beatMarkersMs) && semanticHints.beatMarkersMs.length
    ? semanticHints.beatMarkersMs
    : beatMarkers(request.targetDurationMs),
  silenceRanges: Array.isArray(semanticHints.silenceRanges) ? semanticHints.silenceRanges : [],
  saliency: Array.isArray(semanticHints.saliency) ? semanticHints.saliency : [],
  captionTokens: Array.isArray(semanticHints.captionTokens) ? semanticHints.captionTokens : []
};
const creative = media.compileCreativeEditPlan({
  style: request.style.mediaStyle,
  timeline: baseTimeline,
  loopFriendly: request.semanticDirector.directives?.loop?.proposed === true,
  cta: false,
  hints: creativeHints
});

const exportSpec = {
  format: "mp4",
  videoCodec: "libx264",
  audioCodec: "aac",
  videoBitrate: "2M",
  audioBitrate: "160k",
  pixelFormat: "yuv420p",
  preset: "veryfast",
  loudness: { integratedLufs: -16, truePeakDb: -1.5, lra: 11 }
};

const store = new media.PersistentRenderJobStore({ filePath: path.join(workDir, "media-jobs.json") });
const processExecutor = new media.DeterministicProcessExecutor({ defaultTimeoutMs: 180000, maxOutputBytes: 2 * 1024 * 1024 });
const executor = new media.ShortformFfmpegExecutor({ store, sandboxRoot: workDir, executor: processExecutor });
const probe = new media.FfmpegQaProbe({ store, sandboxRoot: workDir });
const runtime = new media.RenderRuntimeV2({
  store,
  executor,
  probe,
  sandboxRoot: workDir,
  liveExecutionEnabled: true,
  processTimeoutMs: 180000
});
const protocol = new media.MediaJobProtocolV1(runtime);
const jobId = "creator-mvp-" + request.runId;
const idempotencyKey = "creator:mvp:r17:" + request.runId;
const submit = {
  contractVersion: media.MEDIA_JOB_CONTRACT_VERSION,
  action: "submit",
  idempotencyKey,
  request: {
    contractVersion: "media.render.v1",
    jobId,
    timeline: creative.timeline,
    exportSpec,
    outputPath: "outputs/final-media.mp4",
    dryRun: false
  }
};
const first = await protocol.handle(submit);
if (first.duplicate !== false) throw new Error("first Media submit was unexpectedly duplicate");
const duplicate = await protocol.handle(structuredClone(submit));
if (duplicate.duplicate !== true) throw new Error("Media idempotency regression: duplicate submit was not detected");
const polled = await protocol.handle({ contractVersion: media.MEDIA_JOB_CONTRACT_VERSION, action: "resume_or_poll", jobId });
if (polled.status !== "succeeded") throw new Error("Media render failed: " + media.stableStringify(polled.failure ?? polled));
const job = store.get(jobId);
if (!job || job.status !== "succeeded") throw new Error("Media job did not persist succeeded state");

const artifactManifest = runtime.exportArtifactManifest(job.id);
const quality = media.evaluateCreativeQuality(job.timeline, job.probe ?? {});
if (quality.passed !== true) throw new Error("creative quality failed: " + media.stableStringify(quality));

const contractDigests = {};
for (const [name, pin] of Object.entries(EXPECTED_PINS)) {
  contractDigests[name] = { path: pin.path, gitBlobSha: git(mediaRepo, ["hash-object", pin.path]) };
}
contractDigests.creatorCompatManifest = {
  path: "conformance/media.creator_consumer_compat.r13.v1/manifest.json",
  gitBlobSha: git(mediaRepo, ["hash-object", "conformance/media.creator_consumer_compat.r13.v1/manifest.json"])
};

const envelope = media.buildCreatorConsumerEnvelope({
  job,
  artifactManifest,
  creativeQualityReport: quality,
  producerSha,
  contractDigests
});
const materialized = await media.materializeShortformArtifacts({
  finalPath: job.resolvedOutputPath,
  timeline: job.timeline,
  exportSpec: job.exportSpec,
  qa: job.qa,
  artifactManifest,
  sourceEvidence: job.probe.sourceEvidence,
  outputDir: path.join(workDir, "artifacts"),
  executor: processExecutor,
  previewDurationMs: Math.min(3000, request.targetDurationMs)
});

const rendered = relativeInside(workDir, job.resolvedOutputPath, "rendered output");
const preview = relativeInside(workDir, materialized.preview.path, "preview output");
const outputDigest = digestFile(rendered.resolved);
if (outputDigest.sha256 !== envelope.finalContent.sha256 || outputDigest.size !== envelope.finalContent.size) {
  throw new Error("Media output bytes do not match Creator compatibility envelope");
}

const response = {
  contractVersion: "creator.mvp_media_result.r17.v1",
  producerSha,
  compatibilityContractVersion: EXPECTED_COMPAT_VERSION,
  requestDigest: request.requestDigest,
  logicalJobId: envelope.logicalJobId,
  renderedRelativePath: rendered.relative,
  previewRelativePath: preview.relative,
  envelope,
  artifactManifest,
  creativePlan: {
    contractVersion: creative.contractVersion,
    planDigest: creative.planDigest,
    style: creative.style,
    semanticAnalysisDigest: request.semanticDirector.analysisDigest,
    semanticDirectivesDigest: request.semanticDirector.directives?.directivesDigest ?? null,
    semanticHintsDigest: media.fingerprint(creativeHints)
  },
  mediaArtifactManifestDigest: media.artifactManifestDigest(artifactManifest),
  duplicateSubmitObserved: true,
  livePublishing: false
};
writeFileSync(responsePath, media.stableStringify(response) + "\n");
