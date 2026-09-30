from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

CREATOR_REELS_STATE_VERSION = "creator.autonomous_reels_state.v1"
CREATOR_REELS_PROFILE_VERSION = "creator.shortform_profile.v1"
MEDIA_R11_ENVELOPE_VERSION = "creator.media_r11_result_envelope.v1"
GROWTH_R10_ENVELOPE_VERSION = "creator.growth_r10_seed_envelope.v1"
GROWTH_NEXT_CYCLE_SEED_VERSION = "growth.reels_next_cycle_seed.v1"
GROWTH_PUBLISH_RESULT_VERSION = "growth.shortform_publish_result.v1"
GROWTH_METRIC_SNAPSHOT_VERSION = "growth.shortform_metric_snapshot.v1"
MEDIA_JOB_VERSION = "media.job.v1"
MEDIA_ARTIFACT_MANIFEST_VERSION = "media.artifact_manifest.v1"
RELEASE_AUTHORIZATION_VERSION = "release.authorization.v1"
GROWTH_HANDOFF_VERSION = "creator.growth_shortform_handoff.v1"
MEDIA_R11_REPOSITORY = "foto6/video2"
MEDIA_R11_BRANCH = "agent/media-r11-autonomous-reels-20261001"
MEDIA_R11_PREMILESTONE_HEAD = "2366b3820c2cbf429aa734f2e623689699e73003"
MEDIA_JOB_CONTRACT_PATH = "conformance/media.job.v1/consumer-manifest.json"
MEDIA_ARTIFACT_CONTRACT_PATH = "conformance/media.artifact_manifest.v1/manifest.json"
GROWTH_R10_REPOSITORY = "foto6/video3"
GROWTH_R10_BRANCH = "agent/growth-r10-autonomous-reels-20261001"
GROWTH_R10_CONTRACT_PATH = "growth_analytics/autonomous_reels.py"

REELS_STAGES = (
    "brief",
    "research_evidence",
    "idea_hook",
    "script",
    "asset_plan",
    "edit_request",
    "media_render",
    "critic_qa",
    "publish_queue",
    "publish_result",
    "analytics_handoff",
)
PLATFORMS = frozenset({"instagram_reels", "tiktok", "youtube_shorts"})
_SECRET_EXACT = {
    "authorization", "authorizationheader", "proxyauthorization",
    "password", "passwd", "secret", "clientsecret", "apikey", "token",
    "accesstoken", "refreshtoken", "privatekey", "cookie", "credential", "bearer",
}


class AutonomousReelsError(ValueError):
    pass


class StageOrderError(AutonomousReelsError):
    pass


class ContractValidationError(AutonomousReelsError):
    pass


class DependencyUnavailable(AutonomousReelsError):
    pass


class PublishGateError(AutonomousReelsError):
    pass


class PublishOutcomeUnknown(RuntimeError):
    pass


class InjectedCrash(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("value must be canonical JSON-compatible") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ContractValidationError(f"{label} fields must match exactly")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _sha64(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ContractValidationError(f"{field} must be lowercase SHA-256 hex")
    return value


def _git_sha(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ContractValidationError(f"{field} must be lowercase Git SHA-1 hex")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(f"{field} must be a positive integer")
    return value


def _parse_time(value: Any, field: str) -> datetime:
    text = _nonempty(value, field)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ContractValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ContractValidationError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _reject_secrets(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"non-string key at {path}")
            normalized = "".join(ch for ch in key.lower() if ch.isalnum())
            if normalized in _SECRET_EXACT:
                raise ContractValidationError(f"secret-like field {key!r} at {path}")
            _reject_secrets(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_secrets(nested, f"{path}[{index}]")


def canonical_reels_profile(
    *,
    caption: str,
    cta: str,
    hashtags: Sequence[str] = (),
) -> dict[str, Any]:
    _nonempty(caption, "caption")
    _nonempty(cta, "cta")
    tags = []
    for tag in hashtags:
        text = _nonempty(tag, "hashtag")
        if not text.startswith("#"):
            raise ContractValidationError("hashtags must begin with #")
        tags.append(text)
    material = {
        "contractVersion": CREATOR_REELS_PROFILE_VERSION,
        "canvas": {"width": 1080, "height": 1920, "aspectRatio": "9:16", "fps": 30},
        "durationSeconds": {"targetMin": 15.0, "targetMax": 60.0},
        "hookWindowSeconds": {"start": 0.0, "end": 3.0},
        "audio": {"sampleRateHz": 48000, "channels": 2, "loudnessTargetLufs": -14.0},
        "export": {
            "container": "mp4", "videoCodec": "h264", "audioCodec": "aac",
            "pixelFormat": "yuv420p", "fastStart": True,
        },
        "metadata": {
            "caption": caption,
            "cta": cta,
            "hashtags": tags,
            "platformTargets": ["instagram_reels", "tiktok", "youtube_shorts"],
            "safeAreaPolicy": "keep-critical-text-inside-center-80pct",
        },
    }
    material["profileDigest"] = sha256_json(material)
    return material


def validate_media_r11_envelope(
    payload: Mapping[str, Any],
    *,
    expected_producer_sha: str,
    expected_job_contract_blob_sha: str,
    expected_manifest_contract_blob_sha: str,
    expected_profile_digest: str,
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    _git_sha(expected_producer_sha, "expected_producer_sha")
    _git_sha(expected_job_contract_blob_sha, "expected_job_contract_blob_sha")
    _git_sha(expected_manifest_contract_blob_sha, "expected_manifest_contract_blob_sha")
    _sha64(expected_profile_digest, "expected_profile_digest")
    _exact(
        payload,
        {"contractVersion", "sourceClass", "source", "job", "artifactManifest", "preview", "timelineSpec"},
        "Media R11 envelope",
    )
    if payload["contractVersion"] != MEDIA_R11_ENVELOPE_VERSION:
        raise ContractValidationError("unsupported Media R11 envelope version")
    source_class = payload["sourceClass"]
    if source_class not in {"provider", "synthetic_fixture"}:
        raise ContractValidationError("unsupported Media sourceClass")
    if source_class == "synthetic_fixture" and not allow_synthetic_fixture:
        raise DependencyUnavailable("synthetic Media evidence is conformance-only")
    source = _exact(
        payload["source"],
        {
            "repository", "branch", "producerSha",
            "jobContractPath", "jobContractBlobSha",
            "artifactManifestContractPath", "artifactManifestContractBlobSha",
        },
        "Media source",
    )
    if (
        source["repository"] != MEDIA_R11_REPOSITORY
        or source["branch"] != MEDIA_R11_BRANCH
        or source["producerSha"] != expected_producer_sha
        or source["jobContractPath"] != MEDIA_JOB_CONTRACT_PATH
        or source["jobContractBlobSha"] != expected_job_contract_blob_sha
        or source["artifactManifestContractPath"] != MEDIA_ARTIFACT_CONTRACT_PATH
        or source["artifactManifestContractBlobSha"] != expected_manifest_contract_blob_sha
    ):
        raise ContractValidationError("Media producer/source binding mismatch")
    _git_sha(source["producerSha"], "Media producerSha")
    _git_sha(source["jobContractBlobSha"], "Media jobContractBlobSha")
    _git_sha(source["artifactManifestContractBlobSha"], "Media artifactManifestContractBlobSha")
    if source_class == "provider" and source["producerSha"] == MEDIA_R11_PREMILESTONE_HEAD:
        raise DependencyUnavailable("Media R11 producer branch has not advanced beyond its pre-milestone head")

    job = _exact(
        payload["job"],
        {"contractVersion", "jobId", "status", "idempotencyKey", "renderFingerprint"},
        "Media job",
    )
    if job["contractVersion"] != MEDIA_JOB_VERSION or job["status"] != "succeeded":
        raise ContractValidationError("Media job must be media.job.v1 succeeded")
    for field in ("jobId", "idempotencyKey"):
        _nonempty(job[field], f"Media job {field}")
    _sha64(job["renderFingerprint"], "Media renderFingerprint")

    manifest = _exact(
        payload["artifactManifest"],
        {
            "contractVersion", "logicalJobId", "idempotencyKey", "renderFingerprint",
            "attemptToken", "validatedRequestDigest", "profileDigest", "content",
            "probeEvidence", "qaEvidence", "finalization", "timestamps",
        },
        "Media artifact manifest",
    )
    if manifest["contractVersion"] != MEDIA_ARTIFACT_MANIFEST_VERSION:
        raise ContractValidationError("unsupported Media artifact manifest")
    if (
        manifest["logicalJobId"] != job["jobId"]
        or manifest["idempotencyKey"] != job["idempotencyKey"]
        or manifest["renderFingerprint"] != job["renderFingerprint"]
        or manifest["profileDigest"] != expected_profile_digest
    ):
        raise ContractValidationError("Media job/manifest/profile binding mismatch")
    _nonempty(manifest["attemptToken"], "attemptToken")
    _sha64(manifest["validatedRequestDigest"], "validatedRequestDigest")
    _sha64(manifest["profileDigest"], "manifest profileDigest")
    content = _exact(manifest["content"], {"algorithm", "sha256", "size", "contentId"}, "Media content")
    if content["algorithm"] != "sha256":
        raise ContractValidationError("Media content algorithm must be sha256")
    digest = _sha64(content["sha256"], "Media content.sha256")
    _positive_int(content["size"], "Media content.size")
    if content["contentId"] != f"sha256:{digest}":
        raise ContractValidationError("Media contentId does not bind content sha256")
    for evidence_name in ("probeEvidence", "qaEvidence"):
        evidence = _exact(manifest[evidence_name], {"sha256", "value"} | ({"passed"} if evidence_name == "qaEvidence" else set()), evidence_name)
        _sha64(evidence["sha256"], f"{evidence_name}.sha256")
        if sha256_json(evidence["value"]) != evidence["sha256"]:
            raise ContractValidationError(f"{evidence_name} digest mismatch")
    if manifest["qaEvidence"]["passed"] is not True or manifest["qaEvidence"]["value"].get("passed") is not True:
        raise ContractValidationError("Media manifest requires passing QA evidence")
    probe = manifest["probeEvidence"]["value"]
    if (
        not isinstance(probe, Mapping)
        or probe.get("hasVideo") is not True
        or probe.get("width") != 1080
        or probe.get("height") != 1920
    ):
        raise ContractValidationError("Media probe must prove 1080x1920 video")
    duration_ms = probe.get("durationMs")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)) or not 15000 <= float(duration_ms) <= 60000:
        raise ContractValidationError("Media duration outside canonical 15-60s range")

    finalization = _exact(
        manifest["finalization"],
        {"method", "preparedSha256", "preparedSize", "preparedAtMs", "finalizedAtMs"},
        "Media finalization",
    )
    if finalization["method"] not in {"atomic_rename", "legacy_atomic_rename_verified"}:
        raise ContractValidationError("unsupported Media finalization")
    if finalization["preparedSha256"] != digest or finalization["preparedSize"] != content["size"]:
        raise ContractValidationError("Media finalization does not bind final content")
    _exact(manifest["timestamps"], {"jobCreatedAtMs", "manifestCommittedAtMs"}, "Media timestamps")

    preview = _exact(payload["preview"], {"sha256", "contentType"}, "Media preview")
    _sha64(preview["sha256"], "preview.sha256")
    if preview["contentType"] not in {"image/jpeg", "image/png", "video/mp4"}:
        raise ContractValidationError("unsupported preview content type")
    timeline = _exact(payload["timelineSpec"], {"sha256", "profileDigest", "editRequestDigest"}, "Media timeline spec")
    _sha64(timeline["sha256"], "timelineSpec.sha256")
    _sha64(timeline["editRequestDigest"], "timelineSpec.editRequestDigest")
    if timeline["profileDigest"] != expected_profile_digest:
        raise ContractValidationError("timeline profile digest mismatch")
    _reject_secrets(payload)
    return _clone(payload)


def validate_growth_r10_seed_envelope(
    payload: Mapping[str, Any],
    *,
    expected_producer_sha: str,
    expected_contract_blob_sha: str,
    current_cycle_id: str,
    expected_source_cycle_revision: int,
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    _exact(payload, {"contractVersion", "source", "seed"}, "Growth R10 envelope")
    if payload["contractVersion"] != GROWTH_R10_ENVELOPE_VERSION:
        raise ContractValidationError("unsupported Growth R10 envelope version")
    source = _exact(
        payload["source"],
        {"repository", "branch", "producerSha", "contractPath", "contractBlobSha"},
        "Growth source",
    )
    if (
        source["repository"] != GROWTH_R10_REPOSITORY
        or source["branch"] != GROWTH_R10_BRANCH
        or source["producerSha"] != expected_producer_sha
        or source["contractPath"] != GROWTH_R10_CONTRACT_PATH
        or source["contractBlobSha"] != expected_contract_blob_sha
    ):
        raise ContractValidationError("Growth producer/source binding mismatch")
    _git_sha(source["producerSha"], "Growth producerSha")
    _git_sha(source["contractBlobSha"], "Growth contractBlobSha")

    seed = _exact(
        payload["seed"],
        {
            "contract_version", "next_cycle_id", "cycle_revision", "source_class",
            "live_performance_claim_allowed", "creator_cycle_eligible", "evidence_state",
            "lineage", "evidence", "metrics", "recommendations", "authority",
            "interpretation", "idempotency_key", "seed_digest",
        },
        "Growth next-cycle seed",
    )
    if seed["contract_version"] != GROWTH_NEXT_CYCLE_SEED_VERSION:
        raise ContractValidationError("unsupported Growth next-cycle seed version")
    if seed["next_cycle_id"] != current_cycle_id:
        raise StageOrderError("Growth seed targets a different Creator cycle")
    if seed["cycle_revision"] != expected_source_cycle_revision:
        raise StageOrderError("stale or out-of-order Growth seed revision")

    source_class = seed["source_class"]
    if source_class == "synthetic_fixture":
        if seed["live_performance_claim_allowed"] is not False or seed["creator_cycle_eligible"] is not False:
            raise ContractValidationError("synthetic Growth seed cannot claim live eligibility")
        if not allow_synthetic_fixture:
            raise DependencyUnavailable("synthetic Growth seed is conformance-only")
    elif source_class == "platform_export":
        if seed["live_performance_claim_allowed"] is not True or seed["creator_cycle_eligible"] is not True:
            raise ContractValidationError("live Growth seed must preserve live source scope")
    else:
        raise ContractValidationError("unsupported Growth seed source_class")

    authority = seed["authority"]
    if (
        not isinstance(authority, Mapping)
        or authority.get("auto_publish") is not False
        or authority.get("external_mutation") is not False
        or authority.get("release_authorized") is not False
        or authority.get("publish_authorized") is not False
        or authority.get("requires_creator_release_authorization") is not True
    ):
        raise ContractValidationError("Growth seed authority boundary invalid")

    evidence = _exact(
        seed["evidence"],
        {"publish_result", "metric_snapshot", "decision_handoff"},
        "Growth seed evidence",
    )
    published = _exact(
        evidence["publish_result"],
        {
            "contract_version", "publish_result_id", "publish_result_digest",
            "source_class", "platform", "account_id", "post_id", "published_at",
            "captured_at", "cycle_revision", "artifact", "provenance",
        },
        "Growth embedded publish result",
    )
    if published["contract_version"] != GROWTH_PUBLISH_RESULT_VERSION:
        raise ContractValidationError("embedded Growth publish result version mismatch")
    if published["cycle_revision"] != seed["cycle_revision"]:
        raise StageOrderError("embedded publish result revision is stale")
    if published["source_class"] != source_class:
        raise ContractValidationError("embedded publish result source class mismatch")
    if published["platform"] not in PLATFORMS:
        raise ContractValidationError("embedded publish result platform unsupported")
    publish_artifact = _exact(
        published["artifact"],
        {
            "creative_artifact_id", "creative_artifact_digest", "media_artifact_id",
            "media_artifact_digest", "media_render_fingerprint", "media_duration_seconds",
        },
        "Growth embedded publish artifact",
    )
    for field in ("creative_artifact_id", "media_artifact_id", "media_render_fingerprint"):
        _nonempty(publish_artifact[field], f"publish artifact {field}")
    _sha64(publish_artifact["creative_artifact_digest"], "creative_artifact_digest")
    _sha64(publish_artifact["media_artifact_digest"], "media_artifact_digest")
    publish_provenance = _exact(
        published["provenance"],
        {"provider_receipt_digest", "fixture_source_sha256", "live_performance_claim_allowed"},
        "Growth embedded publish provenance",
    )
    if source_class == "synthetic_fixture":
        if (
            publish_provenance["provider_receipt_digest"] is not None
            or publish_provenance["live_performance_claim_allowed"] is not False
        ):
            raise ContractValidationError("synthetic embedded publish provenance invalid")
        _sha64(publish_provenance["fixture_source_sha256"], "fixture_source_sha256")
    else:
        _sha64(publish_provenance["provider_receipt_digest"], "provider_receipt_digest")
        if (
            publish_provenance["fixture_source_sha256"] is not None
            or publish_provenance["live_performance_claim_allowed"] is not True
        ):
            raise ContractValidationError("live embedded publish provenance invalid")
    publish_identity = {
        "platform": published["platform"],
        "account_id": published["account_id"],
        "post_id": published["post_id"],
        "cycle_revision": published["cycle_revision"],
        "media_artifact_digest": publish_artifact["media_artifact_digest"],
    }
    if published["publish_result_id"] != "spr1:" + sha256_json(publish_identity):
        raise ContractValidationError("embedded publish result identity mismatch")
    publish_digest = _sha64(published["publish_result_digest"], "publish_result_digest")
    publish_material = dict(published)
    publish_material.pop("publish_result_digest")
    if sha256_json(publish_material) != publish_digest:
        raise ContractValidationError("embedded publish result digest mismatch")

    snapshot = _exact(
        evidence["metric_snapshot"],
        {
            "account_id", "available_metrics", "contract_version", "cycle_revision",
            "denominators", "live_performance_claim_allowed", "normalization_sources",
            "normalized_metrics", "platform", "post_id", "provenance",
            "publish_result_digest", "publish_result_id", "raw_metrics",
            "selected_metrics_event_digest", "selected_metrics_event_id",
            "snapshot_digest", "source_class", "uncertainty", "window",
        },
        "Growth embedded metric snapshot",
    )
    if snapshot["contract_version"] != GROWTH_METRIC_SNAPSHOT_VERSION:
        raise ContractValidationError("embedded Growth metric snapshot version mismatch")
    if snapshot["cycle_revision"] != seed["cycle_revision"]:
        raise StageOrderError("embedded metric snapshot revision is stale")
    if snapshot["source_class"] != source_class:
        raise ContractValidationError("embedded metric snapshot source class mismatch")
    if snapshot["live_performance_claim_allowed"] is not seed["live_performance_claim_allowed"]:
        raise ContractValidationError("embedded metric snapshot live scope mismatch")
    for field in ("platform", "account_id", "post_id", "publish_result_id", "publish_result_digest"):
        expected = published[field] if field in published else None
        if snapshot[field] != expected:
            raise ContractValidationError(f"embedded metric snapshot {field} binding mismatch")
    _sha64(snapshot["selected_metrics_event_digest"], "selected_metrics_event_digest")
    _nonempty(snapshot["selected_metrics_event_id"], "selected_metrics_event_id")
    metric_window = _exact(snapshot["window"], {"start", "end"}, "metric snapshot window")
    _nonempty(metric_window["start"], "metric window start")
    _nonempty(metric_window["end"], "metric window end")
    snapshot_digest = _sha64(snapshot["snapshot_digest"], "metric snapshot digest")
    snapshot_material = dict(snapshot)
    snapshot_material.pop("snapshot_digest")
    if sha256_json(snapshot_material) != snapshot_digest:
        raise ContractValidationError("embedded metric snapshot digest mismatch")

    lineage = _exact(
        seed["lineage"],
        {
            "creative_artifact_id", "creative_artifact_digest", "media_artifact_id",
            "media_artifact_digest", "media_render_fingerprint", "media_duration_seconds",
            "publish_result_id", "publish_result_digest", "platform", "account_id",
            "post_id", "published_at", "metric_snapshot_digest", "metric_window", "decision",
        },
        "Growth seed lineage",
    )
    bindings = {
        "creative_artifact_id": publish_artifact["creative_artifact_id"],
        "creative_artifact_digest": publish_artifact["creative_artifact_digest"],
        "media_artifact_id": publish_artifact["media_artifact_id"],
        "media_artifact_digest": publish_artifact["media_artifact_digest"],
        "media_render_fingerprint": publish_artifact["media_render_fingerprint"],
        "media_duration_seconds": publish_artifact["media_duration_seconds"],
        "publish_result_id": published["publish_result_id"],
        "publish_result_digest": published["publish_result_digest"],
        "platform": published["platform"],
        "account_id": published["account_id"],
        "post_id": published["post_id"],
        "published_at": published["published_at"],
        "metric_snapshot_digest": snapshot["snapshot_digest"],
        "metric_window": snapshot["window"],
    }
    for field, expected in bindings.items():
        if lineage[field] != expected:
            raise ContractValidationError(f"Growth lineage {field} does not match embedded evidence")

    decision = lineage["decision"]
    if not isinstance(decision, Mapping):
        raise ContractValidationError("Growth decision reference missing")
    if decision.get("state") == "bound":
        handoff = evidence["decision_handoff"]
        if not isinstance(handoff, Mapping):
            raise ContractValidationError("bound Growth decision lacks embedded handoff")
        if decision.get("handoff_digest") != handoff.get("handoff_digest"):
            raise ContractValidationError("Growth decision handoff digest mismatch")
    elif decision.get("state") == "none":
        if evidence["decision_handoff"] is not None:
            raise ContractValidationError("unbound Growth decision contains embedded handoff")
    else:
        raise ContractValidationError("unsupported Growth decision reference state")

    metrics = _exact(
        seed["metrics"],
        {"normalized", "normalization_sources", "denominators", "uncertainty", "available_metrics"},
        "Growth seed metrics",
    )
    if (
        metrics["normalized"] != snapshot["normalized_metrics"]
        or metrics["normalization_sources"] != snapshot["normalization_sources"]
        or metrics["denominators"] != snapshot["denominators"]
        or metrics["uncertainty"] != snapshot["uncertainty"]
        or metrics["available_metrics"] != snapshot["available_metrics"]
    ):
        raise ContractValidationError("Growth seed metrics do not match embedded metric snapshot")

    expected_id = "grs1:" + sha256_json({
        "next_cycle_id": seed["next_cycle_id"],
        "cycle_revision": seed["cycle_revision"],
        "publish_result_digest": lineage["publish_result_digest"],
        "metric_snapshot_digest": lineage["metric_snapshot_digest"],
        "decision_handoff_digest": decision.get("handoff_digest"),
    })
    if seed["idempotency_key"] != expected_id:
        raise ContractValidationError("Growth seed idempotency identity mismatch")
    provided = _sha64(seed["seed_digest"], "Growth seed_digest")
    material = dict(seed)
    material.pop("seed_digest")
    if sha256_json(material) != provided:
        raise ContractValidationError("Growth seed digest mismatch")
    _reject_secrets(payload)
    return _clone(payload)


def _validate_release_authorization(value: Any, artifact_id: str, artifact_digest: str, provider: str, destination: str) -> dict[str, Any]:
    auth = _exact(
        value,
        {
            "contractVersion", "decisionId", "idempotencyKey", "requestId", "campaignId",
            "candidateId", "artifactId", "artifactHash", "lineageHash", "destinationScope",
            "decision", "authorizationId", "expiresAt", "decidedAt", "decisionSource", "approverRef",
        },
        "release authorization",
    )
    if auth["contractVersion"] != RELEASE_AUTHORIZATION_VERSION or auth["decision"] != "approved":
        raise PublishGateError("publishing requires approved release.authorization.v1")
    if auth["decisionSource"] != "external":
        raise PublishGateError("release authorization must be explicit external input")
    if auth["artifactId"] != artifact_id or auth["artifactHash"] != f"sha256:{artifact_digest}":
        raise PublishGateError("release authorization artifact binding mismatch")
    scope = _exact(auth["destinationScope"], {"provider", "destination", "action"}, "destinationScope")
    if scope != {"provider": provider, "destination": destination, "action": "release"}:
        raise PublishGateError("release authorization destination binding mismatch")
    for field in (
        "decisionId", "idempotencyKey", "requestId", "campaignId",
        "candidateId", "lineageHash", "authorizationId", "expiresAt",
        "decidedAt", "approverRef",
    ):
        _nonempty(auth[field], field)
    decided = _parse_time(auth["decidedAt"], "decidedAt")
    expires = _parse_time(auth["expiresAt"], "expiresAt")
    if expires <= decided:
        raise PublishGateError("release authorization must expire after decidedAt")
    return _clone(auth)


def _provider_receipt_digest(receipt: Mapping[str, Any]) -> str:
    material = dict(receipt)
    material.pop("providerReceiptDigest", None)
    return sha256_json(material)


class PublishProvider(Protocol):
    provider: str
    destination: str
    source_class: str
    recovery_supported: bool
    idempotent_submit: bool

    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None: ...
    def submit(self, intent: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass
class FakePublishProvider:
    provider: str = "instagram_reels"
    destination: str = "fixture-account"
    source_class: str = "synthetic_fixture"
    recovery_supported: bool = True
    idempotent_submit: bool = True
    fail_after_effect_once: bool = False

    def __post_init__(self) -> None:
        self._receipts: dict[str, dict[str, Any]] = {}
        self.calls = 0
        self.accepted_effects = 0

    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None:
        value = self._receipts.get(idempotency_key)
        return None if value is None else _clone(value)

    def submit(self, intent: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        key = intent["idempotencyKey"]
        existing = self._receipts.get(key)
        if existing is not None:
            return _clone(existing)
        self.accepted_effects += 1
        base = {
            "contractVersion": "creator.publish_provider_receipt.v1",
            "provider": self.provider,
            "destination": self.destination,
            "sourceClass": self.source_class,
            "intentId": intent["intentId"],
            "idempotencyKey": key,
            "artifactId": intent["artifactId"],
            "artifactDigest": intent["artifactDigest"],
            "accountId": self.destination,
            "postId": f"fixture-post-{sha256_text(key)[:12]}",
            "publishedAt": "2026-10-01T00:00:00Z",
            "capturedAt": "2026-10-01T00:00:05Z",
        }
        base["providerReceiptDigest"] = _provider_receipt_digest(base)
        self._receipts[key] = base
        if self.fail_after_effect_once:
            self.fail_after_effect_once = False
            raise PublishOutcomeUnknown("provider effect occurred but acknowledgement was lost")
        return _clone(base)


class AutonomousReelsLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        cycle_id: str,
        topic: str,
        cycle_revision: int,
        profile: Mapping[str, Any],
        media_producer_sha: str,
        media_job_contract_blob_sha: str,
        media_manifest_contract_blob_sha: str,
        growth_producer_sha: str,
        growth_contract_blob_sha: str,
        allow_synthetic_fixture: bool = False,
    ) -> None:
        self.path = Path(path)
        self.cycle_id = _nonempty(cycle_id, "cycle_id")
        self.topic = _nonempty(topic, "topic")
        if isinstance(cycle_revision, bool) or not isinstance(cycle_revision, int) or cycle_revision < 1:
            raise ContractValidationError("cycle_revision must be >= 1")
        self.cycle_revision = cycle_revision
        self.profile = _clone(profile)
        self.media_producer_sha = _git_sha(media_producer_sha, "media_producer_sha")
        self.media_job_contract_blob_sha = _git_sha(media_job_contract_blob_sha, "media_job_contract_blob_sha")
        self.media_manifest_contract_blob_sha = _git_sha(media_manifest_contract_blob_sha, "media_manifest_contract_blob_sha")
        self.growth_producer_sha = _git_sha(growth_producer_sha, "growth_producer_sha")
        self.growth_contract_blob_sha = _git_sha(growth_contract_blob_sha, "growth_contract_blob_sha")
        self.allow_synthetic_fixture = allow_synthetic_fixture
        self.events: list[dict[str, Any]] = []
        self.stage_records: dict[str, dict[str, Any]] = {}
        self.growth_consumed: dict[str, dict[str, Any]] = {}
        self.publish_prepared: dict[str, Any] | None = None
        self.publish_receipt: dict[str, Any] | None = None
        if self.path.exists():
            self._load()
        else:
            self._append("cycle_created", {
                "cycleId": self.cycle_id,
                "topic": self.topic,
                "cycleRevision": self.cycle_revision,
                "profile": self.profile,
                "dependencyPins": {
                    "mediaProducerSha": self.media_producer_sha,
                    "mediaJobContractBlobSha": self.media_job_contract_blob_sha,
                    "mediaManifestContractBlobSha": self.media_manifest_contract_blob_sha,
                    "growthProducerSha": self.growth_producer_sha,
                    "growthContractBlobSha": self.growth_contract_blob_sha,
                },
            })

    def _event(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "ledgerVersion": CREATOR_REELS_STATE_VERSION,
            "sequence": len(self.events) + 1,
            "eventType": event_type,
            "payload": _clone(payload),
        }
        body["eventDigest"] = sha256_json(body)
        return body

    def _append(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        _reject_secrets(payload)
        event = self._event(event_type, payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self._apply(event)
        return event

    def _load(self) -> None:
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractValidationError(f"invalid ledger JSON line {line_number}") from exc
            _exact(event, {"ledgerVersion", "sequence", "eventType", "payload", "eventDigest"}, "ledger event")
            if event["ledgerVersion"] != CREATOR_REELS_STATE_VERSION or event["sequence"] != len(self.events) + 1:
                raise ContractValidationError("ledger version/sequence invalid")
            material = dict(event)
            digest = material.pop("eventDigest")
            if digest != sha256_json(material):
                raise ContractValidationError("ledger event digest mismatch")
            self.events.append(event)
            self._apply(event)
        first = self.events[0]["payload"] if self.events else None
        if (
            not first
            or first["cycleId"] != self.cycle_id
            or first["topic"] != self.topic
            or first["cycleRevision"] != self.cycle_revision
            or first["profile"] != self.profile
        ):
            raise ContractValidationError("ledger identity/profile mismatch")
        pins = first["dependencyPins"]
        expected = {
            "mediaProducerSha": self.media_producer_sha,
            "mediaJobContractBlobSha": self.media_job_contract_blob_sha,
            "mediaManifestContractBlobSha": self.media_manifest_contract_blob_sha,
            "growthProducerSha": self.growth_producer_sha,
            "growthContractBlobSha": self.growth_contract_blob_sha,
        }
        if pins != expected:
            raise ContractValidationError("ledger dependency pin mismatch")

    def _apply(self, event: Mapping[str, Any]) -> None:
        event_type = event["eventType"]
        payload = event["payload"]
        if event_type == "cycle_created":
            if len(self.events) != 1:
                raise ContractValidationError("cycle_created must be first event")
            return
        if event_type == "stage_committed":
            stage = payload["stage"]
            existing = self.stage_records.get(stage)
            if existing is not None and existing != payload:
                raise ContractValidationError("conflicting duplicate stage record")
            self.stage_records[stage] = _clone(payload)
        elif event_type == "growth_seed_consumed":
            key = payload["idempotencyKey"]
            existing = self.growth_consumed.get(key)
            if existing is not None and existing != payload:
                raise ContractValidationError("conflicting duplicate Growth seed")
            self.growth_consumed[key] = _clone(payload)
        elif event_type == "publish_operation_prepared":
            if self.publish_prepared is not None and self.publish_prepared != payload:
                raise ContractValidationError("conflicting publish preparation")
            self.publish_prepared = _clone(payload)
        elif event_type == "publish_receipt_committed":
            if self.publish_receipt is not None and self.publish_receipt != payload:
                raise ContractValidationError("conflicting publish receipt")
            self.publish_receipt = _clone(payload)
        else:
            raise ContractValidationError(f"unknown ledger event type {event_type!r}")

    @property
    def next_stage(self) -> str | None:
        for stage in REELS_STAGES:
            if stage not in self.stage_records:
                return stage
        return None

    def consume_growth_seed(
        self,
        envelope: Mapping[str, Any],
        *,
        expected_source_cycle_revision: int,
        crash_after_commit: bool = False,
    ) -> str:
        parsed = validate_growth_r10_seed_envelope(
            envelope,
            expected_producer_sha=self.growth_producer_sha,
            expected_contract_blob_sha=self.growth_contract_blob_sha,
            current_cycle_id=self.cycle_id,
            expected_source_cycle_revision=expected_source_cycle_revision,
            allow_synthetic_fixture=self.allow_synthetic_fixture,
        )
        seed = parsed["seed"]
        key = seed["idempotency_key"]
        existing = self.growth_consumed.get(key)
        record = {
            "idempotencyKey": key,
            "seedDigest": seed["seed_digest"],
            "sourceCycleRevision": seed["cycle_revision"],
            "source": parsed["source"],
        }
        if existing is not None:
            if existing != record:
                raise ContractValidationError("Growth idempotency key changed payload")
            return "duplicate"
        self._append("growth_seed_consumed", record)
        if crash_after_commit:
            raise InjectedCrash("after_growth_seed_commit")
        return "accepted"

    def _media_record(self) -> Mapping[str, Any]:
        try:
            return self.stage_records["media_render"]["payload"]
        except KeyError as exc:
            raise StageOrderError("Media render has not completed") from exc

    def _validate_stage_payload(self, stage: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if stage == "brief":
            _exact(payload, {"goal", "topic", "audience"}, "brief")
            for field in ("goal", "topic", "audience"):
                _nonempty(payload[field], field)
        elif stage == "research_evidence":
            _exact(payload, {"items"}, "research_evidence")
            if not isinstance(payload["items"], list) or not payload["items"]:
                raise ContractValidationError("research evidence must be non-empty")
            for item in payload["items"]:
                _exact(item, {"evidenceId", "sourceUri", "sha256", "capturedAt"}, "research evidence item")
                _nonempty(item["evidenceId"], "evidenceId")
                _nonempty(item["sourceUri"], "sourceUri")
                _sha64(item["sha256"], "research sha256")
                _nonempty(item["capturedAt"], "capturedAt")
        elif stage == "idea_hook":
            _exact(payload, {"idea", "hook", "hookWindowSeconds"}, "idea_hook")
            _nonempty(payload["idea"], "idea")
            _nonempty(payload["hook"], "hook")
            if payload["hookWindowSeconds"] != self.profile["hookWindowSeconds"]:
                raise ContractValidationError("hook window must match canonical profile")
        elif stage == "script":
            _exact(payload, {"revision", "text", "sha256"}, "script")
            _positive_int(payload["revision"], "script revision")
            text = _nonempty(payload["text"], "script text")
            if payload["sha256"] != sha256_text(text):
                raise ContractValidationError("script digest mismatch")
        elif stage == "asset_plan":
            _exact(payload, {"assets"}, "asset_plan")
            if not isinstance(payload["assets"], list) or not payload["assets"]:
                raise ContractValidationError("asset plan must be non-empty")
            for item in payload["assets"]:
                _exact(item, {"assetId", "sourceUri", "sha256", "rightsRef"}, "asset")
                _nonempty(item["assetId"], "assetId")
                _nonempty(item["sourceUri"], "asset sourceUri")
                _sha64(item["sha256"], "asset sha256")
                _nonempty(item["rightsRef"], "rightsRef")
        elif stage == "edit_request":
            _exact(payload, {"voice", "music", "subtitles", "edit", "profileDigest"}, "edit_request")
            if payload["profileDigest"] != self.profile["profileDigest"]:
                raise ContractValidationError("edit request profile mismatch")
            if not isinstance(payload["voice"], Mapping) or not isinstance(payload["music"], Mapping):
                raise ContractValidationError("voice/music request must be objects")
            if not isinstance(payload["subtitles"], Mapping) or payload["subtitles"].get("enabled") is not True:
                raise ContractValidationError("subtitles must be explicitly enabled")
            if not isinstance(payload["edit"], Mapping):
                raise ContractValidationError("edit request must be declarative object")
        elif stage == "media_render":
            return validate_media_r11_envelope(
                payload,
                expected_producer_sha=self.media_producer_sha,
                expected_job_contract_blob_sha=self.media_job_contract_blob_sha,
                expected_manifest_contract_blob_sha=self.media_manifest_contract_blob_sha,
                expected_profile_digest=self.profile["profileDigest"],
                allow_synthetic_fixture=self.allow_synthetic_fixture,
            )
        elif stage == "critic_qa":
            _exact(payload, {"decision", "qaDigest", "checks"}, "critic_qa")
            if payload["decision"] != "pass":
                raise ContractValidationError("critic/QA must pass before publish")
            _sha64(payload["qaDigest"], "qaDigest")
            if (
                not isinstance(payload["checks"], list)
                or not payload["checks"]
                or not all(
                    isinstance(item, Mapping) and item.get("pass") is True
                    for item in payload["checks"]
                )
            ):
                raise ContractValidationError("critic/QA checks must all pass")
        elif stage == "publish_queue":
            _exact(payload, {"intentId", "idempotencyKey", "provider", "destination", "platform", "artifactId", "artifactDigest", "caption", "cta", "releaseAuthorization", "adapterState"}, "publish_queue")
            for field in ("intentId", "idempotencyKey", "provider", "destination", "artifactId", "caption", "cta"):
                _nonempty(payload[field], field)
            if payload["platform"] not in PLATFORMS or payload["provider"] != payload["platform"]:
                raise PublishGateError("publish platform/provider must be supported and identical")
            _sha64(payload["artifactDigest"], "artifactDigest")
            media = self._media_record()["artifactManifest"]
            if payload["artifactId"] != media["content"]["contentId"] or payload["artifactDigest"] != media["content"]["sha256"]:
                raise PublishGateError("publish intent is not bound to final Media artifact")
            state = _exact(payload["adapterState"], {"state", "provider", "destination", "recoverySupported", "idempotentSubmit", "evidenceDigest"}, "adapterState")
            if (
                state["state"] != "ready"
                or state["provider"] != payload["provider"]
                or state["destination"] != payload["destination"]
                or state["recoverySupported"] is not True
                or state["idempotentSubmit"] is not True
            ):
                raise PublishGateError("provider adapter is not ready/recoverable/idempotent")
            _sha64(state["evidenceDigest"], "adapterState.evidenceDigest")
            _validate_release_authorization(
                payload["releaseAuthorization"], payload["artifactId"], payload["artifactDigest"],
                payload["provider"], payload["destination"],
            )
        elif stage == "publish_result":
            _exact(payload, {"receipt"}, "publish_result")
            receipt = payload["receipt"]
            self._validate_provider_receipt(receipt, self.stage_records["publish_queue"]["payload"])
        elif stage == "analytics_handoff":
            _exact(payload, {"contractVersion", "publishResult", "handoffDigest"}, "analytics_handoff")
            if payload["contractVersion"] != GROWTH_HANDOFF_VERSION:
                raise ContractValidationError("unsupported analytics handoff")
            _sha64(payload["handoffDigest"], "handoffDigest")
            material = dict(payload)
            digest = material.pop("handoffDigest")
            if sha256_json(material) != digest:
                raise ContractValidationError("analytics handoff digest mismatch")
            if payload["publishResult"].get("contract_version") != GROWTH_PUBLISH_RESULT_VERSION:
                raise ContractValidationError("analytics handoff publish result version mismatch")
        else:
            raise StageOrderError(f"unsupported stage {stage!r}")
        _reject_secrets(payload)
        return _clone(payload)

    def commit_stage(
        self,
        stage: str,
        payload: Mapping[str, Any],
        *,
        provenance: Mapping[str, Any],
        crash_after_commit: bool = False,
    ) -> str:
        if stage not in REELS_STAGES:
            raise StageOrderError(f"unsupported stage {stage!r}")
        normalized_payload = self._validate_stage_payload(stage, payload)
        normalized_provenance = _clone(provenance)
        _exact(normalized_provenance, {"producer", "sourceClass", "sourceRef", "sha256"}, "provenance")
        _nonempty(normalized_provenance["producer"], "provenance.producer")
        _nonempty(normalized_provenance["sourceClass"], "provenance.sourceClass")
        _nonempty(normalized_provenance["sourceRef"], "provenance.sourceRef")
        _sha64(normalized_provenance["sha256"], "provenance.sha256")
        payload_digest = sha256_json(normalized_payload)
        record = {
            "stage": stage,
            "idempotencyKey": "crs1:" + sha256_text(
                f"{self.cycle_id}|{self.cycle_revision}|{stage}|{payload_digest}|{self.profile['profileDigest']}"
            ),
            "payloadDigest": payload_digest,
            "payload": normalized_payload,
            "provenance": normalized_provenance,
        }
        existing = self.stage_records.get(stage)
        if existing is not None:
            if existing != record:
                raise ContractValidationError(f"stage {stage} already committed with different bytes")
            return "duplicate"
        if self.next_stage != stage:
            raise StageOrderError(f"expected stage {self.next_stage!r}, got {stage!r}")
        self._append("stage_committed", record)
        if crash_after_commit:
            raise InjectedCrash(f"after_{stage}_commit")
        return "committed"

    def _validate_provider_receipt(self, receipt: Mapping[str, Any], intent: Mapping[str, Any]) -> dict[str, Any]:
        _exact(
            receipt,
            {
                "contractVersion", "provider", "destination", "sourceClass", "intentId",
                "idempotencyKey", "artifactId", "artifactDigest", "accountId", "postId",
                "publishedAt", "capturedAt", "providerReceiptDigest",
            },
            "provider receipt",
        )
        if receipt["contractVersion"] != "creator.publish_provider_receipt.v1":
            raise PublishGateError("unsupported provider receipt")
        if receipt["sourceClass"] not in {"provider_receipt", "synthetic_fixture"}:
            raise PublishGateError("unsupported provider receipt sourceClass")
        if receipt["sourceClass"] == "synthetic_fixture" and not self.allow_synthetic_fixture:
            raise PublishGateError("synthetic publish receipt is conformance-only")
        for field in ("provider", "destination", "intentId", "idempotencyKey", "artifactId", "accountId", "postId", "publishedAt", "capturedAt"):
            _nonempty(receipt[field], field)
        _sha64(receipt["artifactDigest"], "receipt artifactDigest")
        _sha64(receipt["providerReceiptDigest"], "providerReceiptDigest")
        for field in ("provider", "destination", "intentId", "idempotencyKey", "artifactId", "artifactDigest"):
            if receipt[field] != intent[field]:
                raise PublishGateError(f"provider receipt {field} binding mismatch")
        if _provider_receipt_digest(receipt) != receipt["providerReceiptDigest"]:
            raise PublishGateError("provider receipt digest mismatch")
        return _clone(receipt)

    def execute_publish(self, provider: PublishProvider, *, now: str) -> str:
        if "publish_queue" not in self.stage_records:
            raise StageOrderError("publish intent is not queued")
        if "publish_result" in self.stage_records:
            return "duplicate"
        intent = self.stage_records["publish_queue"]["payload"]
        authorization = _validate_release_authorization(
            intent["releaseAuthorization"],
            intent["artifactId"],
            intent["artifactDigest"],
            intent["provider"],
            intent["destination"],
        )
        if _parse_time(now, "now") >= _parse_time(authorization["expiresAt"], "expiresAt"):
            raise PublishGateError("release authorization expired before publish execution")
        if (
            provider.provider != intent["provider"]
            or provider.destination != intent["destination"]
            or provider.recovery_supported is not True
            or provider.idempotent_submit is not True
        ):
            raise PublishGateError("runtime provider adapter state does not match queued intent")
        prepared = {
            "intentId": intent["intentId"],
            "idempotencyKey": intent["idempotencyKey"],
            "provider": intent["provider"],
            "destination": intent["destination"],
            "artifactDigest": intent["artifactDigest"],
        }
        if self.publish_prepared is None:
            self._append("publish_operation_prepared", prepared)
        elif self.publish_prepared != prepared:
            raise PublishGateError("durable publish preparation changed")

        receipt = self.publish_receipt
        if receipt is None:
            recovered = provider.recover(intent["idempotencyKey"])
            if recovered is None:
                receipt = provider.submit(intent)
            else:
                receipt = recovered
            receipt = self._validate_provider_receipt(receipt, intent)
            self._append("publish_receipt_committed", receipt)
        else:
            receipt = self._validate_provider_receipt(receipt, intent)
        return self.commit_stage(
            "publish_result",
            {"receipt": receipt},
            provenance={
                "producer": receipt["provider"],
                "sourceClass": receipt["sourceClass"],
                "sourceRef": receipt["postId"],
                "sha256": receipt["providerReceiptDigest"],
            },
        )

    def build_growth_handoff(self) -> dict[str, Any]:
        if "publish_result" not in self.stage_records:
            raise StageOrderError("publish result is required before Growth handoff")
        receipt = self.stage_records["publish_result"]["payload"]["receipt"]
        media = self._media_record()
        manifest = media["artifactManifest"]
        script = self.stage_records["script"]["payload"]
        live = receipt["sourceClass"] == "provider_receipt"
        publish_result = {
            "contract_version": GROWTH_PUBLISH_RESULT_VERSION,
            "source_class": "platform_export" if live else "synthetic_fixture",
            "platform": receipt["provider"],
            "account_id": receipt["accountId"],
            "post_id": receipt["postId"],
            "published_at": receipt["publishedAt"],
            "captured_at": receipt["capturedAt"],
            "cycle_revision": self.cycle_revision,
            "artifact": {
                "creative_artifact_id": f"script-r{script['revision']}",
                "creative_artifact_digest": script["sha256"],
                "media_artifact_id": manifest["content"]["contentId"],
                "media_artifact_digest": manifest["content"]["sha256"],
                "media_render_fingerprint": manifest["renderFingerprint"],
                "media_duration_seconds": float(manifest["probeEvidence"]["value"]["durationMs"]) / 1000.0,
            },
            "provenance": {
                "provider_receipt_digest": receipt["providerReceiptDigest"] if live else None,
                "fixture_source_sha256": None if live else receipt["providerReceiptDigest"],
                "live_performance_claim_allowed": live,
            },
        }
        identity = {
            "platform": publish_result["platform"],
            "account_id": publish_result["account_id"],
            "post_id": publish_result["post_id"],
            "cycle_revision": publish_result["cycle_revision"],
            "media_artifact_digest": publish_result["artifact"]["media_artifact_digest"],
        }
        publish_result["publish_result_id"] = "spr1:" + sha256_json(identity)
        publish_result["publish_result_digest"] = sha256_json(publish_result)
        handoff = {"contractVersion": GROWTH_HANDOFF_VERSION, "publishResult": publish_result}
        handoff["handoffDigest"] = sha256_json(handoff)
        return handoff

    def snapshot(self) -> dict[str, Any]:
        return {
            "contractVersion": CREATOR_REELS_STATE_VERSION,
            "cycleId": self.cycle_id,
            "cycleRevision": self.cycle_revision,
            "topic": self.topic,
            "profileDigest": self.profile["profileDigest"],
            "nextStage": self.next_stage,
            "completedStages": [stage for stage in REELS_STAGES if stage in self.stage_records],
            "growthSeedCount": len(self.growth_consumed),
            "publishPrepared": self.publish_prepared is not None,
            "publishReceiptCommitted": self.publish_receipt is not None,
            "eventCount": len(self.events),
            "stateDigest": sha256_json(self.events),
        }
