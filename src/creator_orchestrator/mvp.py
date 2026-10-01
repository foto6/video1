from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import media_r13_compat as m13
from . import semantic_director as director
from . import gemini_video_provider as gemini_video

MVP_VERSION = "creator.mvp_pipeline.r17.v1"
SCRIPT_VERSION = "creator.mvp_local_script.r17.v1"
SUMMARY_VERSION = "creator.mvp_run_summary.r17.v1"
QA_VERSION = "creator.mvp_qa.r17.v1"
CONTENT_AWARE_RUN_VERSION = "creator.content_aware_run.r19.v1"
STYLE_DECISION_VERSION = "creator.style_decision.r19.v1"
EDITORIAL_DIRECTIVES_VERSION = "creator.editorial_directives.r19.v1"
CREATOR_R16_BASE_SHA = "4a176c56b68b8949651eb45e5bd26d2cbdbd02ee"

EXIT_SUCCESS = 0
EXIT_BAD_INPUT = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_MEDIA_MISMATCH = 4
EXIT_RENDER_FAILED = 5
EXIT_TECHNICAL_QA_FAILED = 6
EXIT_CREATIVE_QA_FAILED = 7
EXIT_INSUFFICIENT_EVIDENCE = 8
EXIT_INTERNAL = 9

STYLE_MAP = {
    "clean": "clean_podcast",
    "aggressive": "aggressive_shortform",
    "cinematic": "cinematic_minimal",
    "hybrid": "clean_podcast",
}


class MvpError(RuntimeError):
    exit_code = EXIT_INTERNAL


class BadInput(MvpError):
    exit_code = EXIT_BAD_INPUT


class MissingDependency(MvpError):
    exit_code = EXIT_MISSING_DEPENDENCY


class MediaMismatch(MvpError):
    exit_code = EXIT_MEDIA_MISMATCH


class RenderFailed(MvpError):
    exit_code = EXIT_RENDER_FAILED


class TechnicalQaFailed(MvpError):
    exit_code = EXIT_TECHNICAL_QA_FAILED


class CreativeQaFailed(MvpError):
    exit_code = EXIT_CREATIVE_QA_FAILED


class InsufficientEvidence(MvpError):
    exit_code = EXIT_INSUFFICIENT_EVIDENCE


@dataclass(frozen=True)
class InputProbe:
    duration_ms: int
    width: int
    height: int
    fps: float
    has_audio: bool
    sha256: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "durationMs": self.duration_ms,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "hasAudio": self.has_audio,
            "sha256": self.sha256,
            "size": self.size,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=None if cwd is None else str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _require_tool(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise MissingDependency(
            f"{name} is required but was not found on PATH. "
            f"Install {name} and retry."
        )
    return value


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _semantic_provider_identity(
    analysis: Mapping[str, Any],
    *,
    requested: str,
    gemini_model: str | None,
    gemini_mode: str | None,
    gemini_attempted: bool,
) -> dict[str, Any]:
    adapters = analysis.get("adapters", [])
    gemini_result = next(
        (
            item for item in adapters
            if item.get("adapter") == "google_gemini_native_video"
        ),
        None,
    )
    provider_evidence = [
        item
        for values in analysis["evidence"].values()
        for item in values
        if item.get("source", {}).get("mode") == "provider"
    ]
    local_evidence = [
        item
        for values in analysis["evidence"].values()
        for item in values
        if item.get("source", {}).get("mode")
        in {"deterministic_local", "derived_from_local"}
    ]
    gemini_available = bool(
        gemini_result
        and gemini_result.get("status") == "available"
        and provider_evidence
    )
    if gemini_available:
        provenance = next(
            (
                item.get("value", {}).get("providerProvenance")
                for item in provider_evidence
                if isinstance(
                    item.get("value", {}).get("providerProvenance"),
                    Mapping,
                )
            ),
            {},
        )
        effective = "google_gemini"
        fallback = False
        fallback_reason = None
        model = provenance.get("model") or gemini_model
        mode = provenance.get("mode") or gemini_mode
        status = "available"
    else:
        effective = "deterministic_local"
        fallback = requested in {"auto", "gemini"}
        if gemini_result:
            fallback_reason = gemini_result.get("reason") or "provider_unavailable"
            status = gemini_result.get("status") or "unavailable"
        elif requested == "auto" and not gemini_attempted:
            fallback_reason = "gemini_not_configured"
            status = "not_configured"
        else:
            fallback_reason = None
            status = "local_explicit"
        model = gemini_model if gemini_attempted else None
        mode = gemini_mode if gemini_attempted else None
    value = {
        "requested": requested,
        "effective": effective,
        "status": status,
        "model": model,
        "mode": mode,
        "geminiAttempted": gemini_attempted,
        "fallback": fallback,
        "fallbackReason": fallback_reason,
        "providerEvidenceCount": len(provider_evidence),
        "deterministicLocalEvidenceCount": len(local_evidence),
        "humanLevelQuality": director.HUMAN_LEVEL_STATE,
    }
    value["identityDigest"] = reels.sha256_json(value)
    return value


def _style_artifact(
    decision: Mapping[str, Any],
    *,
    source_sha256: str,
) -> dict[str, Any]:
    value = {
        "contractVersion": STYLE_DECISION_VERSION,
        "sourceSha256": source_sha256,
        "decision": json.loads(reels.canonical_json(decision)),
        "selectedStyle": decision["effectiveMode"],
        "confidence": decision["autoDirector"]["confidence"],
        "evidence": decision["autoDirector"]["sourceSemanticFeatures"],
        "rejectedAlternatives": decision["autoDirector"]["rejectedAlternatives"],
        "overrideProvenance": decision["override"],
        "humanLevelQuality": director.HUMAN_LEVEL_STATE,
    }
    value["styleDecisionDigest"] = reels.sha256_json(value)
    return value


def _directives_artifact(
    directives: Mapping[str, Any],
    *,
    source_sha256: str,
    semantic_digest: str,
    style_decision_digest: str,
) -> dict[str, Any]:
    value = {
        "contractVersion": EDITORIAL_DIRECTIVES_VERSION,
        "sourceSha256": source_sha256,
        "semanticTimelineDigest": semantic_digest,
        "styleDecisionDigest": style_decision_digest,
        "directives": json.loads(reels.canonical_json(directives)),
        "humanLevelQuality": director.HUMAN_LEVEL_STATE,
    }
    value["editorialDirectivesDigest"] = reels.sha256_json(value)
    return value


def normalize_brief(raw: str) -> tuple[str, dict[str, Any]]:
    value = raw.strip()
    if not value:
        raise BadInput("--brief must be non-empty text or a readable text file")
    path = Path(value).expanduser()
    source = "inline"
    if path.is_file():
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BadInput(f"could not read brief file: {path}: {exc}") from exc
        source = "file"
    normalized = " ".join(value.split())
    if not normalized:
        raise BadInput("brief contains no usable text")
    if len(normalized) > 2000:
        raise BadInput("brief exceeds 2000 normalized characters")
    return normalized, {
        "source": source,
        "mode": "deterministic_local_fallback",
        "externalAiUsed": False,
        "fallbackReason": "external AI generation is not required for the MVP baseline",
    }


def build_local_script(brief: str, *, duration_ms: int) -> dict[str, Any]:
    hook = brief.split(".", 1)[0].strip() or brief
    hook = hook[:72].strip()
    if not hook:
        raise InsufficientEvidence("brief does not contain enough text to derive a local hook")
    thirds = [
        0,
        max(1, duration_ms // 3),
        max(2, (duration_ms * 2) // 3),
        duration_ms,
    ]
    value = {
        "contractVersion": SCRIPT_VERSION,
        "generationMode": "deterministic_local_fallback",
        "externalAiUsed": False,
        "hook": hook,
        "normalizedBrief": brief,
        "beats": [
            {"role": "hook", "startMs": thirds[0], "endMs": thirds[1]},
            {"role": "body", "startMs": thirds[1], "endMs": thirds[2]},
            {"role": "finish", "startMs": thirds[2], "endMs": thirds[3]},
        ],
        "cta": None,
    }
    value["scriptDigest"] = reels.sha256_json(value)
    return value


def probe_input(path: Path) -> InputProbe:
    _require_tool("ffprobe")
    if not path.is_file():
        raise BadInput(f"input video does not exist: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BadInput(f"cannot stat input video: {path}: {exc}") from exc
    if size <= 0:
        raise BadInput("input video is empty")
    result = _run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate:format=duration",
            "-of", "json",
            str(path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        raise BadInput(
            "ffprobe could not read the input video: "
            + (result.stderr.strip() or "unknown ffprobe error")
        )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BadInput("ffprobe returned invalid JSON") from exc
    streams = parsed.get("streams")
    if not isinstance(streams, list):
        raise BadInput("ffprobe result has no streams array")
    video = next(
        (item for item in streams if item.get("codec_type") == "video"),
        None,
    )
    if not isinstance(video, Mapping):
        raise BadInput("input file has no video stream")
    duration = float(parsed.get("format", {}).get("duration") or 0)
    if duration < 5.0:
        raise BadInput(
            "input video is shorter than the Media short-form minimum of 5 seconds"
        )
    duration_ms = min(30000, int(round(duration * 1000)))
    rate = str(video.get("r_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0 or fps <= 0:
        raise BadInput("input video has invalid dimensions or frame rate")
    has_audio = any(
        item.get("codec_type") == "audio" for item in streams
    )
    return InputProbe(
        duration_ms=duration_ms,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
        sha256=_sha256_file(path),
        size=size,
    )


def resolve_media_repo(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("CREATOR_MEDIA_R13_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    creator_root = _repo_root()
    candidates.extend(
        [
            creator_root.parent / "video2",
            creator_root / ".deps" / "media-r13",
        ]
    )
    for candidate in candidates:
        if (candidate / ".git").exists() or (candidate / "src" / "index.js").is_file():
            return candidate.resolve()
    raise MissingDependency(
        "exact Media R13 checkout not found. Pass --media-repo PATH, set "
        "CREATOR_MEDIA_R13_DIR, or place foto6/video2 beside this Creator checkout."
    )


def validate_media_checkout(path: Path) -> dict[str, Any]:
    _require_tool("git")
    _require_tool("node")
    _require_tool("ffmpeg")
    _require_tool("ffprobe")
    if not (path / "src" / "index.js").is_file():
        raise MediaMismatch(f"Media checkout is missing src/index.js: {path}")
    head = _run(["git", "-C", str(path), "rev-parse", "HEAD"])
    if head.returncode != 0:
        raise MediaMismatch(
            "Media checkout is not a readable Git repository: "
            + (head.stderr.strip() or str(path))
        )
    producer_sha = head.stdout.strip()
    if producer_sha != m13.MEDIA_R13_PRODUCER_SHA:
        raise MediaMismatch(
            "Media producer SHA mismatch: expected "
            f"{m13.MEDIA_R13_PRODUCER_SHA}, got {producer_sha}"
        )
    for diff_args in (
        ["git", "-C", str(path), "diff", "--quiet"],
        ["git", "-C", str(path), "diff", "--cached", "--quiet"],
    ):
        diff = _run(diff_args)
        if diff.returncode != 0:
            raise MediaMismatch(
                "Media checkout has tracked modifications; use a clean exact "
                f"{m13.MEDIA_R13_PRODUCER_SHA} checkout"
            )
    verified = {}
    for name, pin in m13.EXPECTED_PINS.items():
        target = path / pin["path"]
        if not target.is_file():
            raise MediaMismatch(
                f"Media checkout is missing pinned file {pin['path']}"
            )
        hashed = _run(["git", "-C", str(path), "hash-object", pin["path"]])
        actual = hashed.stdout.strip() if hashed.returncode == 0 else ""
        if actual != pin["gitBlobSha"]:
            raise MediaMismatch(
                f"Media pinned blob mismatch for {name}: expected "
                f"{pin['gitBlobSha']}, got {actual or 'unavailable'}"
            )
        verified[name] = actual
    manifest_hash = _run(
        ["git", "-C", str(path), "hash-object", m13.COMPAT_MANIFEST_PATH]
    )
    actual_manifest = (
        manifest_hash.stdout.strip() if manifest_hash.returncode == 0 else ""
    )
    if actual_manifest != m13.COMPAT_MANIFEST_BLOB_SHA:
        raise MediaMismatch(
            "Media compatibility manifest blob mismatch: expected "
            f"{m13.COMPAT_MANIFEST_BLOB_SHA}, got {actual_manifest or 'unavailable'}"
        )
    local_creator_pins = m13.validate_local_pinned_contracts()
    return {
        "repository": m13.MEDIA_R13_REPOSITORY,
        "branch": m13.MEDIA_R13_BRANCH,
        "producerSha": producer_sha,
        "ciRunId": m13.MEDIA_R13_CI_RUN_ID,
        "ciConclusion": m13.MEDIA_R13_CI_CONCLUSION,
        "contractVersion": m13.MEDIA_R13_COMPAT_VERSION,
        "mediaCheckout": str(path),
        "pins": verified,
        "compatibilityManifestBlobSha": actual_manifest,
        "creatorVendoredPins": local_creator_pins,
    }


def _run_id(
    *,
    input_probe: InputProbe,
    brief: str,
    style: str,
) -> str:
    return reels.sha256_json(
        {
            "version": MVP_VERSION,
            "inputSha256": input_probe.sha256,
            "brief": brief,
            "style": style,
            "mediaProducerSha": m13.MEDIA_R13_PRODUCER_SHA,
        }
    )[:20]


def _safe_clean_managed_work(work: Path, *, out_root: Path, run_id: str) -> None:
    if not work.exists():
        return
    try:
        work.relative_to(out_root)
    except ValueError as exc:
        raise MvpError("managed work directory escaped output root") from exc
    marker = work / ".creator-mvp-managed.json"
    if not marker.is_file():
        raise MvpError(
            f"refusing to clean unmarked work directory: {work}"
        )
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MvpError(
            f"refusing to clean invalid managed work directory: {work}"
        ) from exc
    if value.get("runId") != run_id:
        raise MvpError(
            f"refusing to clean work directory owned by another run: {work}"
        )
    shutil.rmtree(work)


def _write_json_atomic(path: Path, value: Mapping[str, Any], *, run_id: str) -> None:
    temp = path.with_name(f".{path.name}.{run_id}.tmp")
    temp.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def _copy_atomic(source: Path, destination: Path, *, run_id: str) -> None:
    temp = destination.with_name(f".{destination.name}.{run_id}.tmp")
    shutil.copy2(source, temp)
    os.replace(temp, destination)


def _resolve_managed_path(work: Path, relative: str, label: str) -> Path:
    value = (work / relative).resolve()
    root = work.resolve()
    try:
        value.relative_to(root)
    except ValueError as exc:
        raise RenderFailed(f"{label} escaped managed work directory") from exc
    if not value.is_file():
        raise RenderFailed(f"{label} was not produced: {value}")
    return value


def _classify_bridge_failure(stderr: str) -> MvpError:
    text = stderr.strip()
    lowered = text.lower()
    if "technical qa" in lowered or "qa_failed" in lowered:
        return TechnicalQaFailed(text or "Media technical QA failed")
    if "creative" in lowered and (
        "guardrail" in lowered or "quality" in lowered or "visual qa" in lowered
    ):
        return CreativeQaFailed(text or "Media creative QA failed")
    if "producer sha" in lowered or "pinned blob" in lowered or "contract" in lowered:
        return MediaMismatch(text or "Media R13 contract mismatch")
    return RenderFailed(text or "Media R13 render bridge failed")


def run_pipeline(
    *,
    input_path: str | Path,
    brief_arg: str,
    out_dir: str | Path,
    style: str = "auto",
    media_repo: str | None = None,
    keep_work: bool = False,
    semantic_adapters: director.SemanticAdapters | None = None,
    semantic_provider: str = "auto",
    gemini_mode: str = "static",
    gemini_fps: float = 1.0,
    gemini_clip_start_seconds: float = 0.0,
    gemini_clip_end_seconds: float | None = None,
) -> dict[str, Any]:
    if style not in {"auto", *STYLE_MAP}:
        raise BadInput(
            f"unsupported style {style!r}; choose one of: "
            + ", ".join(["auto", *sorted(STYLE_MAP)])
        )
    source = Path(input_path).expanduser().resolve()
    out_root = Path(out_dir).expanduser().resolve()
    if source == out_root:
        raise BadInput("--out cannot be the input video path")
    probe = probe_input(source)
    brief, fallback = normalize_brief(brief_arg)
    script = build_local_script(brief, duration_ms=probe.duration_ms)
    if semantic_provider not in {"auto", "local", "gemini"}:
        raise BadInput("--semantic-provider must be auto, local or gemini")
    gemini_config = None
    gemini_attempted = False
    if semantic_adapters is None:
        gemini_configured = bool(
            _env_truthy("CREATOR_GEMINI_VIDEO_ENABLE")
            and os.environ.get("GEMINI_API_KEY", "").strip()
        )
        should_try_gemini = (
            semantic_provider == "gemini"
            or (semantic_provider == "auto" and gemini_configured)
        )
        if should_try_gemini:
            try:
                gemini_config = gemini_video.GeminiNativeVideoConfig.from_env(
                    explicitly_enabled=True,
                    mode=gemini_mode,
                    fps=gemini_fps,
                    clip_start_seconds=gemini_clip_start_seconds,
                    clip_end_seconds=gemini_clip_end_seconds,
                )
            except ValueError as exc:
                raise BadInput(f"invalid Gemini semantic config: {exc}") from exc
            semantic_adapters = gemini_video.build_semantic_adapters(
                config=gemini_config,
            )
            gemini_attempted = True
        else:
            semantic_adapters = director.SemanticAdapters.local_default()
    try:
        semantic_analysis = director.analyze_video(
            source,
            input_sha256=probe.sha256,
            duration_ms=probe.duration_ms,
            width=probe.width,
            height=probe.height,
            fps=probe.fps,
            has_audio=probe.has_audio,
            brief=brief,
            adapters=semantic_adapters,
        )
        editorial_decision = director.select_editorial_mode(
            semantic_analysis,
            override=style,
        )
        edit_directives = director.generate_edit_directives(
            semantic_analysis,
            editorial_decision,
        )
        director_report = director.build_director_report(
            semantic_analysis,
            editorial_decision,
            edit_directives,
        )
        provider_identity = _semantic_provider_identity(
            semantic_analysis,
            requested=semantic_provider,
            gemini_model=(
                gemini_config.model
                if gemini_config is not None
                else os.environ.get("GEMINI_MODEL")
            ),
            gemini_mode=(
                gemini_config.mode
                if gemini_config is not None
                else gemini_mode
            ),
            gemini_attempted=gemini_attempted,
        )
        style_artifact = _style_artifact(
            editorial_decision,
            source_sha256=probe.sha256,
        )
        directives_artifact = _directives_artifact(
            edit_directives,
            source_sha256=probe.sha256,
            semantic_digest=semantic_analysis["analysisDigest"],
            style_decision_digest=style_artifact["styleDecisionDigest"],
        )
    except director.SemanticDirectorError as exc:
        raise InsufficientEvidence(
            f"semantic director rejected evidence: {exc}"
        ) from exc
    media_path = resolve_media_repo(media_repo)
    media_pin = validate_media_checkout(media_path)

    run_id = _run_id(input_probe=probe, brief=brief, style=style)
    out_root.mkdir(parents=True, exist_ok=True)
    work_parent = out_root / ".creator-mvp-work"
    work = work_parent / run_id
    _safe_clean_managed_work(work, out_root=out_root, run_id=run_id)
    work.mkdir(parents=True, exist_ok=False)
    _write_json_atomic(
        work / ".creator-mvp-managed.json",
        {"runId": run_id, "version": MVP_VERSION},
        run_id=run_id,
    )
    semantic_path = out_root / "semantic-timeline.json"
    directives_path = out_root / "editorial-directives.json"
    style_decision_path = out_root / "style-decision.json"
    director_path = out_root / "director-report.json"
    _write_json_atomic(
        semantic_path,
        semantic_analysis,
        run_id=run_id,
    )
    _write_json_atomic(
        directives_path,
        directives_artifact,
        run_id=run_id,
    )
    _write_json_atomic(
        style_decision_path,
        style_artifact,
        run_id=run_id,
    )
    _write_json_atomic(
        director_path,
        director_report,
        run_id=run_id,
    )
    inputs = work / "inputs"
    inputs.mkdir()
    source_copy = inputs / ("source" + (source.suffix.lower() or ".mp4"))
    shutil.copy2(source, source_copy)
    if (
        _sha256_file(source_copy) != probe.sha256
        or source_copy.stat().st_size != probe.size
    ):
        raise BadInput("managed source copy does not match user source bytes")

    request = {
        "contractVersion": MVP_VERSION,
        "runId": run_id,
        "source": {
            "relativePath": source_copy.relative_to(work).as_posix(),
            **probe.as_dict(),
        },
        "brief": {
            "normalized": brief,
            "fallback": fallback,
        },
        "script": script,
        "style": {
            "operatorStyle": style,
            "autoMode": editorial_decision["autoDirector"]["mode"],
            "editorialMode": editorial_decision["effectiveMode"],
            "mediaStyle": editorial_decision["mediaBaseStyle"],
            "autoConfidence": editorial_decision["autoDirector"]["confidence"],
            "override": editorial_decision["override"],
        },
        "semanticDirector": {
            "contractVersion": director.SEMANTIC_ANALYSIS_VERSION,
            "analysisDigest": semantic_analysis["analysisDigest"],
            "decision": editorial_decision,
            "directives": edit_directives,
            "mediaHints": edit_directives["mediaHints"],
            "unavailableEvidence": semantic_analysis["unavailableEvidence"],
            "humanLevelQuality": director.HUMAN_LEVEL_STATE,
            "providerSelection": semantic_provider,
            "providerIdentity": provider_identity,
            "geminiMode": (
                gemini_mode
                if semantic_provider in {"auto", "gemini"}
                else None
            ),
            "styleDecisionDigest": style_artifact["styleDecisionDigest"],
            "editorialDirectivesDigest": directives_artifact[
                "editorialDirectivesDigest"
            ],
        },
        "targetDurationMs": probe.duration_ms,
        "publishingEnabled": False,
        "growthEnabled": False,
        "analyticsEnabled": False,
    }
    request["requestDigest"] = reels.sha256_json(request)
    request_path = work / "request.json"
    response_path = work / "media-response.json"
    _write_json_atomic(request_path, request, run_id=run_id)

    bridge = _repo_root() / "tools" / "creator-mvp-media-r13.mjs"
    if not bridge.is_file():
        raise MissingDependency(f"Media bridge script is missing: {bridge}")
    proc = _run(
        [
            "node",
            str(bridge),
            "--media-repo", str(media_path),
            "--work-dir", str(work),
            "--request", str(request_path),
            "--response", str(response_path),
        ],
        timeout=240,
    )
    if proc.returncode != 0:
        raise _classify_bridge_failure(proc.stderr or proc.stdout)
    if not response_path.is_file():
        raise RenderFailed("Media bridge returned success without media-response.json")
    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderFailed("Media bridge response is invalid JSON") from exc
    if response.get("contractVersion") != "creator.mvp_media_result.r17.v1":
        raise MediaMismatch("unexpected MVP Media result contract version")

    try:
        envelope = m13.validate_envelope(response["envelope"])
    except (m13.MediaR13CompatibilityError, reels.AutonomousReelsError) as exc:
        message = str(exc)
        if "source provenance" in message.lower():
            raise InsufficientEvidence(message) from exc
        raise MediaMismatch(message) from exc
    if envelope["producer"]["sha"] != m13.MEDIA_R13_PRODUCER_SHA:
        raise MediaMismatch("render result producer SHA changed after preflight")
    evidence = envelope["probeEvidence"]["value"].get("sourceEvidence")
    if not isinstance(evidence, list) or not evidence:
        raise InsufficientEvidence(
            "Media result has no source-bound provenance evidence"
        )
    matching_source = [
        item
        for item in evidence
        if item.get("sha256") == probe.sha256
        and item.get("size") == probe.size
        and item.get("exists") is True
        and item.get("probeOk") is True
    ]
    if not matching_source:
        raise InsufficientEvidence(
            "Media result does not bind the operator source video digest/size"
        )
    technical = envelope["technicalQa"]
    if technical["passed"] is not True:
        raise TechnicalQaFailed("Media R13 technical QA failed")
    creative = envelope["creativeQuality"]
    if creative["passed"] is not True:
        raise CreativeQaFailed("Media R13 creative QA failed")

    rendered = _resolve_managed_path(
        work,
        response["renderedRelativePath"],
        "Media final render",
    )
    preview = _resolve_managed_path(
        work,
        response["previewRelativePath"],
        "Media preview",
    )
    final_hash = _sha256_file(rendered)
    if (
        final_hash != envelope["finalContent"]["sha256"]
        or rendered.stat().st_size != envelope["finalContent"]["size"]
    ):
        raise MediaMismatch(
            "rendered MP4 bytes do not match Media R13 finalContent provenance"
        )

    final_path = out_root / "final.mp4"
    preview_path = out_root / "preview.mp4"
    qa_path = out_root / "qa.json"
    summary_path = out_root / "run-summary.json"
    content_aware_path = out_root / "content-aware-run.json"
    _copy_atomic(rendered, final_path, run_id=run_id)
    _copy_atomic(preview, preview_path, run_id=run_id)

    qa = {
        "contractVersion": QA_VERSION,
        "runId": run_id,
        "mediaProducerSha": m13.MEDIA_R13_PRODUCER_SHA,
        "technicalQa": technical,
        "creativeQa": creative,
        "sourceEvidence": evidence,
        "semanticDirector": {
            "analysisDigest": semantic_analysis["analysisDigest"],
            "directorReportDigest": director_report["reportDigest"],
            "readiness": director.READINESS_STATE,
            "humanLevelQuality": director.HUMAN_LEVEL_STATE,
            "unavailableEvidence": semantic_analysis["unavailableEvidence"],
            "providerIdentity": provider_identity,
            "styleDecisionDigest": style_artifact["styleDecisionDigest"],
            "editorialDirectivesDigest": directives_artifact[
                "editorialDirectivesDigest"
            ],
        },
        "gates": {
            "input_ok": True,
            "media_pin_ok": True,
            "render_ok": True,
            "technical_qa_ok": True,
            "creative_qa_ok": True,
            "artifact_export_ok": True,
        },
    }
    qa["qaDigest"] = reels.sha256_json(qa)
    _write_json_atomic(qa_path, qa, run_id=run_id)

    summary = {
        "contractVersion": SUMMARY_VERSION,
        "state": "MVP_GREEN",
        "runId": run_id,
        "requestDigest": request["requestDigest"],
        "input": {
            "path": str(source),
            **probe.as_dict(),
        },
        "brief": {
            "normalized": brief,
            **fallback,
        },
        "script": script,
        "style": request["style"],
        "semanticDirector": {
            "analysisDigest": semantic_analysis["analysisDigest"],
            "directorReportDigest": director_report["reportDigest"],
            "readiness": director.READINESS_STATE,
            "humanLevelQuality": director.HUMAN_LEVEL_STATE,
            "chosenStyle": editorial_decision,
            "unavailableEvidence": semantic_analysis["unavailableEvidence"],
            "providerSelection": semantic_provider,
            "providerIdentity": provider_identity,
            "geminiMode": (
                gemini_mode
                if semantic_provider in {"auto", "gemini"}
                else None
            ),
            "styleDecisionDigest": style_artifact["styleDecisionDigest"],
            "editorialDirectivesDigest": directives_artifact[
                "editorialDirectivesDigest"
            ],
        },
        "media": {
            **media_pin,
            "compatibilityEnvelopeContract": envelope["contractVersion"],
            "logicalJobId": envelope["logicalJobId"],
            "renderFingerprint": envelope["renderFingerprint"],
            "timelineDigest": envelope["timelineDigest"],
            "artifactManifestDigest": envelope["artifactManifestDigest"],
            "creativePlan": response.get("creativePlan"),
        },
        "outputs": {
            "final": {
                "path": str(final_path),
                "sha256": _sha256_file(final_path),
                "size": final_path.stat().st_size,
            },
            "preview": {
                "path": str(preview_path),
                "sha256": _sha256_file(preview_path),
                "size": preview_path.stat().st_size,
            },
            "qa": str(qa_path),
            "semanticTimeline": str(semantic_path),
            "editorialDirectives": str(directives_path),
            "styleDecision": str(style_decision_path),
            "directorReport": str(director_path),
            "contentAwareRun": str(content_aware_path),
        },
        "gates": dict(qa["gates"]),
        "fallback": fallback,
        "publishingEnabled": False,
        "growthEnabled": False,
        "analyticsEnabled": False,
        "credentialsPresent": False,
    }
    content_aware_run = {
        "contractVersion": CONTENT_AWARE_RUN_VERSION,
        "runId": run_id,
        "source": {
            "sha256": probe.sha256,
            "durationMs": probe.duration_ms,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
        },
        "semantic": {
            "provider": provider_identity,
            "fallback": provider_identity["fallback"],
            "timelineContract": semantic_analysis["contractVersion"],
            "timelineDigest": semantic_analysis["analysisDigest"],
            "styleDecisionContract": STYLE_DECISION_VERSION,
            "styleDecisionDigest": style_artifact["styleDecisionDigest"],
            "directivesContract": EDITORIAL_DIRECTIVES_VERSION,
            "directivesDigest": directives_artifact[
                "editorialDirectivesDigest"
            ],
            "humanLevelQuality": director.HUMAN_LEVEL_STATE,
        },
        "media": {
            "repository": media_pin["repository"],
            "producerSha": media_pin["producerSha"],
            "compatibilityContract": media_pin["contractVersion"],
            "compatibilityManifestBlobSha": media_pin[
                "compatibilityManifestBlobSha"
            ],
            "contractBlobDigests": media_pin["pins"],
            "renderFingerprint": envelope["renderFingerprint"],
            "timelineDigest": envelope["timelineDigest"],
            "artifactManifestDigest": envelope["artifactManifestDigest"],
        },
        "artifacts": {
            "final": summary["outputs"]["final"],
            "preview": summary["outputs"]["preview"],
        },
        "qa": {
            "qaDigest": qa["qaDigest"],
            "technicalQaDigest": reels.sha256_json(technical),
            "creativeQaDigest": reels.sha256_json(creative),
            "technicalPassed": technical["passed"],
            "creativePassed": creative["passed"],
        },
        "claims": {
            "contentAwareEvidence": True,
            "humanLevelQualityClaimed": False,
            "aestheticSuperiorityClaimed": False,
        },
        "publishingEnabled": False,
        "growthEnabled": False,
        "analyticsEnabled": False,
    }
    content_aware_run["runDigest"] = reels.sha256_json(content_aware_run)
    _write_json_atomic(
        content_aware_path,
        content_aware_run,
        run_id=run_id,
    )
    summary["contentAwareRun"] = {
        "contractVersion": CONTENT_AWARE_RUN_VERSION,
        "runDigest": content_aware_run["runDigest"],
        "path": str(content_aware_path),
    }
    summary["summaryDigest"] = reels.sha256_json(summary)
    _write_json_atomic(summary_path, summary, run_id=run_id)

    if not keep_work:
        _safe_clean_managed_work(work, out_root=out_root, run_id=run_id)
        try:
            work_parent.rmdir()
        except OSError:
            pass
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="creator-mvp",
        description=(
            "Render one local source video into a finished vertical MP4 using "
            "the exact pinned Media R13 producer."
        ),
    )
    parser.add_argument("--input", required=True, help="local source video")
    parser.add_argument(
        "--brief",
        required=True,
        help="short inline brief or path to a UTF-8 text file",
    )
    parser.add_argument("--out", required=True, help="operator output directory")
    parser.add_argument(
        "--style",
        choices=("auto", *tuple(STYLE_MAP)),
        default="auto",
        help=(
            "auto selects an evidence-based editorial mode; an explicit style "
            "overrides the director and disagreement is reported"
        ),
    )
    parser.add_argument(
        "--media-repo",
        help=(
            "optional exact foto6/video2 checkout; otherwise uses "
            "CREATOR_MEDIA_R13_DIR or a sibling video2 checkout"
        ),
    )
    parser.add_argument(
        "--semantic-provider",
        choices=("auto", "local", "gemini"),
        default="auto",
        help=(
            "auto uses Gemini only when explicitly configured with enable flag "
            "and credentials, otherwise labels deterministic local fallback"
        ),
    )
    parser.add_argument(
        "--gemini-mode",
        choices=("static", "agentic"),
        default="static",
        help="Gemini video processing mode when --semantic-provider gemini",
    )
    parser.add_argument(
        "--gemini-fps",
        type=float,
        default=1.0,
        help="static Gemini video sampling FPS",
    )
    parser.add_argument(
        "--gemini-clip-start",
        type=float,
        default=0.0,
        help="static Gemini clip start in seconds",
    )
    parser.add_argument(
        "--gemini-clip-end",
        type=float,
        help="optional static Gemini clip end in seconds",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="preserve the managed work directory after success",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = run_pipeline(
            input_path=args.input,
            brief_arg=args.brief,
            out_dir=args.out,
            style=args.style,
            media_repo=args.media_repo,
            keep_work=args.keep_work,
            semantic_provider=args.semantic_provider,
            gemini_mode=args.gemini_mode,
            gemini_fps=args.gemini_fps,
            gemini_clip_start_seconds=args.gemini_clip_start,
            gemini_clip_end_seconds=args.gemini_clip_end,
        )
    except MvpError as exc:
        print(f"creator-mvp: {exc}", file=sys.stderr)
        return exc.exit_code
    except subprocess.TimeoutExpired as exc:
        print(
            f"creator-mvp: Media command timed out: {exc}",
            file=sys.stderr,
        )
        return EXIT_RENDER_FAILED
    except Exception as exc:
        print(
            f"creator-mvp: unexpected failure: {exc}",
            file=sys.stderr,
        )
        return EXIT_INTERNAL
    print(json.dumps(summary, sort_keys=True, indent=2))
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
