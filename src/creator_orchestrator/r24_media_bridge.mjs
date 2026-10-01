import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const MEDIA_SHA = "a17f782da8144d1e890ac83195396a3192df93c2";

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
    cwd: repo, encoding: "utf8", windowsHide: true
  }).trim();
}
function digest(filePath) {
  const bytes = readFileSync(filePath);
  return {
    sha256: createHash("sha256").update(bytes).digest("hex"),
    size: bytes.length
  };
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
if (request.contractVersion !== "creator.media_r15_render_request.r24.v1") {
  die("Media request contract mismatch");
}
if (request.mediaProducerSha !== MEDIA_SHA) {
  die("Media request producer SHA mismatch");
}
const root = path.resolve(args.out);
const requestedSourcePath = path.resolve(request.source.path);
mkdirSync(root, { recursive: true });

// All caller-relative inputs are resolved before this point. This script is a
// dedicated child process, so its cwd can be scoped to the candidate sandbox
// without mutating the Python caller or any sibling process.
process.chdir(root);
if (process.cwd() !== root) {
  die("failed to bind Media bridge cwd to candidate sandbox root");
}

const media = await import(pathToFileURL(path.join(checkout, "src", "index.js")).href);
const finalPath = path.join(root, "final.mp4");
const sidecarPath = path.join(root, media.MEDIA_RENDER_EXPORT_FILENAME);

if (existsSync(finalPath) && existsSync(sidecarPath)) {
  const record = media.requireRenderExportSidecar(finalPath);
  if (record.producer.sha !== MEDIA_SHA) {
    die("recovered render export producer SHA mismatch");
  }
  console.log(JSON.stringify({
    contractVersion: "creator.media_r15_render_result.r24.v1",
    state: "recovered",
    requestDigest: request.requestDigest,
    finalPath,
    sidecarPath,
    renderExport: record,
    renderExportDigest: media.renderExportDigest(record),
    actualMediaProducerInvoked: true,
    logicalEffects: 0,
    bridgeCwd: process.cwd(),
    sandboxRoot: root,
    sourceUri: "inputs/source.mp4"
  }));
  process.exit(0);
}

mkdirSync(path.join(root, "inputs"), { recursive: true });
mkdirSync(path.join(root, "outputs"), { recursive: true });
const copiedSource = path.join(root, "inputs", "source.mp4");
copyFileSync(requestedSourcePath, copiedSource);
const sourceDigest = digest(copiedSource);

// Media R15 resolves timeline source.uri against sandboxRoot for validation,
// while its process executor passes that URI unchanged to ffmpeg. Keep the
// source sandbox-relative, then bind this dedicated bridge process cwd to the
// same candidate root before protocol execution so validation and ffmpeg open
// the exact same copied bytes on every platform.
const canonicalCopiedSource = path.resolve(copiedSource);
const sandboxRelativeSource = path.relative(root, canonicalCopiedSource);
if (
  sandboxRelativeSource.startsWith("..")
  || path.isAbsolute(sandboxRelativeSource)
) {
  die("copied source escaped Media sandbox root");
}
const sandboxSourceUri = sandboxRelativeSource.split(path.sep).join("/");
if (
  sourceDigest.sha256 !== request.source.sha256
  || sourceDigest.size !== request.source.sizeBytes
) {
  die("source SHA/size mismatch after bounded copy");
}

const durationMs = request.source.durationMs;
const plan = request.plan;
const ordinal = Number(plan.ordinal);
const roundIndex = Number(plan.roundIndex);
const baseTimeline = {
  id: "r24-" + plan.candidateId,
  version: 1,
  profileVersion: media.MEDIA_SHORTFORM_PROFILE_VERSION,
  canvas: { width: 1080, height: 1920, fps: 30, durationMs },
  tracks: [
    {
      id: "video",
      kind: "video",
      items: [{
        id: "primary",
        startMs: 0,
        endMs: durationMs,
        role: "body",
        source: {
          id: request.source.sourceId,
          uri: sandboxSourceUri,
          inMs: 0,
          outMs: durationMs,
          sha256: sourceDigest.sha256,
          size: sourceDigest.size
        },
        reframe: { x: 0, y: 0 },
        fadeInMs: 80 + ordinal * 20,
        fadeOutMs: 100 + roundIndex * 20
      }]
    },
    {
      id: "captions",
      kind: "caption",
      items: [{
        id: "candidate-label",
        startMs: 300,
        endMs: Math.min(durationMs - 200, 1900 + roundIndex * 100),
        text: "R24 C" + (ordinal + 1) + " R" + (roundIndex + 1),
        style: {
          fontSize: 58 + ordinal * 2,
          y: 1430 - roundIndex * 10,
          maxWidth: 860
        }
      }]
    }
  ]
};

const styleMap = {
  clean_podcast: "clean_podcast",
  aggressive_shortform: "aggressive_shortform",
  cinematic_minimal: "cinematic_minimal",
  hybrid: "aggressive_shortform"
};
const style = styleMap[plan.editorialMode] || "clean_podcast";
const hints = request.mediaHints || {};
const creative = media.compileCreativeEditPlan({
  style,
  timeline: baseTimeline,
  loopFriendly: false,
  cta: false,
  hints: {
    silenceRanges: Array.isArray(hints.silenceRanges) ? hints.silenceRanges : [],
    sentenceBoundariesMs: Array.isArray(hints.sentenceBoundariesMs) ? hints.sentenceBoundariesMs : [],
    beatMarkersMs: Array.isArray(hints.beatMarkersMs) ? hints.beatMarkersMs : [],
    saliency: Array.isArray(hints.saliency) ? hints.saliency : [],
    captionTokens: []
  }
});

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
let nowMs = 1900000000000;
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
const jobId = "r24-" + createHash("sha256")
  .update(request.requestDigest)
  .digest("hex")
  .slice(0, 24);
const idempotencyKey = "creator:r24:" + request.requestDigest;
const submit = {
  contractVersion: media.MEDIA_JOB_CONTRACT_VERSION,
  action: "submit",
  idempotencyKey,
  request: {
    contractVersion: "media.render.v1",
    jobId,
    timeline: creative.timeline,
    exportSpec,
    outputPath: "outputs/final.mp4",
    dryRun: false
  }
};
// Media R15's path policy interprets this relative URI against sandboxRoot.
// ffmpeg receives the same relative URI and inherits this bridge process cwd,
// which is now exactly sandboxRoot.
const first = await protocol.handle(submit);
const duplicate = await protocol.handle(structuredClone(submit));
if (first.duplicate !== false || duplicate.duplicate !== true) {
  die("Media duplicate submit idempotency regression");
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
  die("Media render failed: " + JSON.stringify(response.failure || response));
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
console.log(JSON.stringify({
  contractVersion: "creator.media_r15_render_result.r24.v1",
  state: "rendered",
  requestDigest: request.requestDigest,
  finalPath,
  sidecarPath,
  renderExport: record,
  renderExportDigest: media.renderExportDigest(record),
  creativePlanDigest: creative.planDigest,
  actualMediaProducerInvoked: true,
  logicalEffects: 1,
  bridgeCwd: process.cwd(),
  sandboxRoot: root,
  sourceUri: sandboxSourceUri
}));
