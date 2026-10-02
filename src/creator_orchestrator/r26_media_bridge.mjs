import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync
} from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { pathToFileURL } from "node:url";

const MEDIA_SHA = "a17f782da8144d1e890ac83195396a3192df93c2";
const REQUEST_VERSION = "creator.media_r15_real_review_request.r26.v1";
const RESULT_VERSION = "creator.media_r15_real_review_result.r26.v1";
const SUPPORTED = new Set([
  "trim",
  "cut",
  "crop_scale_reframe",
  "speed_change",
  "fade_transition",
  "text_overlay",
  "subtitles_captions",
  "audio_duck_mix",
  "intro_outro_cta"
]);

function argsOf(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith("--")) out[key] = true;
    else {
      out[key] = value;
      i += 1;
    }
  }
  return out;
}
function die(message) {
  console.error(message);
  process.exit(2);
}
function gitHead(repo) {
  return execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repo,
    encoding: "utf8",
    windowsHide: true
  }).trim();
}
function digest(filePath) {
  const bytes = readFileSync(filePath);
  return {
    sha256: createHash("sha256").update(bytes).digest("hex"),
    size: bytes.length
  };
}
function jsonDigest(value) {
  return createHash("sha256")
    .update(JSON.stringify(value, Object.keys(value).sort()))
    .digest("hex");
}
function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

const args = argsOf(process.argv.slice(2));
for (const key of ["media-checkout", "request", "out"]) {
  if (!args[key]) die("missing --" + key);
}
const checkout = path.resolve(args["media-checkout"]);
if (gitHead(checkout) !== MEDIA_SHA) {
  die("Media checkout HEAD mismatch; expected " + MEDIA_SHA);
}
const requestPath = path.resolve(args.request);
const request = JSON.parse(readFileSync(requestPath, "utf8"));
if (request.contractVersion !== REQUEST_VERSION) die("R26 Media request contract mismatch");
if (request.mediaProducerSha !== MEDIA_SHA) die("R26 Media producer SHA mismatch");
if (!request.originalSource || !request.editInput || !request.plan) {
  die("R26 Media request lineage fields missing");
}
if (!Array.isArray(request.reviewDirectives)) die("reviewDirectives must be array");
if (!/^[0-9a-f]{64}$/.test(request.requestDigest || "")) die("requestDigest invalid");

const root = path.resolve(args.out);
const requestedInputPath = path.resolve(request.editInput.path);
mkdirSync(root, { recursive: true });
process.chdir(root);
if (process.cwd() !== root) die("failed to bind R26 Media bridge cwd to sandbox root");

const media = await import(pathToFileURL(path.join(checkout, "src", "index.js")).href);
const finalPath = path.join(root, "final.mp4");
const sidecarPath = path.join(root, media.MEDIA_RENDER_EXPORT_FILENAME);
const receiptPath = path.join(root, "creator-r26-media-receipt.json");

if (existsSync(finalPath) || existsSync(sidecarPath) || existsSync(receiptPath)) {
  if (!(existsSync(finalPath) && existsSync(sidecarPath) && existsSync(receiptPath))) {
    die("partial R26 Media recovery state");
  }
  const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
  if (
    receipt.contractVersion !== "creator.media_r15_real_review_receipt.r26.v1"
    || receipt.requestDigest !== request.requestDigest
  ) {
    die("R26 Media recovery request mismatch");
  }
  const record = media.requireRenderExportSidecar(finalPath);
  media.validateRenderExportAgainstFinal(record, finalPath);
  if (record.producer.sha !== MEDIA_SHA) die("recovered Media producer SHA mismatch");
  const exportDigest = media.renderExportDigest(record);
  if (receipt.renderExportDigest !== exportDigest) die("recovered render export digest mismatch");
  console.log(JSON.stringify({
    contractVersion: RESULT_VERSION,
    state: "recovered",
    requestDigest: request.requestDigest,
    finalPath,
    sidecarPath,
    renderExport: record,
    renderExportDigest: exportDigest,
    actualMediaProducerInvoked: true,
    logicalEffects: 0,
    bridgeCwd: process.cwd(),
    sandboxRoot: root,
    inputSha256: receipt.inputSha256,
    directiveDigest: receipt.directiveDigest
  }));
  process.exit(0);
}

mkdirSync(path.join(root, "inputs"), { recursive: true });
mkdirSync(path.join(root, "outputs"), { recursive: true });
const copiedInput = path.join(root, "inputs", "edit-input.mp4");
copyFileSync(requestedInputPath, copiedInput);
const inputDigest = digest(copiedInput);
if (
  inputDigest.sha256 !== request.editInput.sha256
  || inputDigest.size !== request.editInput.sizeBytes
) {
  die("R26 edit input SHA/size mismatch after bounded copy");
}
const relativeInput = path.relative(root, path.resolve(copiedInput));
if (relativeInput.startsWith("..") || path.isAbsolute(relativeInput)) {
  die("R26 copied input escaped Media sandbox");
}
const sourceUri = relativeInput.split(path.sep).join("/");
const durationMs = Number(request.editInput.durationMs);
if (!Number.isInteger(durationMs) || durationMs < 15000 || durationMs > 60000) {
  die("R26 edit input duration must be 15-60 seconds");
}
const hasAudio = request.editInput.hasAudio === true;

const directives = request.reviewDirectives.map((row, index) => {
  if (!row || typeof row !== "object") die("directive must be object");
  if (!SUPPORTED.has(row.operation)) die("unsupported directive operation");
  if (!Number.isInteger(row.start_ms) || !Number.isInteger(row.end_ms)) {
    die("directive timestamps must be integers");
  }
  if (row.start_ms < 0 || row.end_ms <= row.start_ms || row.end_ms > durationMs) {
    die("directive timestamp outside current render");
  }
  if (row.upstream_proposed_edit_executable !== false) {
    die("freeform upstream edit is not executable");
  }
  if (row.operation === "audio_duck_mix" && !hasAudio) {
    die("audio_duck_mix unsupported for an input with no audio stream");
  }
  return { ...clone(row), _index: index };
});

const boundaries = new Set([0, durationMs]);
for (const row of directives) {
  boundaries.add(row.start_ms);
  boundaries.add(row.end_ms);
}
const points = [...boundaries].sort((a, b) => a - b);
const segments = [];
let cursor = 0;
for (let i = 0; i < points.length - 1; i += 1) {
  const inputStart = points[i];
  const inputEnd = points[i + 1];
  if (inputEnd <= inputStart) continue;
  const active = directives.filter(
    (row) => row.start_ms <= inputStart && inputEnd <= row.end_ms
  );
  const removed = active.some((row) => row.operation === "trim" || row.operation === "cut");
  let speed = active.some((row) => row.operation === "speed_change") ? 1.08 : 1.0;
  let outputDuration = removed ? 0 : Math.max(80, Math.round((inputEnd - inputStart) / speed));
  const mapping = {
    inputStart,
    inputEnd,
    outputStart: cursor,
    outputEnd: cursor + outputDuration,
    removed,
    speed,
    active
  };
  segments.push(mapping);
  cursor += outputDuration;
}
if (cursor < 15000 || cursor > 60000) {
  die("R26 directive set would produce output outside 15-60 second profile");
}

function mapTime(ms) {
  for (const seg of segments) {
    if (ms < seg.inputStart) break;
    if (ms <= seg.inputEnd) {
      if (seg.removed) return seg.outputStart;
      const span = seg.inputEnd - seg.inputStart;
      const ratio = span === 0 ? 0 : (ms - seg.inputStart) / span;
      return Math.round(seg.outputStart + ratio * (seg.outputEnd - seg.outputStart));
    }
  }
  return cursor;
}

const videoItems = [];
const audioItems = [];
let videoIndex = 0;
let audioIndex = 0;
for (const seg of segments) {
  if (seg.removed) continue;
  const duration = seg.outputEnd - seg.outputStart;
  if (duration < 80) continue;
  const operations = new Set(seg.active.map((row) => row.operation));
  const video = {
    id: "video-" + String(++videoIndex).padStart(3, "0"),
    startMs: seg.outputStart,
    endMs: seg.outputEnd,
    role: "body",
    source: {
      id: "r26-edit-input",
      uri: sourceUri,
      inMs: seg.inputStart,
      outMs: seg.inputEnd,
      sha256: inputDigest.sha256,
      size: inputDigest.size
    },
    reframe: { x: 0, y: 0 },
    speed: seg.speed,
    motion: operations.has("crop_scale_reframe")
      ? { type: "punch_in", zoom: 1.06, amplitudePx: 0 }
      : { type: "slow_push", zoom: 1.02, amplitudePx: 0 }
  };
  if (operations.has("fade_transition") && duration > 400) {
    video.fadeInMs = Math.min(120, Math.floor(duration / 4));
    video.fadeOutMs = Math.min(120, Math.floor(duration / 4));
  }
  videoItems.push(video);

  if (hasAudio) {
    const audio = {
      id: "audio-" + String(++audioIndex).padStart(3, "0"),
      startMs: seg.outputStart,
      endMs: seg.outputEnd,
      role: "voiceover",
      source: {
        id: "r26-edit-input-audio",
        uri: sourceUri,
        inMs: seg.inputStart,
        outMs: seg.inputEnd,
        sha256: inputDigest.sha256,
        size: inputDigest.size
      },
      speed: seg.speed,
      gainDb: operations.has("audio_duck_mix") ? -4 : 0
    };
    if (operations.has("fade_transition") && duration > 400) {
      audio.fadeInMs = Math.min(120, Math.floor(duration / 4));
      audio.fadeOutMs = Math.min(120, Math.floor(duration / 4));
    }
    audioItems.push(audio);
  }
}

const captionItems = [{
  id: "r26-round-label",
  startMs: 250,
  endMs: Math.min(cursor - 200, 1550),
  text: "R26 REVIEW R" + (Number(request.plan.roundIndex) + 1),
  style: { fontSize: 44, y: 1450, maxWidth: 820 }
}];
const overlayItems = [];
for (const row of directives) {
  const startMs = mapTime(row.start_ms);
  const endMs = mapTime(row.end_ms);
  if (endMs - startMs < 180) continue;
  if (row.operation === "subtitles_captions") {
    captionItems.push({
      id: "r26-caption-" + row._index,
      startMs,
      endMs,
      text: "EMPHASIS",
      style: { fontSize: 58, y: 1430, maxWidth: 860, kinetic: "none" }
    });
  }
  if (row.operation === "text_overlay") {
    overlayItems.push({
      id: "r26-overlay-" + row._index,
      startMs,
      endMs,
      role: "label",
      text: "KEY POINT",
      style: { fontSize: 48, y: 260, maxWidth: 860, box: true }
    });
  }
  if (row.operation === "intro_outro_cta") {
    overlayItems.push({
      id: "r26-cta-" + row._index,
      startMs,
      endMs,
      role: "cta",
      text: "CTA",
      style: { fontSize: 54, y: 300, maxWidth: 860, box: true }
    });
  }
}

const tracks = [
  { id: "video", kind: "video", items: videoItems },
  { id: "captions", kind: "caption", items: captionItems }
];
if (audioItems.length) tracks.push({ id: "audio", kind: "audio", items: audioItems });
if (overlayItems.length) tracks.push({ id: "overlays", kind: "overlay", items: overlayItems });

const timeline = {
  id: "r26-" + request.plan.candidateId,
  version: 1,
  profileVersion: media.MEDIA_SHORTFORM_PROFILE_VERSION,
  canvas: { width: 1080, height: 1920, fps: 30, durationMs: cursor },
  tracks
};
media.validateTimeline(timeline);

const exportSpec = {
  format: "mp4",
  videoCodec: "libx264",
  audioCodec: "aac",
  videoBitrate: "1M",
  audioBitrate: "128k",
  pixelFormat: "yuv420p",
  preset: "ultrafast",
  loudness: { integratedLufs: -16, truePeakDb: -1.5, lra: 11 }
};

const store = new media.PersistentRenderJobStore({
  filePath: path.join(root, "jobs.json")
});
const executor = new media.DeterministicProcessExecutor({
  defaultTimeoutMs: 180000,
  maxOutputBytes: 2 * 1024 * 1024
});
const mediaExecutor = new media.ShortformFfmpegExecutor({
  store,
  sandboxRoot: root,
  executor
});
const probe = new media.FfmpegQaProbe({ store, sandboxRoot: root });
let nowMs = 1910000000000;
const runtime = new media.RenderRuntimeV2({
  store,
  executor: mediaExecutor,
  probe,
  sandboxRoot: root,
  liveExecutionEnabled: true,
  processTimeoutMs: 180000,
  clock: () => {
    nowMs += 10;
    return nowMs;
  }
});
const protocol = new media.MediaJobProtocolV1(runtime);
const jobId = "r26-" + createHash("sha256")
  .update(request.requestDigest)
  .digest("hex")
  .slice(0, 24);
const idempotencyKey = "creator:r26:" + request.requestDigest;
const submit = {
  contractVersion: media.MEDIA_JOB_CONTRACT_VERSION,
  action: "submit",
  idempotencyKey,
  request: {
    contractVersion: "media.render.v1",
    jobId,
    timeline,
    exportSpec,
    outputPath: "outputs/final.mp4",
    dryRun: false
  }
};
const first = await protocol.handle(submit);
const duplicate = await protocol.handle(structuredClone(submit));
if (first.duplicate !== false || duplicate.duplicate !== true) {
  die("R26 Media duplicate submit idempotency regression");
}
let response = await protocol.handle({
  contractVersion: media.MEDIA_JOB_CONTRACT_VERSION,
  action: "resume_or_poll",
  jobId
});
for (let i = 0; i < 12 && response.status !== "succeeded"; i += 1) {
  if (response.status === "failed") break;
  response = await protocol.handle({
    contractVersion: media.MEDIA_JOB_CONTRACT_VERSION,
    action: "resume_or_poll",
    jobId
  });
}
if (response.status !== "succeeded") {
  die("R26 Media render failed: " + JSON.stringify(response.failure || response));
}
const job = store.get(jobId);
const manifest = runtime.exportArtifactManifest(job.id);
const actualFinal = job.resolvedOutputPath;
const record = media.buildSucceededRenderExport({
  job,
  finalPath: actualFinal,
  artifactManifest: manifest,
  producerSha: MEDIA_SHA
});
media.writeRenderExportSidecar(
  record,
  path.join(path.dirname(actualFinal), media.MEDIA_RENDER_EXPORT_FILENAME)
);
if (actualFinal !== finalPath) {
  copyFileSync(actualFinal, finalPath);
  media.writeRenderExportSidecar(record, sidecarPath);
}
media.validateRenderExportAgainstFinal(record, finalPath);
const exportDigest = media.renderExportDigest(record);
const directiveDigest = createHash("sha256")
  .update(JSON.stringify(request.reviewDirectives))
  .digest("hex");
writeFileSync(
  receiptPath,
  JSON.stringify({
    contractVersion: "creator.media_r15_real_review_receipt.r26.v1",
    requestDigest: request.requestDigest,
    inputSha256: inputDigest.sha256,
    inputSizeBytes: inputDigest.size,
    renderExportDigest: exportDigest,
    directiveDigest,
    outputSha256: digest(finalPath).sha256,
    outputSizeBytes: digest(finalPath).size
  }, null, 2) + "\n",
  "utf8"
);
console.log(JSON.stringify({
  contractVersion: RESULT_VERSION,
  state: "rendered",
  requestDigest: request.requestDigest,
  finalPath,
  sidecarPath,
  renderExport: record,
  renderExportDigest: exportDigest,
  actualMediaProducerInvoked: true,
  logicalEffects: 1,
  bridgeCwd: process.cwd(),
  sandboxRoot: root,
  inputSha256: inputDigest.sha256,
  directiveDigest
}));
