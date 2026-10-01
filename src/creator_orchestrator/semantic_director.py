from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from . import autonomous_reels as reels

SEMANTIC_ANALYSIS_VERSION = "creator.semantic_video_analysis.r18.v1"
DIRECTOR_REPORT_VERSION = "creator.semantic_video_director.r18.v1"
ADAPTER_RESULT_VERSION = "creator.semantic_adapter_result.r18.v1"
READINESS_STATE = "SEMANTIC_PIPELINE_READY"
HUMAN_LEVEL_STATE = "HUMAN_LEVEL_UNPROVEN"

EDITORIAL_MODES = (
    "clean_podcast",
    "aggressive_shortform",
    "cinematic_minimal",
    "hybrid",
)

SEMANTIC_EVENT_TYPES = {
    "hook",
    "setup",
    "proof_demo",
    "explanation",
    "punchline_payoff",
    "cta_candidate",
    "low_information",
}

EVIDENCE_CATEGORIES = (
    "transcriptSegments",
    "sentenceBoundaries",
    "shotBoundaries",
    "visualSubjects",
    "importantObjects",
    "motionEnergy",
    "audioEnergy",
    "semanticEvents",
)


class SemanticDirectorError(ValueError):
    pass


class SemanticAdapter(Protocol):
    name: str

    def analyze(
        self,
        video_path: Path,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


class AsrAdapter(SemanticAdapter, Protocol):
    pass


class ShotDetectorAdapter(SemanticAdapter, Protocol):
    pass


class CvTrackingAdapter(SemanticAdapter, Protocol):
    pass


class VlmSemanticAdapter(SemanticAdapter, Protocol):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _confidence(value: Any, field: str = "confidence") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SemanticDirectorError(f"{field} must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise SemanticDirectorError(f"{field} must be between 0 and 1")
    return round(number, 6)


def _bounded_time(
    value: Any,
    *,
    duration_ms: int,
    field: str,
    allow_end: bool = True,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SemanticDirectorError(f"{field} must be an integer")
    maximum = duration_ms if allow_end else max(0, duration_ms - 1)
    if value < 0 or value > maximum:
        raise SemanticDirectorError(
            f"{field} must be within source duration"
        )
    return value


def _source(
    *,
    adapter: str,
    mode: str,
    input_sha256: str,
    detail: str,
) -> dict[str, Any]:
    if mode not in {
        "provider",
        "deterministic_local",
        "derived_from_provider",
        "derived_from_local",
    }:
        raise SemanticDirectorError("unsupported evidence source mode")
    reels._sha64(input_sha256, "semantic input sha256")
    value = {
        "adapter": adapter,
        "mode": mode,
        "inputSha256": input_sha256,
        "detail": detail,
    }
    value["sourceDigest"] = reels.sha256_json(value)
    return value


def evidence_span(
    *,
    evidence_type: str,
    start_ms: int,
    end_ms: int,
    value: Mapping[str, Any],
    confidence: float,
    source: Mapping[str, Any],
    duration_ms: int,
) -> dict[str, Any]:
    start = _bounded_time(
        start_ms,
        duration_ms=duration_ms,
        field="startMs",
        allow_end=False,
    )
    end = _bounded_time(
        end_ms,
        duration_ms=duration_ms,
        field="endMs",
    )
    if end <= start:
        raise SemanticDirectorError("evidence span endMs must exceed startMs")
    if not isinstance(value, Mapping):
        raise SemanticDirectorError("evidence value must be an object")
    item = {
        "evidenceType": evidence_type,
        "startMs": start,
        "endMs": end,
        "value": _clone(value),
        "confidence": _confidence(confidence),
        "source": _clone(source),
    }
    item["evidenceDigest"] = reels.sha256_json(item)
    return item


def _validate_evidence(
    item: Mapping[str, Any],
    *,
    duration_ms: int,
) -> dict[str, Any]:
    required = {
        "evidenceType",
        "startMs",
        "endMs",
        "value",
        "confidence",
        "source",
        "evidenceDigest",
    }
    if not isinstance(item, Mapping) or set(item) != required:
        raise SemanticDirectorError(
            "semantic evidence fields must match exactly"
        )
    source = item["source"]
    if not isinstance(source, Mapping) or set(source) != {
        "adapter",
        "mode",
        "inputSha256",
        "detail",
        "sourceDigest",
    }:
        raise SemanticDirectorError("semantic evidence source fields invalid")
    material = dict(source)
    source_digest = material.pop("sourceDigest")
    if reels.sha256_json(material) != source_digest:
        raise SemanticDirectorError("semantic evidence source digest mismatch")
    reels._sha64(source["inputSha256"], "semantic source inputSha256")
    material = dict(item)
    digest = material.pop("evidenceDigest")
    if reels.sha256_json(material) != digest:
        raise SemanticDirectorError("semantic evidence digest mismatch")
    _bounded_time(
        item["startMs"],
        duration_ms=duration_ms,
        field="evidence.startMs",
        allow_end=False,
    )
    _bounded_time(
        item["endMs"],
        duration_ms=duration_ms,
        field="evidence.endMs",
    )
    if item["endMs"] <= item["startMs"]:
        raise SemanticDirectorError("semantic evidence span is empty")
    _confidence(item["confidence"], "evidence.confidence")
    return _clone(item)


@dataclass(frozen=True)
class UnavailableAdapter:
    name: str
    evidence_categories: tuple[str, ...]
    reason: str = "provider_not_configured"

    def analyze(
        self,
        video_path: Path,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return {
            "contractVersion": ADAPTER_RESULT_VERSION,
            "adapter": self.name,
            "status": "unavailable",
            "providerMode": "unavailable",
            "evidence": [],
            "unavailableCategories": list(self.evidence_categories),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FixtureAdapter:
    name: str
    evidence: tuple[Mapping[str, Any], ...]
    categories: tuple[str, ...]

    def analyze(
        self,
        video_path: Path,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        duration_ms = int(context["durationMs"])
        input_sha = str(context["inputSha256"])
        converted = []
        for raw in self.evidence:
            converted.append(
                evidence_span(
                    evidence_type=str(raw["evidenceType"]),
                    start_ms=int(raw["startMs"]),
                    end_ms=int(raw["endMs"]),
                    value=raw["value"],
                    confidence=float(raw["confidence"]),
                    source=_source(
                        adapter=self.name,
                        mode="provider",
                        input_sha256=input_sha,
                        detail=str(
                            raw.get(
                                "sourceDetail",
                                "deterministic conformance adapter evidence",
                            )
                        ),
                    ),
                    duration_ms=duration_ms,
                )
            )
        return {
            "contractVersion": ADAPTER_RESULT_VERSION,
            "adapter": self.name,
            "status": "available",
            "providerMode": "fixture_provider",
            "evidence": converted,
            "unavailableCategories": [],
            "reason": None,
        }


class LocalFfmpegShotAdapter:
    name = "local_ffmpeg_scene_detector"

    def analyze(
        self,
        video_path: Path,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return UnavailableAdapter(
                self.name,
                ("shotBoundaries", "motionEnergy"),
                "ffmpeg_not_found",
            ).analyze(video_path, context)
        duration_ms = int(context["durationMs"])
        input_sha = str(context["inputSha256"])
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostdin",
                    "-i",
                    str(video_path),
                    "-vf",
                    "select='gt(scene,0.30)',showinfo",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return UnavailableAdapter(
                self.name,
                ("shotBoundaries", "motionEnergy"),
                "local_scene_detector_failed",
            ).analyze(video_path, context)
        if result.returncode != 0:
            return UnavailableAdapter(
                self.name,
                ("shotBoundaries", "motionEnergy"),
                "local_scene_detector_failed",
            ).analyze(video_path, context)
        points = []
        for raw in re.findall(r"pts_time:([0-9.]+)", result.stderr):
            ms = max(1, min(duration_ms - 1, int(round(float(raw) * 1000))))
            if ms not in points:
                points.append(ms)
        points.sort()
        source = _source(
            adapter=self.name,
            mode="deterministic_local",
            input_sha256=input_sha,
            detail="ffmpeg scene score > 0.30",
        )
        evidence = [
            evidence_span(
                evidence_type="shot_boundary",
                start_ms=point,
                end_ms=min(duration_ms, point + 1),
                value={"boundaryMs": point, "threshold": 0.30},
                confidence=0.72,
                source=source,
                duration_ms=duration_ms,
            )
            for point in points
        ]
        bucket_ms = 3000
        for start in range(0, duration_ms, bucket_ms):
            end = min(duration_ms, start + bucket_ms)
            count = sum(start <= point < end for point in points)
            energy = min(1.0, count / 3.0)
            evidence.append(
                evidence_span(
                    evidence_type="motion_energy",
                    start_ms=start,
                    end_ms=end,
                    value={
                        "normalizedEnergy": round(energy, 4),
                        "basis": "scene_boundary_density",
                        "boundaries": count,
                    },
                    confidence=0.55,
                    source=_source(
                        adapter=self.name,
                        mode="derived_from_local",
                        input_sha256=input_sha,
                        detail="motion proxy derived only from local scene-boundary density",
                    ),
                    duration_ms=duration_ms,
                )
            )
        return {
            "contractVersion": ADAPTER_RESULT_VERSION,
            "adapter": self.name,
            "status": "available",
            "providerMode": "deterministic_local",
            "evidence": evidence,
            "unavailableCategories": [],
            "reason": None,
        }


def local_audio_evidence(
    video_path: Path,
    context: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    if context.get("hasAudio") is not True:
        return [], ["speech_energy", "silence", "music"]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return [], ["speech_energy", "silence", "music"]
    duration_ms = int(context["durationMs"])
    input_sha = str(context["inputSha256"])
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-i",
                str(video_path),
                "-af",
                "silencedetect=n=-40dB:d=0.35",
                "-vn",
                "-f",
                "null",
                "-",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], ["speech_energy", "silence", "music"]
    if result.returncode != 0:
        return [], ["speech_energy", "silence", "music"]
    starts = [float(v) for v in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [float(v) for v in re.findall(r"silence_end: ([0-9.]+)", result.stderr)]
    spans = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration_ms / 1000
        a = max(0, min(duration_ms - 1, int(round(start * 1000))))
        b = max(a + 1, min(duration_ms, int(round(end * 1000))))
        spans.append(
            evidence_span(
                evidence_type="audio_energy",
                start_ms=a,
                end_ms=b,
                value={
                    "signalType": "silence",
                    "energy": 0.0,
                    "thresholdDb": -40,
                },
                confidence=0.85,
                source=_source(
                    adapter="local_ffmpeg_audio_detector",
                    mode="deterministic_local",
                    input_sha256=input_sha,
                    detail="ffmpeg silencedetect -40dB >=350ms",
                ),
                duration_ms=duration_ms,
            )
        )
    return spans, ["speech_energy", "music"]


@dataclass(frozen=True)
class SemanticAdapters:
    asr: AsrAdapter
    shot: ShotDetectorAdapter
    cv: CvTrackingAdapter
    vlm: VlmSemanticAdapter

    @classmethod
    def local_default(cls) -> "SemanticAdapters":
        return cls(
            asr=UnavailableAdapter(
                "asr",
                ("transcriptSegments", "sentenceBoundaries", "speech_energy"),
            ),
            shot=LocalFfmpegShotAdapter(),
            cv=UnavailableAdapter(
                "cv_tracking",
                ("visualSubjects", "importantObjects"),
            ),
            vlm=UnavailableAdapter(
                "vlm_semantic",
                ("semanticEvents",),
            ),
        )


def _normalize_adapter_result(
    raw: Mapping[str, Any],
    *,
    duration_ms: int,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SemanticDirectorError("adapter result must be an object")
    required = {
        "contractVersion",
        "adapter",
        "status",
        "providerMode",
        "evidence",
        "unavailableCategories",
        "reason",
    }
    if set(raw) != required:
        raise SemanticDirectorError("adapter result fields must match exactly")
    if raw["contractVersion"] != ADAPTER_RESULT_VERSION:
        raise SemanticDirectorError("adapter result contract version mismatch")
    if raw["status"] not in {"available", "unavailable", "degraded"}:
        raise SemanticDirectorError("adapter result status is invalid")
    if not isinstance(raw["evidence"], list):
        raise SemanticDirectorError("adapter evidence must be an array")
    evidence = [
        _validate_evidence(item, duration_ms=duration_ms)
        for item in raw["evidence"]
    ]
    unavailable = raw["unavailableCategories"]
    if not isinstance(unavailable, list) or not all(
        isinstance(item, str) and item for item in unavailable
    ):
        raise SemanticDirectorError(
            "adapter unavailableCategories must be strings"
        )
    return {
        "contractVersion": ADAPTER_RESULT_VERSION,
        "adapter": str(raw["adapter"]),
        "status": raw["status"],
        "providerMode": str(raw["providerMode"]),
        "evidence": evidence,
        "unavailableCategories": sorted(set(unavailable)),
        "reason": raw["reason"],
    }


def _categorize(item: Mapping[str, Any]) -> str:
    kind = item["evidenceType"]
    return {
        "transcript_segment": "transcriptSegments",
        "sentence_boundary": "sentenceBoundaries",
        "shot_boundary": "shotBoundaries",
        "visual_subject": "visualSubjects",
        "important_object": "importantObjects",
        "motion_energy": "motionEnergy",
        "audio_energy": "audioEnergy",
        "semantic_event": "semanticEvents",
    }.get(kind, "")


def _derived_semantic_events(
    categories: Mapping[str, list[dict[str, Any]]],
    *,
    duration_ms: int,
    input_sha: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    events.append(
        evidence_span(
            evidence_type="semantic_event",
            start_ms=0,
            end_ms=min(duration_ms, 3000),
            value={
                "event": "hook",
                "basis": "structural_opening_candidate_only",
                "claimLevel": "candidate_not_semantic_confirmation",
            },
            confidence=0.30,
            source=_source(
                adapter="semantic_director",
                mode="derived_from_local",
                input_sha256=input_sha,
                detail="first 1-3 seconds treated only as structural hook candidate",
            ),
            duration_ms=duration_ms,
        )
    )
    keyword_rules = (
        ("proof_demo", re.compile(r"\b(watch|show|demo|result|before|after|here is|here's)\b", re.I)),
        ("explanation", re.compile(r"\b(because|why|how|means|works|reason)\b", re.I)),
        ("punchline_payoff", re.compile(r"\b(punchline|finally|turns out|but then|payoff|reveal)\b", re.I)),
        ("cta_candidate", re.compile(r"\b(follow|subscribe|save|comment|share|click|try it)\b", re.I)),
        ("setup", re.compile(r"\b(first|started|setup|context|problem|story)\b", re.I)),
    )
    for segment in categories["transcriptSegments"]:
        text = str(segment["value"].get("text", ""))
        for event_name, pattern in keyword_rules:
            if pattern.search(text):
                events.append(
                    evidence_span(
                        evidence_type="semantic_event",
                        start_ms=segment["startMs"],
                        end_ms=segment["endMs"],
                        value={
                            "event": event_name,
                            "basis": "deterministic_keyword_in_source_bound_asr",
                            "textDigest": reels.sha256_text(text),
                        },
                        confidence=min(
                            0.72,
                            float(segment["confidence"]) * 0.75,
                        ),
                        source=_source(
                            adapter="semantic_director",
                            mode="derived_from_provider",
                            input_sha256=input_sha,
                            detail="low-certainty keyword inference from source-bound ASR transcript",
                        ),
                        duration_ms=duration_ms,
                    )
                )
                break

    silence = [
        item
        for item in categories["audioEnergy"]
        if item["value"].get("signalType") == "silence"
    ]
    motion = categories["motionEnergy"]
    for silent in silence:
        overlapping = [
            item
            for item in motion
            if item["startMs"] < silent["endMs"]
            and item["endMs"] > silent["startMs"]
        ]
        if overlapping and max(
            float(item["value"].get("normalizedEnergy", 1.0))
            for item in overlapping
        ) <= 0.34:
            events.append(
                evidence_span(
                    evidence_type="semantic_event",
                    start_ms=silent["startMs"],
                    end_ms=silent["endMs"],
                    value={
                        "event": "low_information",
                        "basis": "local_silence_plus_low_scene_change",
                    },
                    confidence=0.58,
                    source=_source(
                        adapter="semantic_director",
                        mode="derived_from_local",
                        input_sha256=input_sha,
                        detail="low-information proxy from measured silence plus low scene-change density",
                    ),
                    duration_ms=duration_ms,
                )
            )
    return events


def analyze_video(
    video_path: str | Path,
    *,
    input_sha256: str,
    duration_ms: int,
    width: int,
    height: int,
    fps: float,
    has_audio: bool,
    brief: str,
    adapters: SemanticAdapters | None = None,
) -> dict[str, Any]:
    reels._sha64(input_sha256, "semantic analysis input_sha256")
    if duration_ms < 1:
        raise SemanticDirectorError("duration_ms must be positive")
    path = Path(video_path)
    adapters = adapters or SemanticAdapters.local_default()
    context = {
        "inputSha256": input_sha256,
        "durationMs": duration_ms,
        "width": width,
        "height": height,
        "fps": fps,
        "hasAudio": has_audio,
        "brief": brief,
        "briefDigest": reels.sha256_text(brief),
    }
    results = []
    for adapter in (
        adapters.asr,
        adapters.shot,
        adapters.cv,
        adapters.vlm,
    ):
        results.append(
            _normalize_adapter_result(
                adapter.analyze(path, context),
                duration_ms=duration_ms,
            )
        )
    categories: dict[str, list[dict[str, Any]]] = {
        name: [] for name in EVIDENCE_CATEGORIES
    }
    unavailable: set[str] = set()
    for result in results:
        unavailable.update(result["unavailableCategories"])
        for item in result["evidence"]:
            category = _categorize(item)
            if not category:
                raise SemanticDirectorError(
                    f"unsupported evidence type {item['evidenceType']!r}"
                )
            categories[category].append(item)

    audio, audio_unavailable = local_audio_evidence(path, context)
    categories["audioEnergy"].extend(audio)
    unavailable.update(audio_unavailable)

    transcript = categories["transcriptSegments"]
    for segment in transcript:
        categories["sentenceBoundaries"].append(
            evidence_span(
                evidence_type="sentence_boundary",
                start_ms=max(0, segment["endMs"] - 1),
                end_ms=segment["endMs"],
                value={
                    "boundaryMs": segment["endMs"],
                    "basis": "asr_segment_end",
                },
                confidence=float(segment["confidence"]),
                source=_source(
                    adapter="semantic_director",
                    mode="derived_from_provider",
                    input_sha256=input_sha256,
                    detail="sentence boundary inherited from source-bound ASR segment end",
                ),
                duration_ms=duration_ms,
            )
        )
        categories["audioEnergy"].append(
            evidence_span(
                evidence_type="audio_energy",
                start_ms=segment["startMs"],
                end_ms=segment["endMs"],
                value={
                    "signalType": "speech",
                    "energy": float(
                        segment["value"].get("speechEnergy", 0.7)
                    ),
                },
                confidence=float(segment["confidence"]) * 0.9,
                source=_source(
                    adapter="semantic_director",
                    mode="derived_from_provider",
                    input_sha256=input_sha256,
                    detail="speech-presence evidence derived from source-bound ASR span",
                ),
                duration_ms=duration_ms,
            )
        )

    categories["semanticEvents"].extend(
        _derived_semantic_events(
            categories,
            duration_ms=duration_ms,
            input_sha=input_sha256,
        )
    )
    for category in categories:
        categories[category] = sorted(
            categories[category],
            key=lambda item: (
                item["startMs"],
                item["endMs"],
                item["evidenceDigest"],
            ),
        )
    present = {
        category
        for category, values in categories.items()
        if values
    }
    unavailable = {
        item
        for item in unavailable
        if item not in present
    }
    result = {
        "contractVersion": SEMANTIC_ANALYSIS_VERSION,
        "source": {
            "sha256": input_sha256,
            "durationMs": duration_ms,
            "width": width,
            "height": height,
            "fps": fps,
            "hasAudio": has_audio,
        },
        "briefDigest": reels.sha256_text(brief),
        "evidence": categories,
        "adapters": results,
        "unavailableEvidence": sorted(unavailable),
        "claim": {
            "semanticCompleteness": (
                "partial"
                if unavailable
                else "adapter_evidence_complete_for_configured_categories"
            ),
            "humanLevelQuality": HUMAN_LEVEL_STATE,
            "syntheticFixturesMayProveHumanLevel": False,
        },
    }
    result["analysisDigest"] = reels.sha256_json(result)
    return result


def _coverage(
    evidence: Sequence[Mapping[str, Any]],
    duration_ms: int,
) -> float:
    intervals = sorted(
        (int(item["startMs"]), int(item["endMs"]))
        for item in evidence
    )
    covered = 0
    cursor = 0
    for start, end in intervals:
        start = max(start, cursor)
        if end > start:
            covered += end - start
            cursor = max(cursor, end)
    return min(1.0, covered / max(1, duration_ms))


def select_editorial_mode(
    analysis: Mapping[str, Any],
    *,
    override: str | None = None,
) -> dict[str, Any]:
    if analysis.get("contractVersion") != SEMANTIC_ANALYSIS_VERSION:
        raise SemanticDirectorError("semantic analysis contract mismatch")
    duration_ms = int(analysis["source"]["durationMs"])
    evidence = analysis["evidence"]
    transcript_coverage = _coverage(
        evidence["transcriptSegments"],
        duration_ms,
    )
    subject_coverage = _coverage(
        evidence["visualSubjects"],
        duration_ms,
    )
    shots_per_10s = (
        len(evidence["shotBoundaries"])
        / max(duration_ms / 10000.0, 0.001)
    )
    motion_values = [
        float(item["value"].get("normalizedEnergy", 0.0))
        for item in evidence["motionEnergy"]
    ]
    motion_mean = (
        sum(motion_values) / len(motion_values)
        if motion_values
        else None
    )
    object_kinds = {
        str(item["value"].get("kind", "")).lower()
        for item in evidence["importantObjects"]
    }
    event_names = {
        str(item["value"].get("event", ""))
        for item in evidence["semanticEvents"]
    }

    scores = {
        "clean_podcast": 0.20,
        "aggressive_shortform": 0.15,
        "cinematic_minimal": 0.10,
        "hybrid": 0.10,
    }
    rationale: dict[str, list[str]] = {
        key: [] for key in scores
    }
    if transcript_coverage >= 0.45:
        scores["clean_podcast"] += 0.35
        rationale["clean_podcast"].append(
            "source-bound transcript covers substantial duration"
        )
    if subject_coverage >= 0.45:
        scores["clean_podcast"] += 0.25
        rationale["clean_podcast"].append(
            "tracked person/face subject is persistent"
        )
    if {"product", "screen", "device", "interface"} & object_kinds:
        scores["hybrid"] += 0.50
        rationale["hybrid"].append(
            "important product/screen interaction evidence requires continuity plus emphasis"
        )
    if "proof_demo" in event_names:
        scores["hybrid"] += 0.25
        scores["aggressive_shortform"] += 0.15
        rationale["hybrid"].append("proof/demo semantic event is present")
    if "punchline_payoff" in event_names:
        scores["aggressive_shortform"] += 0.45
        rationale["aggressive_shortform"].append(
            "punchline/payoff event supports tighter emphasis"
        )
    if shots_per_10s >= 4.0 and transcript_coverage < 0.35:
        scores["cinematic_minimal"] += 0.55
        rationale["cinematic_minimal"].append(
            "high shot density with limited transcript evidence"
        )
    if motion_mean is not None and motion_mean >= 0.50:
        scores["cinematic_minimal"] += 0.15
        rationale["cinematic_minimal"].append(
            "measured visual-energy proxy is elevated"
        )
    if (
        shots_per_10s <= 1.0
        and (motion_mean is None or motion_mean <= 0.20)
    ):
        scores["clean_podcast"] += 0.25
        rationale["clean_podcast"].append(
            "low shot/motion energy favors restrained editing"
        )

    chosen = sorted(
        scores,
        key=lambda mode: (-scores[mode], mode),
    )[0]
    evidence_count = sum(
        len(values) for values in evidence.values()
    )
    unavailable = analysis.get("unavailableEvidence", [])
    if evidence_count <= 2:
        confidence = 0.30
        rationale[chosen].append(
            "semantic provider evidence is sparse; conservative fallback"
        )
    else:
        top_scores = sorted(scores.values(), reverse=True)
        margin = top_scores[0] - top_scores[1]
        availability = max(
            0.0,
            1.0 - min(1.0, len(unavailable) / 8.0),
        )
        confidence = min(
            0.92,
            0.45 + margin * 0.55 + availability * 0.20,
        )
    rounded_scores = {
        key: round(value, 4) for key, value in scores.items()
    }
    source_features = {
        "durationMs": duration_ms,
        "transcriptCoverage": round(transcript_coverage, 4),
        "subjectCoverage": round(subject_coverage, 4),
        "shotsPer10s": round(shots_per_10s, 4),
        "motionMean": (
            round(motion_mean, 4)
            if motion_mean is not None
            else None
        ),
        "sourceAspectRatio": round(
            float(analysis["source"]["width"])
            / max(1.0, float(analysis["source"]["height"])),
            4,
        ),
        "objectKinds": sorted(item for item in object_kinds if item),
        "semanticEvents": sorted(item for item in event_names if item),
        "evidenceCount": evidence_count,
        "unavailableEvidence": sorted(unavailable),
    }
    rejected = [
        {
            "mode": mode,
            "score": rounded_scores[mode],
            "scoreDeltaFromSelected": round(
                rounded_scores[chosen] - rounded_scores[mode],
                4,
            ),
            "supportingRationale": rationale[mode],
        }
        for mode in sorted(scores)
        if mode != chosen
    ]
    auto = {
        "mode": chosen,
        "scores": rounded_scores,
        "rationale": rationale[chosen],
        "confidence": round(confidence, 4),
        "sourceSemanticFeatures": source_features,
        "rejectedAlternatives": rejected,
    }

    normalized_override = override
    if normalized_override in {None, "", "auto"}:
        effective = chosen
        override_applied = False
    else:
        mapping = {
            "clean": "clean_podcast",
            "aggressive": "aggressive_shortform",
            "cinematic": "cinematic_minimal",
            "hybrid": "hybrid",
            **{mode: mode for mode in EDITORIAL_MODES},
        }
        if normalized_override not in mapping:
            raise SemanticDirectorError(
                "unsupported editorial style override"
            )
        effective = mapping[normalized_override]
        override_applied = True
    disagreement = (
        override_applied
        and effective != chosen
        and confidence >= 0.55
    )
    decision = {
        "autoDirector": auto,
        "effectiveMode": effective,
        "override": {
            "requested": normalized_override,
            "applied": override_applied,
            "materialDisagreement": disagreement,
            "explanation": (
                "operator override wins despite evidence-based auto-director disagreement"
                if disagreement
                else (
                    "operator override wins"
                    if override_applied
                    else "no operator override"
                )
            ),
        },
        "mediaBaseStyle": (
            "clean_podcast"
            if effective == "hybrid"
            else effective
        ),
        "selectionBasis": {
            "sourceBound": True,
            "analysisDigest": analysis["analysisDigest"],
            "sourceSha256": analysis["source"]["sha256"],
            "humanLevelQuality": HUMAN_LEVEL_STATE,
        },
    }
    decision["decisionDigest"] = reels.sha256_json(decision)
    return decision


def _merge_spans(
    spans: Sequence[tuple[int, int]],
) -> list[dict[str, int]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged: list[list[int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1] + 100:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [
        {"startMs": start, "endMs": end}
        for start, end in merged
    ]


def generate_edit_directives(
    analysis: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = analysis["evidence"]
    duration_ms = int(analysis["source"]["durationMs"])
    input_sha = str(analysis["source"]["sha256"])
    semantic_events = evidence["semanticEvents"]
    preserve = []
    continuity = []
    for item in evidence["importantObjects"]:
        kind = str(item["value"].get("kind", "")).lower()
        if kind in {"product", "screen", "device", "interface"}:
            preserve.append((item["startMs"], item["endMs"]))
            continuity.append((item["startMs"], item["endMs"]))
    for item in semantic_events:
        event = item["value"].get("event")
        if event in {"proof_demo", "punchline_payoff"}:
            preserve.append((item["startMs"], item["endMs"]))
        if event == "proof_demo":
            continuity.append((item["startMs"], item["endMs"]))
    low_info = [
        (item["startMs"], item["endMs"])
        for item in semantic_events
        if item["value"].get("event") == "low_information"
    ]
    transcript = evidence["transcriptSegments"]
    sentence_boundaries = sorted(
        {
            int(item["value"].get("boundaryMs", item["endMs"]))
            for item in evidence["sentenceBoundaries"]
        }
    )
    caption_emphasis = []
    high_event_spans = [
        item
        for item in semantic_events
        if item["value"].get("event")
        in {"hook", "proof_demo", "punchline_payoff", "cta_candidate"}
        and float(item["confidence"]) >= 0.5
    ]
    for segment in transcript:
        if any(
            segment["startMs"] < event["endMs"]
            and segment["endMs"] > event["startMs"]
            for event in high_event_spans
        ):
            caption_emphasis.append(
                {
                    "startMs": segment["startMs"],
                    "endMs": segment["endMs"],
                    "text": segment["value"].get("text", ""),
                    "confidence": segment["confidence"],
                    "sourceEvidenceDigest": segment["evidenceDigest"],
                }
            )
    objects = {
        str(item["value"].get("label") or item["value"].get("kind") or "")
        for item in evidence["importantObjects"]
        if (
            item["value"].get("label")
            or item["value"].get("kind")
        )
    }
    proof_events = [
        item
        for item in semantic_events
        if item["value"].get("event") == "proof_demo"
    ]
    broll = {
        "allowed": bool(objects and proof_events),
        "requireSemanticMatch": True,
        "relevantConcepts": sorted(objects),
        "rationale": (
            "B-roll may be used only if an available asset semantically matches "
            "the source-bound proof/demo concepts"
            if objects and proof_events
            else "no source-bound proof/object evidence supports B-roll selection"
        ),
    }
    cta_events = [
        item
        for item in semantic_events
        if item["value"].get("event") == "cta_candidate"
        and float(item["confidence"]) >= 0.5
    ]
    payoff_events = [
        item
        for item in semantic_events
        if item["value"].get("event") == "punchline_payoff"
        and float(item["confidence"]) >= 0.5
    ]
    hook_events = [
        item
        for item in semantic_events
        if item["value"].get("event") == "hook"
    ]
    saliency = []
    for item in evidence["visualSubjects"]:
        box = item["value"].get("box")
        if (
            isinstance(box, Mapping)
            and all(
                isinstance(box.get(key), (int, float))
                for key in ("x", "y", "width", "height")
            )
        ):
            center_x = float(box["x"]) + float(box["width"]) / 2.0
            center_y = float(box["y"]) + float(box["height"]) / 2.0
            saliency.append(
                {
                    "startMs": item["startMs"],
                    "endMs": item["endMs"],
                    "centerX": round(max(0.0, min(1.0, center_x)), 4),
                    "centerY": round(max(0.0, min(1.0, center_y)), 4),
                    "confidence": item["confidence"],
                }
            )
    silence_ranges = [
        {
            "startMs": item["startMs"],
            "endMs": item["endMs"],
        }
        for item in evidence["audioEnergy"]
        if item["value"].get("signalType") == "silence"
        and item["endMs"] - item["startMs"] >= 260
    ]
    media_hints = {
        "sentenceBoundariesMs": sentence_boundaries,
        "beatMarkersMs": sorted({
            int(item["value"].get("boundaryMs", item["startMs"]))
            for item in evidence["shotBoundaries"]
        }),
        "silenceRanges": silence_ranges,
        "saliency": saliency,
        "captionTokens": [
            {
                "id": "semantic-" + reels.sha256_json(item)[:12],
                "text": str(item["text"])[:80],
                "startMs": item["startMs"],
                "endMs": item["endMs"],
                "emphasis": True,
            }
            for item in caption_emphasis
            if item["text"]
        ],
    }
    directives = {
        "preserveImportantReveals": _merge_spans(preserve),
        "avoidMidSentenceCuts": {
            "enabled": bool(sentence_boundaries),
            "sentenceBoundariesMs": sentence_boundaries,
            "exceptionPolicy": (
                "cut mid-sentence only when an explicit source-bound hook/payoff "
                "event justifies it and record that rationale"
            ),
        },
        "compressLowInformationSpans": _merge_spans(low_info),
        "strengthenHook": {
            "windowStartMs": 0,
            "windowEndMs": min(3000, duration_ms),
            "supported": any(
                float(item["confidence"]) >= 0.5
                for item in hook_events
            ),
            "rationale": (
                "source-bound semantic hook evidence available"
                if any(
                    float(item["confidence"]) >= 0.5
                    for item in hook_events
                )
                else "only structural opening candidate available; do not claim semantic hook quality"
            ),
        },
        "payoffVisualEmphasis": [
            {
                "startMs": item["startMs"],
                "endMs": item["endMs"],
                "sourceEvidenceDigest": item["evidenceDigest"],
            }
            for item in payoff_events
        ],
        "broll": broll,
        "captionEmphasis": caption_emphasis,
        "continuityPreserve": _merge_spans(continuity),
        "loop": {
            "proposed": bool(payoff_events),
            "reason": (
                "source-bound payoff evidence can support a loop"
                if payoff_events
                else "no source-bound payoff evidence supports a loop"
            ),
        },
        "cta": {
            "proposed": bool(cta_events),
            "moments": [
                {
                    "startMs": item["startMs"],
                    "endMs": item["endMs"],
                    "sourceEvidenceDigest": item["evidenceDigest"],
                }
                for item in cta_events
            ],
            "reason": (
                "source-bound CTA candidate evidence exists"
                if cta_events
                else "no source-bound CTA candidate evidence"
            ),
        },
        "mediaHints": media_hints,
        "mediaBaseStyle": decision["mediaBaseStyle"],
    }
    directives["directivesDigest"] = reels.sha256_json(directives)
    return directives


def build_director_report(
    analysis: Mapping[str, Any],
    decision: Mapping[str, Any],
    directives: Mapping[str, Any],
) -> dict[str, Any]:
    events = [
        {
            "event": item["value"].get("event"),
            "startMs": item["startMs"],
            "endMs": item["endMs"],
            "confidence": item["confidence"],
            "evidenceDigest": item["evidenceDigest"],
        }
        for item in analysis["evidence"]["semanticEvents"]
    ]
    report = {
        "contractVersion": DIRECTOR_REPORT_VERSION,
        "readiness": READINESS_STATE,
        "humanLevelQuality": HUMAN_LEVEL_STATE,
        "analysisDigest": analysis["analysisDigest"],
        "semanticTimeline": _clone(analysis["evidence"]),
        "chosenStyle": _clone(decision),
        "keyMoments": events,
        "cutsToPreserve": directives["preserveImportantReveals"],
        "spansToCompress": directives["compressLowInformationSpans"],
        "continuityPreserve": directives["continuityPreserve"],
        "broll": directives["broll"],
        "captionEmphasis": directives["captionEmphasis"],
        "loop": directives["loop"],
        "cta": directives["cta"],
        "confidence": decision["autoDirector"]["confidence"],
        "unavailableEvidence": analysis["unavailableEvidence"],
        "claims": {
            "humanLevelQualityClaimed": False,
            "syntheticFixtureQualityClaimed": False,
            "missingEvidenceIsFabricated": False,
        },
    }
    report["reportDigest"] = reels.sha256_json(report)
    return report
