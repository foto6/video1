from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from .publish_providers import (
    DurablePublishCoordinator,
    InstagramReelsMockProvider,
    TikTokMockProvider,
    YouTubeShortsMockProvider,
    build_growth_handoff as build_r12_growth_handoff,
    build_publish_request,
)

INTEGRATION_ACCEPTANCE_VERSION = "creator.integration_acceptance.r13.v1"
INTEGRATION_LEDGER_VERSION = "creator.integration_acceptance_ledger.v1"
GROWTH_R11_EVIDENCE_VERSION = "creator.growth_r11_provider_ingest_evidence.v1"
MEDIA_ACCEPTANCE_PIN_VERSION = "creator.media_r11_acceptance_pin.v1"
MEDIA_REQUEST_VERSION = "creator.media_r11_acceptance_request.v1"

CREATOR_R12_BASE_SHA = "3594a907bb0c16469f33909af102714bdecaaafd"

GROWTH_R11_PRODUCER_SHA = "c4ed94d3e76b75d36bf8cc8280f6937f455133a6"
GROWTH_R11_REPOSITORY = "foto6/video3"
GROWTH_R11_BRANCH = "agent/growth-r11-provider-ingest-20261001"
GROWTH_R11_MANIFEST_PATH = "conformance/growth.provider_metrics_ingest.v1/manifest.json"
GROWTH_R11_MANIFEST_BLOB_SHA = "8b47817cb344c4a1670d338fca351c1056e8ba6f"
GROWTH_R11_IMPLEMENTATION_PATH = "growth_analytics/provider_ingest.py"
GROWTH_R11_IMPLEMENTATION_BLOB_SHA = "3fde5ed6fbae9356cc232613a8a81ea442c74315"
GROWTH_R11_R10_CONTRACT_PATH = "conformance/growth.autonomous_reels.v1/contract.json"
GROWTH_R11_R10_CONTRACT_BLOB_SHA = "0a63ebece0fe8620a57e635143cc3ea16d095f59"
GROWTH_R10_PRODUCER_SHA = "7209a2a9033c4ced0690b8311e6f1661681e7ca2"
GROWTH_R10_IMPLEMENTATION_BLOB_SHA = "808ebeb3df424f480dea4a394174fcf7356849b8"

GROWTH_R11_FIXTURE_BLOBS = {
    "instagram_reels": "9c411453e66a59d0388a142a4b874348f4d0f1d8",
    "tiktok": "3e5fe2212ab8b120209bd73abf509bf9eab188b8",
    "youtube_shorts": "95bb85583cbed8e7d04d54d71c13d7b75fa53ef9",
}

MEDIA_OBSERVED_CANDIDATE = {
    "producerSha": "530e0ea43288840d2d66609ca2407640522df3f7",
    "conformanceManifestBlobSha": "07c38a048d23490b8e55924697650e9969bf089f",
    "creatorConsumerBlobSha": "8d979c9a8f59259c5092c20b0c48c153f41b64a8",
    "jobContractBlobSha": "96b252acae743f8fe059fd634ee320f92bd9c79c",
    "artifactManifestContractBlobSha": "42aed1ca4720cddd4a5e48af076bc73b663322b0",
    "exactHeadCiRunId": None,
    "exactHeadCiConclusion": None,
}
MEDIA_PREMILESTONE_SHA = reels.MEDIA_R11_PREMILESTONE_HEAD

CROSS_REPO_BOUNDARIES = (
    "creator_to_media_request",
    "media_to_creator_result",
    "creator_to_publish_provider",
    "publish_provider_to_creator_receipt",
    "creator_to_growth_handoff",
    "growth_r11_provider_metrics",
    "growth_to_creator_next_cycle_seed",
)

OPTIONAL_METRICS = (
    "average_watch_duration_seconds",
    "comments",
    "completed_views",
    "completion_rate",
    "follows",
    "impressions",
    "likes",
    "link_clicks",
    "retention_denominator_views",
    "retention_points",
    "saves",
    "shares",
    "views",
    "watch_time_seconds",
)

PLATFORM_FIXTURE_METRICS = {
    "instagram_reels": {
        "views": 1200,
        "watch_time_seconds": 18000.0,
        "average_watch_duration_seconds": 15.0,
        "likes": 120,
        "comments": 12,
        "shares": 30,
        "saves": 18,
        "follows": 7,
    },
    "tiktok": {
        "views": 2400,
        "watch_time_seconds": 28800.0,
        "average_watch_duration_seconds": 12.0,
        "completion_rate": 0.31,
        "likes": 210,
        "comments": 19,
        "shares": 44,
    },
    "youtube_shorts": {
        "views": 3600,
        "watch_time_seconds": 43200.0,
        "average_watch_duration_seconds": 12.0,
        "likes": 330,
        "comments": 27,
        "shares": 51,
        "follows": 11,
    },
}


class IntegrationAcceptanceError(ValueError):
    pass


class BoundaryConflict(IntegrationAcceptanceError):
    pass


class BoundaryCrash(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaAcceptancePin:
    producer_sha: str
    job_contract_blob_sha: str
    artifact_manifest_contract_blob_sha: str
    conformance_manifest_blob_sha: str
    creator_consumer_blob_sha: str
    ci_run_id: str
    ci_conclusion: str

    def validate(self) -> "MediaAcceptancePin":
        for value, name in (
            (self.producer_sha, "producer_sha"),
            (self.job_contract_blob_sha, "job_contract_blob_sha"),
            (self.artifact_manifest_contract_blob_sha, "artifact_manifest_contract_blob_sha"),
            (self.conformance_manifest_blob_sha, "conformance_manifest_blob_sha"),
            (self.creator_consumer_blob_sha, "creator_consumer_blob_sha"),
        ):
            reels._git_sha(value, name)
        reels._nonempty(self.ci_run_id, "ci_run_id")
        if self.producer_sha == MEDIA_PREMILESTONE_SHA:
            raise IntegrationAcceptanceError("Media producer is still the R11 pre-milestone head")
        if self.ci_conclusion != "success":
            raise IntegrationAcceptanceError("Media exact-head CI is not successful")
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": MEDIA_ACCEPTANCE_PIN_VERSION,
            "repository": reels.MEDIA_R11_REPOSITORY,
            "branch": reels.MEDIA_R11_BRANCH,
            "producerSha": self.producer_sha,
            "jobContractPath": reels.MEDIA_JOB_CONTRACT_PATH,
            "jobContractBlobSha": self.job_contract_blob_sha,
            "artifactManifestContractPath": reels.MEDIA_ARTIFACT_CONTRACT_PATH,
            "artifactManifestContractBlobSha": self.artifact_manifest_contract_blob_sha,
            "shortformConformancePath": "conformance/media.shortform_editor.r11.v1/manifest.json",
            "shortformConformanceBlobSha": self.conformance_manifest_blob_sha,
            "creatorConsumerPath": "conformance/media.shortform_editor.r11.v1/fixtures/creator-consumer.json",
            "creatorConsumerBlobSha": self.creator_consumer_blob_sha,
            "ciRunId": self.ci_run_id,
            "ciConclusion": self.ci_conclusion,
        }


def growth_r11_source_pin() -> dict[str, Any]:
    return {
        "repository": GROWTH_R11_REPOSITORY,
        "branch": GROWTH_R11_BRANCH,
        "producerSha": GROWTH_R11_PRODUCER_SHA,
        "manifestPath": GROWTH_R11_MANIFEST_PATH,
        "manifestBlobSha": GROWTH_R11_MANIFEST_BLOB_SHA,
        "implementationPath": GROWTH_R11_IMPLEMENTATION_PATH,
        "implementationBlobSha": GROWTH_R11_IMPLEMENTATION_BLOB_SHA,
        "r10ContractPath": GROWTH_R11_R10_CONTRACT_PATH,
        "r10ContractBlobSha": GROWTH_R11_R10_CONTRACT_BLOB_SHA,
        "normalizedOutputContract": "growth.shortform_platform_metrics.v1",
        "adapterContract": "growth.provider_metrics_adapter.v1",
        "providerLedgerContract": "growth.provider_metrics_ingest_ledger.v1",
        "readOnly": True,
    }


def readiness_report(media_pin: MediaAcceptancePin | None) -> dict[str, Any]:
    media_gate: dict[str, Any]
    if media_pin is None:
        media_gate = {
            "state": "BLOCKED_MEDIA",
            "reason": "no accepted exact Media R11 producer pin with successful exact-head CI",
            "acceptedPin": None,
            "observedCandidate": dict(MEDIA_OBSERVED_CANDIDATE),
        }
        overall = "BLOCKED_MEDIA"
    else:
        try:
            media_pin.validate()
        except IntegrationAcceptanceError as exc:
            media_gate = {
                "state": "BLOCKED_MEDIA",
                "reason": str(exc),
                "acceptedPin": None,
                "observedCandidate": dict(MEDIA_OBSERVED_CANDIDATE),
            }
            overall = "BLOCKED_MEDIA"
        else:
            media_gate = {
                "state": "GREEN_FOR_SYNTHETIC_ACCEPTANCE",
                "reason": "caller supplied exact compatible Media producer/contract/CI evidence",
                "acceptedPin": media_pin.as_dict(),
                "observedCandidate": dict(MEDIA_OBSERVED_CANDIDATE),
            }
            overall = "SYNTHETIC_ACCEPTANCE_READY"
    report = {
        "reportVersion": INTEGRATION_ACCEPTANCE_VERSION,
        "overall": overall,
        "gates": {
            "creatorR11": {
                "state": "GREEN",
                "baselineSha": CREATOR_R12_BASE_SHA,
                "mediaFailClosedPreserved": True,
            },
            "creatorR12": {
                "state": "GREEN",
                "producerSha": CREATOR_R12_BASE_SHA,
                "publishProviderContract": "creator.publish_provider.v1",
            },
            "growthR11": {
                "state": "GREEN",
                "source": growth_r11_source_pin(),
                "fixtureBlobShas": dict(GROWTH_R11_FIXTURE_BLOBS),
                "syntheticMayClaimLivePerformance": False,
            },
            "mediaR11": media_gate,
        },
    }
    report["reportDigest"] = reels.sha256_json(report)
    return report


class IntegrationAcceptanceLedger:
    def __init__(self, path: str | os.PathLike[str], *, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = reels._nonempty(run_id, "run_id")
        self.events: list[dict[str, Any]] = []
        self.boundaries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()
        else:
            self._append("run_created", {"runId": self.run_id})

    def _event(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "ledgerVersion": INTEGRATION_LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventType": event_type,
            "payload": json.loads(reels.canonical_json(payload)),
        }
        body["eventDigest"] = reels.sha256_json(body)
        return body

    def _append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        reels._reject_secrets(payload)
        event = self._event(event_type, payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self._apply(event)

    def _apply(self, event: Mapping[str, Any]) -> None:
        event_type = event["eventType"]
        payload = event["payload"]
        if event_type == "run_created":
            if len(self.events) != 1 or payload != {"runId": self.run_id}:
                raise BoundaryConflict("acceptance run identity changed")
            return
        if event_type != "boundary_committed":
            raise BoundaryConflict(f"unknown acceptance event {event_type!r}")
        boundary = payload["boundary"]
        existing = self.boundaries.get(boundary)
        if existing is not None and existing != payload:
            raise BoundaryConflict(f"boundary {boundary} changed after commit")
        self.boundaries[boundary] = json.loads(reels.canonical_json(payload))

    def _load(self) -> None:
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BoundaryConflict(f"invalid acceptance ledger JSON line {line_number}") from exc
            if set(event) != {"ledgerVersion", "sequence", "eventType", "payload", "eventDigest"}:
                raise BoundaryConflict("acceptance ledger event fields invalid")
            if event["ledgerVersion"] != INTEGRATION_LEDGER_VERSION:
                raise BoundaryConflict("acceptance ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise BoundaryConflict("acceptance ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if reels.sha256_json(material) != digest:
                raise BoundaryConflict("acceptance ledger event digest mismatch")
            self.events.append(event)
            self._apply(event)

    def commit_boundary(
        self,
        boundary: str,
        payload: Mapping[str, Any],
        *,
        crash_after_commit: bool = False,
    ) -> str:
        if boundary not in CROSS_REPO_BOUNDARIES:
            raise BoundaryConflict(f"unsupported boundary {boundary!r}")
        normalized = json.loads(reels.canonical_json(payload))
        record = {
            "boundary": boundary,
            "payloadDigest": reels.sha256_json(normalized),
            "payload": normalized,
            "idempotencyKey": "cia13:" + reels.sha256_json(
                {"runId": self.run_id, "boundary": boundary, "payload": normalized}
            ),
        }
        existing = self.boundaries.get(boundary)
        if existing is not None:
            if existing != record:
                raise BoundaryConflict(f"conflicting replay at {boundary}")
            return "duplicate"
        self._append("boundary_committed", record)
        if crash_after_commit:
            raise BoundaryCrash(f"after_{boundary}_commit")
        return "committed"


def build_media_request(
    *,
    cycle_id: str,
    profile: Mapping[str, Any],
    script: Mapping[str, Any],
    asset_plan: Mapping[str, Any],
    edit_request: Mapping[str, Any],
) -> dict[str, Any]:
    material = {
        "contractVersion": MEDIA_REQUEST_VERSION,
        "cycleId": cycle_id,
        "profileDigest": profile["profileDigest"],
        "scriptDigest": script["sha256"],
        "assetPlanDigest": reels.sha256_json(asset_plan),
        "editRequestDigest": reels.sha256_json(edit_request),
    }
    material["idempotencyKey"] = "cmr13:" + reels.sha256_json(material)
    return material


class MockMediaAcceptanceProvider:
    def __init__(self, pin: MediaAcceptancePin, *, fail_after_effect_once: bool = False) -> None:
        self.pin = pin.validate()
        self.fail_after_effect_once = fail_after_effect_once
        self._results: dict[str, dict[str, Any]] = {}
        self.submit_calls = 0
        self.accepted_effects = 0

    def submit(self, request: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
        self.submit_calls += 1
        key = request["idempotencyKey"]
        existing = self._results.get(key)
        if existing is not None:
            return json.loads(reels.canonical_json(existing))
        self.accepted_effects += 1
        content_digest = reels.sha256_json({"request": request, "artifact": "final.mp4"})
        render_fp = reels.sha256_json({"request": request, "renderer": "mock-media-r11"})
        probe = {
            "hasVideo": True,
            "hasAudio": True,
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "durationMs": 30000,
            "videoCodec": "h264",
            "audioCodec": "aac",
            "blackFrameRatio": 0.0,
        }
        qa = {
            "passed": True,
            "checks": [
                {"name": "video-present", "pass": True},
                {"name": "vertical", "pass": True},
                {"name": "duration", "pass": True},
            ],
        }
        manifest = {
            "contractVersion": reels.MEDIA_ARTIFACT_MANIFEST_VERSION,
            "logicalJobId": "media-r13-" + reels.sha256_json({"key": key})[:16],
            "idempotencyKey": key,
            "renderFingerprint": render_fp,
            "attemptToken": "mock-media-r11:attempt:1",
            "validatedRequestDigest": reels.sha256_json(request),
            "profileDigest": profile["profileDigest"],
            "content": {
                "algorithm": "sha256",
                "sha256": content_digest,
                "size": 1234567,
                "contentId": f"sha256:{content_digest}",
            },
            "probeEvidence": {"sha256": reels.sha256_json(probe), "value": probe},
            "qaEvidence": {"sha256": reels.sha256_json(qa), "passed": True, "value": qa},
            "finalization": {
                "method": "atomic_rename",
                "preparedSha256": content_digest,
                "preparedSize": 1234567,
                "preparedAtMs": 1790812800000,
                "finalizedAtMs": 1790812801000,
            },
            "timestamps": {
                "jobCreatedAtMs": 1790812799000,
                "manifestCommittedAtMs": 1790812802000,
            },
        }
        result = {
            "contractVersion": reels.MEDIA_R11_ENVELOPE_VERSION,
            "sourceClass": "synthetic_fixture",
            "source": {
                "repository": reels.MEDIA_R11_REPOSITORY,
                "branch": reels.MEDIA_R11_BRANCH,
                "producerSha": self.pin.producer_sha,
                "jobContractPath": reels.MEDIA_JOB_CONTRACT_PATH,
                "jobContractBlobSha": self.pin.job_contract_blob_sha,
                "artifactManifestContractPath": reels.MEDIA_ARTIFACT_CONTRACT_PATH,
                "artifactManifestContractBlobSha": self.pin.artifact_manifest_contract_blob_sha,
            },
            "job": {
                "contractVersion": reels.MEDIA_JOB_VERSION,
                "jobId": manifest["logicalJobId"],
                "status": "succeeded",
                "idempotencyKey": key,
                "renderFingerprint": render_fp,
            },
            "artifactManifest": manifest,
            "preview": {
                "sha256": reels.sha256_json({"preview": content_digest}),
                "contentType": "image/jpeg",
            },
            "timelineSpec": {
                "sha256": reels.sha256_json({"timeline": request}),
                "profileDigest": profile["profileDigest"],
                "editRequestDigest": request["editRequestDigest"],
            },
        }
        self._results[key] = result
        if self.fail_after_effect_once:
            self.fail_after_effect_once = False
            raise BoundaryCrash("media effect accepted before Creator acknowledgement")
        return json.loads(reels.canonical_json(result))


def _growth_metrics_event(
    *,
    platform: str,
    account_id: str,
    post_id: str,
    cycle_revision: int,
    source_class: str,
) -> dict[str, Any]:
    if platform not in PLATFORM_FIXTURE_METRICS:
        raise IntegrationAcceptanceError("unsupported Growth acceptance platform")
    raw = {name: None for name in OPTIONAL_METRICS}
    raw.update(PLATFORM_FIXTURE_METRICS[platform])
    available = sorted(name for name, value in raw.items() if value is not None)
    fixture_source = reels.sha256_json({
        "producerSha": GROWTH_R11_PRODUCER_SHA,
        "fixtureBlobSha": GROWTH_R11_FIXTURE_BLOBS[platform],
        "metrics": raw,
    })
    window = {"start": "2026-10-01T00:00:03Z", "end": "2026-10-01T01:00:03Z"}
    export_id = f"creator-r13-{platform}-fixture@revision-1"
    provenance = {
        "provider": platform if source_class == "platform_export" else "fixture",
        "export_id": export_id,
        "export_digest": reels.sha256_json({
            "growthR11ProducerSha": GROWTH_R11_PRODUCER_SHA,
            "fixtureBlobSha": GROWTH_R11_FIXTURE_BLOBS[platform],
            "platform": platform,
        }),
        "fixture_source_sha256": None if source_class == "platform_export" else fixture_source,
        "live_performance_claim_allowed": source_class == "platform_export",
    }
    event = {
        "contract_version": "growth.shortform_platform_metrics.v1",
        "source_class": source_class,
        "platform": platform,
        "account_id": account_id,
        "post_id": post_id,
        "cycle_revision": cycle_revision,
        "captured_at": "2026-10-01T01:05:00Z",
        "window": window,
        "complete": True,
        "available_metrics": available,
        "metrics": raw,
        "provenance": provenance,
    }
    identity = {
        "platform": platform,
        "account_id": account_id,
        "post_id": post_id,
        "cycle_revision": cycle_revision,
        "export_id": export_id,
        "window": window,
    }
    event["metrics_event_id"] = "spm1:" + reels.sha256_json(identity)
    event["metrics_event_digest"] = reels.sha256_json(event)
    return event


def validate_growth_r11_provider_evidence(
    envelope: Mapping[str, Any],
    *,
    expected_platform: str,
    expected_account_id: str,
    expected_post_id: str,
    expected_source_class: str,
) -> dict[str, Any]:
    if not isinstance(envelope, Mapping) or set(envelope) != {
        "contractVersion", "source", "metricsEvent"
    }:
        raise IntegrationAcceptanceError("Growth R11 evidence fields must match exactly")
    if envelope["contractVersion"] != GROWTH_R11_EVIDENCE_VERSION:
        raise IntegrationAcceptanceError("unsupported Growth R11 evidence version")
    if envelope["source"] != growth_r11_source_pin():
        raise IntegrationAcceptanceError("Growth R11 exact producer/source pin mismatch")
    event = envelope["metricsEvent"]
    expected_fields = {
        "contract_version", "metrics_event_id", "metrics_event_digest", "source_class",
        "platform", "account_id", "post_id", "cycle_revision", "captured_at", "window",
        "complete", "available_metrics", "metrics", "provenance",
    }
    if not isinstance(event, Mapping) or set(event) != expected_fields:
        raise IntegrationAcceptanceError("Growth platform metrics contract mismatch")
    if event["contract_version"] != "growth.shortform_platform_metrics.v1":
        raise IntegrationAcceptanceError("Growth normalized output version mismatch")
    for field, expected in (
        ("platform", expected_platform),
        ("account_id", expected_account_id),
        ("post_id", expected_post_id),
        ("source_class", expected_source_class),
    ):
        if event[field] != expected:
            raise IntegrationAcceptanceError(f"Growth metrics {field} binding mismatch")
    if set(event["metrics"]) != set(OPTIONAL_METRICS):
        raise IntegrationAcceptanceError("Growth metrics must preserve unavailable fields as null")
    available = set(event["available_metrics"])
    if any((name in available) != (event["metrics"][name] is not None) for name in OPTIONAL_METRICS):
        raise IntegrationAcceptanceError("Growth available_metrics/null semantics mismatch")
    provenance = event["provenance"]
    if set(provenance) != {
        "provider", "export_id", "export_digest", "fixture_source_sha256",
        "live_performance_claim_allowed",
    }:
        raise IntegrationAcceptanceError("Growth metrics provenance fields mismatch")
    reels._sha64(provenance["export_digest"], "Growth export_digest")
    if expected_source_class == "synthetic_fixture":
        reels._sha64(provenance["fixture_source_sha256"], "Growth fixture_source_sha256")
        if provenance["provider"] != "fixture" or provenance["live_performance_claim_allowed"] is not False:
            raise IntegrationAcceptanceError("synthetic Growth evidence attempted live provenance")
    elif expected_source_class == "platform_export":
        if (
            provenance["fixture_source_sha256"] is not None
            or provenance["provider"] != expected_platform
            or provenance["live_performance_claim_allowed"] is not True
        ):
            raise IntegrationAcceptanceError("live Growth evidence provenance mismatch")
    else:
        raise IntegrationAcceptanceError("unsupported Growth source class")
    digest = event["metrics_event_digest"]
    reels._sha64(digest, "Growth metrics_event_digest")
    material = dict(event)
    material.pop("metrics_event_digest")
    if reels.sha256_json(material) != digest:
        raise IntegrationAcceptanceError("Growth metrics event digest mismatch")
    return json.loads(reels.canonical_json(envelope))


def _growth_seed_envelope(
    *,
    next_cycle_id: str,
    cycle_revision: int,
    script: Mapping[str, Any],
    media_envelope: Mapping[str, Any],
    receipt: Mapping[str, Any],
    growth_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    event = growth_evidence["metricsEvent"]
    source_class = event["source_class"]
    manifest = media_envelope["artifactManifest"]
    live = source_class == "platform_export"
    publish_result = {
        "contract_version": reels.GROWTH_PUBLISH_RESULT_VERSION,
        "source_class": source_class,
        "platform": receipt["platform"],
        "account_id": receipt["accountId"],
        "post_id": receipt["postId"],
        "published_at": receipt["publishedAt"],
        "captured_at": receipt["capturedAt"],
        "cycle_revision": cycle_revision,
        "artifact": {
            "creative_artifact_id": f"script-r{script['revision']}",
            "creative_artifact_digest": script["sha256"],
            "media_artifact_id": receipt["mediaContentId"],
            "media_artifact_digest": receipt["mediaContentSha256"],
            "media_render_fingerprint": manifest["renderFingerprint"],
            "media_duration_seconds": float(manifest["probeEvidence"]["value"]["durationMs"]) / 1000.0,
        },
        "provenance": {
            "provider_receipt_digest": receipt["receiptDigest"] if live else None,
            "fixture_source_sha256": None if live else receipt["receiptDigest"],
            "live_performance_claim_allowed": live,
        },
    }
    identity = {
        "platform": publish_result["platform"],
        "account_id": publish_result["account_id"],
        "post_id": publish_result["post_id"],
        "cycle_revision": cycle_revision,
        "media_artifact_digest": publish_result["artifact"]["media_artifact_digest"],
    }
    publish_result["publish_result_id"] = "spr1:" + reels.sha256_json(identity)
    publish_result["publish_result_digest"] = reels.sha256_json(publish_result)

    normalized = {name: event["metrics"][name] for name in event["available_metrics"]}
    snapshot = {
        "account_id": receipt["accountId"],
        "available_metrics": list(event["available_metrics"]),
        "contract_version": reels.GROWTH_METRIC_SNAPSHOT_VERSION,
        "cycle_revision": cycle_revision,
        "denominators": {},
        "live_performance_claim_allowed": live,
        "normalization_sources": {},
        "normalized_metrics": normalized,
        "platform": receipt["platform"],
        "post_id": receipt["postId"],
        "provenance": {
            "complete_export": True,
            "observational": True,
            "provider": event["provenance"]["provider"],
        },
        "publish_result_digest": publish_result["publish_result_digest"],
        "publish_result_id": publish_result["publish_result_id"],
        "raw_metrics": json.loads(reels.canonical_json(event["metrics"])),
        "selected_metrics_event_digest": event["metrics_event_digest"],
        "selected_metrics_event_id": event["metrics_event_id"],
        "source_class": source_class,
        "uncertainty": {},
        "window": json.loads(reels.canonical_json(event["window"])),
    }
    snapshot["snapshot_digest"] = reels.sha256_json(snapshot)
    decision = {"state": "none", "handoff_digest": None}
    lineage = {
        "creative_artifact_id": publish_result["artifact"]["creative_artifact_id"],
        "creative_artifact_digest": publish_result["artifact"]["creative_artifact_digest"],
        "media_artifact_id": publish_result["artifact"]["media_artifact_id"],
        "media_artifact_digest": publish_result["artifact"]["media_artifact_digest"],
        "media_render_fingerprint": publish_result["artifact"]["media_render_fingerprint"],
        "media_duration_seconds": publish_result["artifact"]["media_duration_seconds"],
        "publish_result_id": publish_result["publish_result_id"],
        "publish_result_digest": publish_result["publish_result_digest"],
        "platform": publish_result["platform"],
        "account_id": publish_result["account_id"],
        "post_id": publish_result["post_id"],
        "published_at": publish_result["published_at"],
        "metric_snapshot_digest": snapshot["snapshot_digest"],
        "metric_window": snapshot["window"],
        "decision": decision,
    }
    seed = {
        "contract_version": reels.GROWTH_NEXT_CYCLE_SEED_VERSION,
        "next_cycle_id": next_cycle_id,
        "cycle_revision": cycle_revision,
        "source_class": source_class,
        "live_performance_claim_allowed": live,
        "creator_cycle_eligible": live,
        "evidence_state": "directional_observational",
        "lineage": lineage,
        "evidence": {
            "publish_result": publish_result,
            "metric_snapshot": snapshot,
            "decision_handoff": None,
        },
        "metrics": {
            "normalized": snapshot["normalized_metrics"],
            "normalization_sources": snapshot["normalization_sources"],
            "denominators": snapshot["denominators"],
            "uncertainty": snapshot["uncertainty"],
            "available_metrics": snapshot["available_metrics"],
        },
        "recommendations": [{
            "action": "carry_forward_observational_signal",
            "certainty": "directional_not_causal",
            "state": "observational_signal",
            "evidence_refs": [f"metric_snapshot:{snapshot['snapshot_digest']}"],
            "rationale": "R13 deterministic acceptance fixture",
        }],
        "authority": {
            "auto_publish": False,
            "external_mutation": False,
            "release_authorized": False,
            "publish_authorized": False,
            "requires_creator_release_authorization": True,
        },
        "interpretation": "Synthetic acceptance evidence is observational and never authorizes publishing.",
    }
    seed_identity = {
        "next_cycle_id": next_cycle_id,
        "cycle_revision": cycle_revision,
        "publish_result_digest": publish_result["publish_result_digest"],
        "metric_snapshot_digest": snapshot["snapshot_digest"],
        "decision_handoff_digest": None,
    }
    seed["idempotency_key"] = "grs1:" + reels.sha256_json(seed_identity)
    seed["seed_digest"] = reels.sha256_json(seed)
    return {
        "contractVersion": reels.GROWTH_R10_ENVELOPE_VERSION,
        "source": {
            "repository": reels.GROWTH_R10_REPOSITORY,
            "branch": reels.GROWTH_R10_BRANCH,
            "producerSha": GROWTH_R10_PRODUCER_SHA,
            "contractPath": reels.GROWTH_R10_CONTRACT_PATH,
            "contractBlobSha": GROWTH_R10_IMPLEMENTATION_BLOB_SHA,
        },
        "seed": seed,
    }


class MockGrowthR11AcceptanceProvider:
    def __init__(self, *, fail_after_effect_once: bool = False) -> None:
        self.fail_after_effect_once = fail_after_effect_once
        self._results: dict[str, dict[str, Any]] = {}
        self.calls = 0
        self.accepted_effects = 0

    def ingest(
        self,
        *,
        handoff: Mapping[str, Any],
        next_cycle_id: str,
        cycle_revision: int,
        script: Mapping[str, Any],
        media_envelope: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.calls += 1
        key = handoff["handoffDigest"]
        existing = self._results.get(key)
        if existing is not None:
            return json.loads(reels.canonical_json(existing))
        self.accepted_effects += 1
        source_class = handoff["sourceClass"]
        metrics = _growth_metrics_event(
            platform=handoff["platform"],
            account_id=handoff["accountId"],
            post_id=handoff["postId"],
            cycle_revision=cycle_revision,
            source_class=source_class,
        )
        evidence = {
            "contractVersion": GROWTH_R11_EVIDENCE_VERSION,
            "source": growth_r11_source_pin(),
            "metricsEvent": metrics,
        }
        validate_growth_r11_provider_evidence(
            evidence,
            expected_platform=handoff["platform"],
            expected_account_id=handoff["accountId"],
            expected_post_id=handoff["postId"],
            expected_source_class=source_class,
        )
        seed_envelope = _growth_seed_envelope(
            next_cycle_id=next_cycle_id,
            cycle_revision=cycle_revision,
            script=script,
            media_envelope=media_envelope,
            receipt=receipt,
            growth_evidence=evidence,
        )
        result = {
            "growthR11Evidence": evidence,
            "nextCycleSeedEnvelope": seed_envelope,
        }
        self._results[key] = result
        if self.fail_after_effect_once:
            self.fail_after_effect_once = False
            raise BoundaryCrash("Growth effect accepted before Creator acknowledgement")
        return json.loads(reels.canonical_json(result))


def _profile(platform: str) -> dict[str, Any]:
    return reels.canonical_reels_profile(
        caption=f"R13 {platform} acceptance caption",
        cta="Follow for the next deterministic cycle",
        hashtags=("#creator", "#shortform"),
    )


def _stage_inputs(profile: Mapping[str, Any]) -> dict[str, Any]:
    script_text = "Hook immediately. Show the deterministic proof. End with one explicit call to action."
    script = {"revision": 1, "text": script_text, "sha256": reels.sha256_text(script_text)}
    asset_plan = {
        "assets": [{
            "assetId": "asset-r13-1",
            "sourceUri": "fixture://r13/asset/1",
            "sha256": "d" * 64,
            "rightsRef": "fixture-rights-r13",
        }]
    }
    edit_request = {
        "voice": {"mode": "voiceover", "sourceRef": "fixture://r13/voice/1"},
        "music": {"assetRef": "fixture://r13/music/1", "duckUnderVoiceDb": -9},
        "subtitles": {"enabled": True, "language": "en", "burnIn": True},
        "edit": {
            "trim": True,
            "cuts": "beat-aligned",
            "reframe": "center-subject",
            "transitions": "requested-only",
            "ctaOutroSeconds": 2.0,
        },
        "profileDigest": profile["profileDigest"],
    }
    return {
        "brief": {
            "goal": "Prove the R13 autonomous Reel integration lifecycle",
            "topic": "integration acceptance",
            "audience": "short-form creators",
        },
        "research_evidence": {
            "items": [{
                "evidenceId": "r13-evidence-1",
                "sourceUri": "fixture://r13/research/1",
                "sha256": "c" * 64,
                "capturedAt": "2026-10-01T00:00:00Z",
            }]
        },
        "idea_hook": {
            "idea": "Show deterministic recovery across every boundary",
            "hook": "One crash should never create two posts.",
            "hookWindowSeconds": profile["hookWindowSeconds"],
        },
        "script": script,
        "asset_plan": asset_plan,
        "edit_request": edit_request,
    }


def _release_authorization(
    *,
    cycle_id: str,
    platform: str,
    destination: str,
    artifact_id: str,
    artifact_digest: str,
) -> dict[str, Any]:
    return {
        "contractVersion": reels.RELEASE_AUTHORIZATION_VERSION,
        "decisionId": f"r13-decision-{platform}",
        "idempotencyKey": f"r13-release-auth-{platform}",
        "requestId": f"r13-release-request-{platform}",
        "campaignId": cycle_id,
        "candidateId": f"r13-candidate-{platform}",
        "artifactId": artifact_id,
        "artifactHash": f"sha256:{artifact_digest}",
        "lineageHash": "sha256:" + "b" * 64,
        "destinationScope": {
            "provider": platform,
            "destination": destination,
            "action": "release",
        },
        "decision": "approved",
        "authorizationId": f"r13-authorization-{platform}",
        "expiresAt": "2026-10-02T00:00:00Z",
        "decidedAt": "2026-10-01T00:00:00Z",
        "decisionSource": "external",
        "approverRef": "fixture-human-approver-r13",
    }


def _provider_for(platform: str):
    mapping = {
        "instagram_reels": InstagramReelsMockProvider,
        "tiktok": TikTokMockProvider,
        "youtube_shorts": YouTubeShortsMockProvider,
    }
    try:
        return mapping[platform]()
    except KeyError as exc:
        raise IntegrationAcceptanceError("unsupported platform") from exc


def run_platform_acceptance(
    *,
    work_dir: str | os.PathLike[str],
    platform: str,
    media_pin: MediaAcceptancePin | None,
    media_provider: MockMediaAcceptanceProvider | None = None,
    publish_provider: Any | None = None,
    growth_provider: MockGrowthR11AcceptanceProvider | None = None,
) -> dict[str, Any]:
    readiness = readiness_report(media_pin)
    if readiness["overall"] == "BLOCKED_MEDIA":
        return readiness
    assert media_pin is not None
    media_pin.validate()
    root = Path(work_dir) / platform
    root.mkdir(parents=True, exist_ok=True)
    cycle_id = f"r13-cycle-1-{platform}"
    next_cycle_id = f"r13-cycle-2-{platform}"
    profile = _profile(platform)
    inputs = _stage_inputs(profile)

    boundary_ledger = IntegrationAcceptanceLedger(
        root / "integration-boundaries.jsonl",
        run_id=f"r13-{platform}",
    )
    creator = reels.AutonomousReelsLedger(
        root / "creator-cycle.jsonl",
        cycle_id=cycle_id,
        topic="integration acceptance",
        cycle_revision=1,
        profile=profile,
        media_producer_sha=media_pin.producer_sha,
        media_job_contract_blob_sha=media_pin.job_contract_blob_sha,
        media_manifest_contract_blob_sha=media_pin.artifact_manifest_contract_blob_sha,
        growth_producer_sha=GROWTH_R10_PRODUCER_SHA,
        growth_contract_blob_sha=GROWTH_R10_IMPLEMENTATION_BLOB_SHA,
        allow_synthetic_fixture=True,
    )
    provenance = {
        "producer": "creator-r13-acceptance",
        "sourceClass": "synthetic_fixture",
        "sourceRef": f"fixture://r13/{platform}",
        "sha256": reels.sha256_json({"platform": platform, "cycle": cycle_id}),
    }
    for stage in ("brief", "research_evidence", "idea_hook", "script", "asset_plan", "edit_request"):
        creator.commit_stage(stage, inputs[stage], provenance=provenance)

    media_request = build_media_request(
        cycle_id=cycle_id,
        profile=profile,
        script=inputs["script"],
        asset_plan=inputs["asset_plan"],
        edit_request=inputs["edit_request"],
    )
    boundary_ledger.commit_boundary("creator_to_media_request", media_request)
    media_provider = media_provider or MockMediaAcceptanceProvider(media_pin)
    media_result = media_provider.submit(media_request, profile)
    creator.commit_stage("media_render", media_result, provenance=provenance)
    boundary_ledger.commit_boundary("media_to_creator_result", media_result)

    critic = {
        "decision": "pass",
        "qaDigest": media_result["artifactManifest"]["qaEvidence"]["sha256"],
        "checks": [
            {"name": "hook-within-window", "pass": True},
            {"name": "captions-present", "pass": True},
            {"name": "media-qa-bound", "pass": True},
        ],
    }
    creator.commit_stage("critic_qa", critic, provenance=provenance)
    manifest = media_result["artifactManifest"]
    artifact_id = manifest["content"]["contentId"]
    artifact_digest = manifest["content"]["sha256"]
    account_id = f"fixture-{platform}-account"
    destination = f"fixture-{platform}-destination"
    auth = _release_authorization(
        cycle_id=cycle_id,
        platform=platform,
        destination=destination,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    creator.commit_stage("publish_queue", {
        "intentId": f"r13-publish-intent-{platform}",
        "idempotencyKey": f"r13-publish-queue-{platform}",
        "provider": platform,
        "destination": destination,
        "platform": platform,
        "artifactId": artifact_id,
        "artifactDigest": artifact_digest,
        "caption": profile["metadata"]["caption"],
        "cta": profile["metadata"]["cta"],
        "releaseAuthorization": auth,
        "adapterState": {
            "state": "ready",
            "provider": platform,
            "destination": destination,
            "recoverySupported": True,
            "idempotentSubmit": True,
            "evidenceDigest": reels.sha256_json({
                "provider": platform,
                "destination": destination,
                "contract": "creator.publish_provider.v1",
            }),
        },
    }, provenance=provenance)

    r12_request = build_publish_request(
        platform=platform,
        account_id=account_id,
        destination=destination,
        credential_ref=f"vault-ref://{platform}/r13-fixture",
        authorization_lineage={
            "credentialRef": f"vault-ref://{platform}/r13-fixture",
            "authorizationRef": f"oauth-grant-ref://{platform}/r13-fixture",
        },
        media={
            "sourceClass": "synthetic_fixture",
            "contentId": artifact_id,
            "contentSha256": artifact_digest,
            "sizeBytes": manifest["content"]["size"],
            "contentType": "video/mp4",
            "durationSeconds": float(manifest["probeEvidence"]["value"]["durationMs"]) / 1000.0,
            "aspectRatio": "9:16",
            "manifestDigest": reels.sha256_json(manifest),
        },
        caption=profile["metadata"]["caption"],
        cta=profile["metadata"]["cta"],
        release_authorization=auth,
        allow_synthetic_fixture=True,
    )
    boundary_ledger.commit_boundary("creator_to_publish_provider", r12_request)
    publisher = publish_provider or _provider_for(platform)
    coordinator = DurablePublishCoordinator(
        root / "publish-provider.jsonl",
        r12_request,
        allow_synthetic_fixture=True,
    )
    outcome: dict[str, Any] = {"state": "recoverable_unknown", "receipt": None}
    for offset in range(6):
        outcome = coordinator.drive(
            publisher,
            now=f"2026-10-01T00:00:0{offset}Z",
        )
        if outcome["state"] in {"published", "failed_terminal", "waiting_for_credentials"}:
            break
    if outcome["state"] != "published" or outcome["receipt"] is None:
        raise IntegrationAcceptanceError(f"publish acceptance did not reach published: {outcome['state']}")
    receipt = outcome["receipt"]
    boundary_ledger.commit_boundary("publish_provider_to_creator_receipt", receipt)

    growth_handoff = build_r12_growth_handoff(
        receipt,
        r12_request,
        allow_synthetic_fixture=True,
    )
    boundary_ledger.commit_boundary("creator_to_growth_handoff", growth_handoff)
    growth_provider = growth_provider or MockGrowthR11AcceptanceProvider()
    growth_result = growth_provider.ingest(
        handoff=growth_handoff,
        next_cycle_id=next_cycle_id,
        cycle_revision=1,
        script=inputs["script"],
        media_envelope=media_result,
        receipt=receipt,
    )
    growth_evidence = validate_growth_r11_provider_evidence(
        growth_result["growthR11Evidence"],
        expected_platform=platform,
        expected_account_id=receipt["accountId"],
        expected_post_id=receipt["postId"],
        expected_source_class=growth_handoff["sourceClass"],
    )
    boundary_ledger.commit_boundary("growth_r11_provider_metrics", growth_evidence)

    seed_envelope = reels.validate_growth_r10_seed_envelope(
        growth_result["nextCycleSeedEnvelope"],
        expected_producer_sha=GROWTH_R10_PRODUCER_SHA,
        expected_contract_blob_sha=GROWTH_R10_IMPLEMENTATION_BLOB_SHA,
        current_cycle_id=next_cycle_id,
        expected_source_cycle_revision=1,
        allow_synthetic_fixture=True,
    )
    boundary_ledger.commit_boundary("growth_to_creator_next_cycle_seed", seed_envelope)
    next_cycle = reels.AutonomousReelsLedger(
        root / "creator-next-cycle.jsonl",
        cycle_id=next_cycle_id,
        topic="integration acceptance next cycle",
        cycle_revision=2,
        profile=profile,
        media_producer_sha=media_pin.producer_sha,
        media_job_contract_blob_sha=media_pin.job_contract_blob_sha,
        media_manifest_contract_blob_sha=media_pin.artifact_manifest_contract_blob_sha,
        growth_producer_sha=GROWTH_R10_PRODUCER_SHA,
        growth_contract_blob_sha=GROWTH_R10_IMPLEMENTATION_BLOB_SHA,
        allow_synthetic_fixture=True,
    )
    consume_status = next_cycle.consume_growth_seed(
        seed_envelope,
        expected_source_cycle_revision=1,
    )
    report = {
        "reportVersion": INTEGRATION_ACCEPTANCE_VERSION,
        "overall": "SYNTHETIC_ACCEPTANCE_GREEN",
        "platform": platform,
        "cycleId": cycle_id,
        "nextCycleId": next_cycle_id,
        "gates": readiness["gates"],
        "crossRepoBoundaries": list(CROSS_REPO_BOUNDARIES),
        "boundaryEventCount": len(boundary_ledger.boundaries),
        "effects": {
            "mediaLogicalEffects": media_provider.accepted_effects,
            "mediaSubmitCalls": media_provider.submit_calls,
            "publishLogicalEffects": publisher.accepted_effects,
            "publishSubmitCalls": publisher.submit_calls,
            "growthLogicalEffects": growth_provider.accepted_effects,
            "growthIngestCalls": growth_provider.calls,
        },
        "publishReceiptDigest": receipt["receiptDigest"],
        "growthMetricsDigest": growth_evidence["metricsEvent"]["metrics_event_digest"],
        "nextCycleSeedDigest": seed_envelope["seed"]["seed_digest"],
        "nextCycleConsumeStatus": consume_status,
        "livePerformanceClaimEligible": growth_handoff["livePerformanceClaimEligible"],
        "productionReadinessClaim": False,
    }
    report["reportDigest"] = reels.sha256_json(report)
    return report


def run_all_platforms(
    *,
    work_dir: str | os.PathLike[str],
    media_pin: MediaAcceptancePin | None,
) -> dict[str, Any]:
    readiness = readiness_report(media_pin)
    if readiness["overall"] == "BLOCKED_MEDIA":
        return readiness
    results = [
        run_platform_acceptance(
            work_dir=work_dir,
            platform=platform,
            media_pin=media_pin,
        )
        for platform in ("instagram_reels", "tiktok", "youtube_shorts")
    ]
    report = {
        "reportVersion": INTEGRATION_ACCEPTANCE_VERSION,
        "overall": "SYNTHETIC_ACCEPTANCE_GREEN",
        "platforms": results,
        "mediaPin": media_pin.as_dict() if media_pin else None,
        "growthR11Source": growth_r11_source_pin(),
        "productionReadinessClaim": False,
    }
    report["reportDigest"] = reels.sha256_json(report)
    return report


def _media_pin_from_args(args: argparse.Namespace) -> MediaAcceptancePin | None:
    values = (
        args.media_producer_sha,
        args.media_job_contract_blob_sha,
        args.media_manifest_contract_blob_sha,
        args.media_conformance_manifest_blob_sha,
        args.media_creator_consumer_blob_sha,
        args.media_ci_run_id,
        args.media_ci_conclusion,
    )
    if not any(values):
        return None
    if not all(values):
        raise SystemExit("all Media exact-pin/CI arguments are required together")
    return MediaAcceptancePin(
        producer_sha=args.media_producer_sha,
        job_contract_blob_sha=args.media_job_contract_blob_sha,
        artifact_manifest_contract_blob_sha=args.media_manifest_contract_blob_sha,
        conformance_manifest_blob_sha=args.media_conformance_manifest_blob_sha,
        creator_consumer_blob_sha=args.media_creator_consumer_blob_sha,
        ci_run_id=args.media_ci_run_id,
        ci_conclusion=args.media_ci_conclusion,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Creator R13 integration acceptance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("readiness")
    run = sub.add_parser("run")
    run.add_argument("--work-dir", required=True)
    run.add_argument(
        "--platform",
        choices=("all", "instagram_reels", "tiktok", "youtube_shorts"),
        default="all",
    )
    run.add_argument("--media-producer-sha")
    run.add_argument("--media-job-contract-blob-sha")
    run.add_argument("--media-manifest-contract-blob-sha")
    run.add_argument("--media-conformance-manifest-blob-sha")
    run.add_argument("--media-creator-consumer-blob-sha")
    run.add_argument("--media-ci-run-id")
    run.add_argument("--media-ci-conclusion")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        print(json.dumps(readiness_report(None), sort_keys=True, indent=2))
        return 2
    pin = _media_pin_from_args(args)
    if args.platform == "all":
        report = run_all_platforms(work_dir=args.work_dir, media_pin=pin)
    else:
        report = run_platform_acceptance(
            work_dir=args.work_dir,
            platform=args.platform,
            media_pin=pin,
        )
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["overall"] == "SYNTHETIC_ACCEPTANCE_GREEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
