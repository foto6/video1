import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const EXPECTED_MEDIA_SHA = "ad4e0ba487a3cabc84dd339d412e19a0db0f9add";

function parseArgs(argv) {
  const out = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) throw new Error("invalid arguments");
    out[key.slice(2)] = value;
  }
  if (!out["media-repo"] || !out.input) throw new Error("--media-repo and --input are required");
  return out;
}

function head(repo) {
  return execFileSync("git", ["-C", repo, "rev-parse", "HEAD"], {
    encoding: "utf8",
    windowsHide: true
  }).trim();
}

function timeline(media) {
  return {
    id: "semantic-r18-plan-compare",
    version: 1,
    profileVersion: media.MEDIA_SHORTFORM_PROFILE_VERSION,
    canvas: { width: 1080, height: 1920, fps: 30, durationMs: 6000 },
    tracks: [
      {
        id: "video",
        kind: "video",
        items: [{
          id: "main",
          startMs: 0,
          endMs: 6000,
          role: "body",
          source: {
            id: "source",
            uri: "source.mp4",
            inMs: 0,
            outMs: 6000,
            sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            size: 1
          }
        }]
      },
      {
        id: "captions",
        kind: "caption",
        items: [{
          id: "hook",
          startMs: 200,
          endMs: 2200,
          text: "same source",
          style: { fontSize: 56, y: 1480, maxWidth: 820 }
        }]
      }
    ]
  };
}

const args = parseArgs(process.argv.slice(2));
const mediaRepo = path.resolve(args["media-repo"]);
if (head(mediaRepo) !== EXPECTED_MEDIA_SHA) throw new Error("Media producer SHA mismatch");
const media = await import(pathToFileURL(path.join(mediaRepo, "src", "index.js")).href);
const input = JSON.parse(readFileSync(path.resolve(args.input), "utf8"));

function normalizeHints(raw) {
  const hints = raw ?? {};
  return {
    sentenceBoundariesMs: Array.isArray(hints.sentenceBoundariesMs) && hints.sentenceBoundariesMs.length
      ? hints.sentenceBoundariesMs
      : [0, 1500, 3000, 4500, 6000],
    beatMarkersMs: Array.isArray(hints.beatMarkersMs) && hints.beatMarkersMs.length
      ? hints.beatMarkersMs
      : [0, 1000, 2000, 3000, 4000, 5000, 6000],
    silenceRanges: Array.isArray(hints.silenceRanges) ? hints.silenceRanges : [],
    saliency: Array.isArray(hints.saliency) ? hints.saliency : [],
    captionTokens: Array.isArray(hints.captionTokens) ? hints.captionTokens : []
  };
}

function compile(spec) {
  const result = media.compileCreativeEditPlan({
    style: spec.mediaStyle,
    timeline: timeline(media),
    loopFriendly: spec.loopFriendly === true,
    cta: false,
    hints: normalizeHints(spec.hints)
  });
  return {
    style: result.style,
    planDigest: result.planDigest,
    alignedCutPointsMs: result.timeline.creativePlan.alignedCutPointsMs,
    removedDeadAir: result.timeline.creativePlan.removedDeadAir,
    hintDigest: result.timeline.creativePlan.hintDigest,
    loopFriendly: result.timeline.creativePlan.loopFriendly
  };
}

const output = {
  producerSha: EXPECTED_MEDIA_SHA,
  fallback: compile(input.fallback),
  enriched: compile(input.enriched)
};
process.stdout.write(JSON.stringify(output));
