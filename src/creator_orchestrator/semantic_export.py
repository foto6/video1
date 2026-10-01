from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import semantic_director as director

CONTRACT_VERSION = "creator.semantic_export.v1"
REPOSITORY = "foto6/video1"
BENCHMARK_PROTOCOL = "boss.human_editing_gate.v1"
BENCHMARK_REPOSITORY = "foto6/boss"
BENCHMARK_HEAD = "e0763bebf2aad9402f8de8c60edb1b9eb8c4be8e"

REQUIRED_KEYS = (
    "contract_version",
    "repository",
    "commit_sha",
    "source_id",
    "source_sha256",
    "brief_digest",
    "analysis_contract",
    "director_report_contract",
    "semantic_timeline",
    "unavailable_evidence",
    "auto_style",
    "effective_style",
    "style_confidence",
    "edit_directives",
    "analysis_digest",
    "directives_digest",
    "generation_mode",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class SemanticExportError(ValueError):
    pass


def current_creator_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SemanticExportError(
            "cannot resolve exact Creator commit SHA"
        ) from exc
    value = result.stdout.strip()
    if result.returncode != 0 or not _SHA40.fullmatch(value):
        raise SemanticExportError(
            "cannot resolve exact Creator commit SHA"
        )
    return value


def default_source_id(source_sha256: str) -> str:
    if not _SHA64.fullmatch(source_sha256):
        raise SemanticExportError("source_sha256 must be 64 lowercase hex")
    return "creator-source-" + source_sha256[:20]


def generation_mode(provider_identity: Mapping[str, Any]) -> str:
    if provider_identity.get("effective") == "google_gemini":
        return "gemini_native_video"
    if provider_identity.get("effective") == "deterministic_local":
        if provider_identity.get("fallback") is True:
            return "deterministic_local_fallback"
        return "deterministic_local"
    raise SemanticExportError(
        "unsupported semantic provider identity for generation_mode"
    )


def _validate_timestamp_tree(
    value: Any,
    *,
    duration_ms: int,
    path: str = "semantic_timeline",
) -> None:
    if isinstance(value, Mapping):
        has_start = "startMs" in value
        has_end = "endMs" in value
        if has_start != has_end:
            raise SemanticExportError(
                f"{path} must carry startMs/endMs together"
            )
        if has_start:
            start = value["startMs"]
            end = value["endMs"]
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
            ):
                raise SemanticExportError(
                    f"{path} timestamps must be integer milliseconds"
                )
            if start < 0 or end <= start or end > duration_ms:
                raise SemanticExportError(
                    f"{path} timestamp range outside source duration"
                )
        for key, child in value.items():
            _validate_timestamp_tree(
                child,
                duration_ms=duration_ms,
                path=f"{path}.{key}",
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_timestamp_tree(
                child,
                duration_ms=duration_ms,
                path=f"{path}[{index}]",
            )


def validate_semantic_export(
    value: Mapping[str, Any],
    *,
    expected_commit_sha: str | None = None,
    expected_source_sha256: str | None = None,
    expected_brief_digest: str | None = None,
    expected_analysis_digest: str | None = None,
    expected_directives_digest: str | None = None,
    source_duration_ms: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED_KEYS):
        missing = [key for key in REQUIRED_KEYS if key not in value]
        extra = [key for key in value if key not in REQUIRED_KEYS]
        raise SemanticExportError(
            "semantic export keys must match canonical order/set exactly; "
            f"missing={missing}, extra={extra}"
        )
    if value["contract_version"] != CONTRACT_VERSION:
        raise SemanticExportError("semantic export contract_version mismatch")
    if value["repository"] != REPOSITORY:
        raise SemanticExportError("semantic export repository mismatch")
    commit_sha = value["commit_sha"]
    if not isinstance(commit_sha, str) or not _SHA40.fullmatch(commit_sha):
        raise SemanticExportError("commit_sha must be 40 lowercase hex")
    if expected_commit_sha is not None and commit_sha != expected_commit_sha:
        raise SemanticExportError("Creator commit binding mismatch")
    source_id = value["source_id"]
    if not isinstance(source_id, str) or not source_id.strip():
        raise SemanticExportError("source_id must be non-empty")
    source_sha = value["source_sha256"]
    brief_digest = value["brief_digest"]
    if not isinstance(source_sha, str) or not _SHA64.fullmatch(source_sha):
        raise SemanticExportError("source_sha256 must be 64 lowercase hex")
    if not isinstance(brief_digest, str) or not _SHA64.fullmatch(brief_digest):
        raise SemanticExportError("brief_digest must be 64 lowercase hex")
    if (
        expected_source_sha256 is not None
        and source_sha != expected_source_sha256
    ):
        raise SemanticExportError("source SHA binding mismatch")
    if (
        expected_brief_digest is not None
        and brief_digest != expected_brief_digest
    ):
        raise SemanticExportError("brief digest binding mismatch")
    if value["analysis_contract"] != director.SEMANTIC_ANALYSIS_VERSION:
        raise SemanticExportError("analysis_contract mismatch")
    if value["director_report_contract"] != director.DIRECTOR_REPORT_VERSION:
        raise SemanticExportError("director_report_contract mismatch")
    if not isinstance(value["semantic_timeline"], Mapping):
        raise SemanticExportError("semantic_timeline must be an object")
    _validate_timestamp_tree(
        value["semantic_timeline"],
        duration_ms=source_duration_ms,
    )
    unavailable = value["unavailable_evidence"]
    if not isinstance(unavailable, list) or not all(
        isinstance(item, str) and item for item in unavailable
    ):
        raise SemanticExportError(
            "unavailable_evidence must be an array of strings"
        )
    if unavailable != sorted(set(unavailable)):
        raise SemanticExportError(
            "unavailable_evidence must be sorted and unique"
        )
    for key in ("auto_style", "effective_style"):
        if not isinstance(value[key], str) or value[key] not in director.EDITORIAL_MODES:
            raise SemanticExportError(f"{key} is invalid")
    confidence = value["style_confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise SemanticExportError("style_confidence must be within 0..1")
    directives = value["edit_directives"]
    if not isinstance(directives, Mapping):
        raise SemanticExportError("edit_directives must be an object")
    analysis_digest = value["analysis_digest"]
    directives_digest = value["directives_digest"]
    for digest_name, digest in (
        ("analysis_digest", analysis_digest),
        ("directives_digest", directives_digest),
    ):
        if not isinstance(digest, str) or not _SHA64.fullmatch(digest):
            raise SemanticExportError(
                f"{digest_name} must be 64 lowercase hex"
            )
    if reels.sha256_json(directives) != directives_digest:
        raise SemanticExportError("directives_digest does not match edit_directives")
    if (
        expected_analysis_digest is not None
        and analysis_digest != expected_analysis_digest
    ):
        raise SemanticExportError("analysis digest binding mismatch")
    if (
        expected_directives_digest is not None
        and directives_digest != expected_directives_digest
    ):
        raise SemanticExportError("directives digest binding mismatch")
    mode = value["generation_mode"]
    if mode not in {
        "gemini_native_video",
        "deterministic_local",
        "deterministic_local_fallback",
    }:
        raise SemanticExportError("generation_mode is invalid")
    serialized = json.dumps(value, sort_keys=True).lower()
    if "human_ground_truth" in serialized or '"human_level": true' in serialized:
        raise SemanticExportError(
            "Creator semantic export must not label model/fixture evidence as human ground truth"
        )
    return json.loads(reels.canonical_json(value))


def build_semantic_export(
    *,
    commit_sha: str,
    source_id: str,
    source_sha256: str,
    source_duration_ms: int,
    brief_digest: str,
    semantic_analysis: Mapping[str, Any],
    director_report: Mapping[str, Any],
    style_decision: Mapping[str, Any],
    edit_directives: Mapping[str, Any],
    provider_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if semantic_analysis.get("source", {}).get("sha256") != source_sha256:
        raise SemanticExportError("semantic analysis source SHA mismatch")
    if semantic_analysis.get("source", {}).get("durationMs") != source_duration_ms:
        raise SemanticExportError("semantic analysis source duration mismatch")
    if semantic_analysis.get("briefDigest") != brief_digest:
        raise SemanticExportError("semantic analysis brief digest mismatch")
    if director_report.get("analysisDigest") != semantic_analysis.get(
        "analysisDigest"
    ):
        raise SemanticExportError("director report analysis binding mismatch")
    if style_decision.get("selectionBasis", {}).get(
        "analysisDigest"
    ) != semantic_analysis.get("analysisDigest"):
        raise SemanticExportError("style decision analysis binding mismatch")
    if edit_directives.get("directivesDigest") != reels.sha256_json(
        {
            key: item
            for key, item in edit_directives.items()
            if key != "directivesDigest"
        }
    ):
        raise SemanticExportError("edit directives digest mismatch")

    export = {
        "contract_version": CONTRACT_VERSION,
        "repository": REPOSITORY,
        "commit_sha": commit_sha,
        "source_id": source_id,
        "source_sha256": source_sha256,
        "brief_digest": brief_digest,
        "analysis_contract": semantic_analysis["contractVersion"],
        "director_report_contract": director_report["contractVersion"],
        "semantic_timeline": json.loads(
            reels.canonical_json(semantic_analysis["evidence"])
        ),
        "unavailable_evidence": sorted(
            set(semantic_analysis["unavailableEvidence"])
        ),
        "auto_style": style_decision["autoDirector"]["mode"],
        "effective_style": style_decision["effectiveMode"],
        "style_confidence": style_decision["autoDirector"]["confidence"],
        "edit_directives": {
            key: json.loads(reels.canonical_json(item))
            for key, item in edit_directives.items()
            if key != "directivesDigest"
        },
        "analysis_digest": semantic_analysis["analysisDigest"],
        "directives_digest": edit_directives["directivesDigest"],
        "generation_mode": generation_mode(provider_identity),
    }
    return validate_semantic_export(
        export,
        expected_commit_sha=commit_sha,
        expected_source_sha256=source_sha256,
        expected_brief_digest=brief_digest,
        expected_analysis_digest=semantic_analysis["analysisDigest"],
        expected_directives_digest=edit_directives["directivesDigest"],
        source_duration_ms=source_duration_ms,
    )
