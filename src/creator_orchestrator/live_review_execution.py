from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_editor_loop as r22
from . import autonomous_reels as reels
from . import editor_publish_handoff as r23
from . import publish_execution as r21
from . import real_review_closed_loop as r26

CONTRACT_VERSION = "creator.real_live_review_execution.r27.v1"
ENVELOPE_VERSION = "creator.growth_r25_external_review.r27.v1"
CANDIDATE_CONTEXT_VERSION = "creator.reviewed_candidate_context.r27.v1"
LEDGER_VERSION = "creator.real_live_review_execution_ledger.r27.v1"
REPORT_VERSION = "creator.real_live_review_execution.r27.readiness.v1"
NEXT_REVIEW_VERSION = "creator.next_live_review_request.r27.v1"

CREATOR_R26_BASE_SHA = "ee73a4492c0e96b54f050be2a6d24a1af06c16bf"
MAX_REEDIT_ROUNDS = 2

MEDIA_R19 = {
    "repository": "foto6/video2",
    "branch": "agent/media-r19-editorial-runtime-production-20261002",
    "sha": "31409de4bef473417a33a8c698507f7cfb1905e1",
    "ciRunId": 36984502487,
    "applicationContract": "media.editorial_reedit_application.v1",
    "requestContract": "media.editorial_reedit_request.r19.v1",
    "applicationContractBlobSha1": "6b3350c5f1524fe49a49d5637514e2fb1a808bcf",
    "applicationManifestBlobSha1": "502c32253d370e9b4e3d53f4a70de317f89dd21b",
    "applicationSchemaBlobSha1": "7cabf91f08ae11b68cc4a7eec88d358a46730289",
    "implementationBlobSha1": "8110a086b5b319bd2601860845c6afbf97681921",
    "runnerBlobSha1": "7dbec612621aa42baaf2946cdac61d070e3ff41f",
    "renderExportContract": "media.render_export.v1",
    "renderExportManifestBlobSha1": "945acb01ff0269d89b91463aa8d862f500e055b2",
    "renderExportSchemaBlobSha1": "6353d32d785a2a1f1441bac4cfd0271b46b41d4a",
}

# The branch exists, but at R27 implementation time it is still identical to
# exact-green Growth R24 and contains no R25-specific Creator-ready envelope.
GROWTH_R25_OBSERVED = {
    "repository": "foto6/video3",
    "branch": "agent/growth-r25-real-capture-ingest-20261002",
    "observedSha": "dc0741d5b11c1f7464ac9a6c5db80c0a4535df08",
    "observedCiRunId": 36987057963,
    "observedContract": "growth.live_video_review_capture.v1",
    "observedContractBlobSha1": "4c37ebd518d6f931140e47c5ce4590bb923157aa",
    "observedSchemaBlobSha1": "0e21bdb22c46ff8bb74694f9fc0fcf1d66274253",
    "observedImplementationBlobSha1": "e0acb79b04332f78fd051fa4889e052c4424cc81",
    "creatorReadyEnvelopeAvailable": False,
    "missing": (
        "agent/growth-r25-real-capture-ingest-20261002 still points to "
        "Growth R24 head dc0741d5b11c1f7464ac9a6c5db80c0a4535df08 "
        "and contains no R25-specific Creator-ready external review envelope "
        "contract/schema"
    ),
}

# The named R20 integration branch also still points at the R19 producer and
# contains no dynamic next-round blinded-review package contract.
MEDIA_R20_OBSERVED = {
    "repository": "foto6/video2",
    "branch": "agent/media-r20-r19-creator-integration-20261002",
    "observedSha": "31409de4bef473417a33a8c698507f7cfb1905e1",
    "observedCiRunId": 36984502487,
    "dynamicReviewPackageAvailable": False,
    "missing": (
        "agent/media-r20-r19-creator-integration-20261002 still points to "
        "Media R19 head 31409de4bef473417a33a8c698507f7cfb1905e1 "
        "and contains no R20-specific dynamic blinded review package contract"
    ),
}

SUPPORTED_STATES = {
    "targeted_reedit",
    "winner",
    "tie",
    "insufficient_evidence",
    "human_review",
}


class R27Error(ValueError):
    pass


class DependencyUnavailable(R27Error):
    pass


class DependencyDrift(R27Error):
    pass


class ReviewLineageError(R27Error):
    pass


class ReviewReplayConflict(R27Error):
    pass


class RoundLimitError(R27Error):
    pass


class MediaR19Error(R27Error):
    pass


class InjectedLostAck(RuntimeError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _hex(value: Any, size: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != size
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReviewLineageError(f"{field} must be lowercase {size}-hex")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewLineageError(f"{field} must be non-empty")
    return value


def _git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(path),
        text=True,
    ).strip()


def _git_blob_sha(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file_size(path: Path) -> int:
    return Path(path).stat().st_size


def verify_media_r19_checkout(media_checkout: Path) -> dict[str, Any]:
    root = Path(media_checkout).resolve()
    if _git_head(root) != MEDIA_R19["sha"]:
        raise DependencyDrift("Media checkout is not exact R19 producer SHA")
    checks = {
        "applicationContractBlobSha1": root
        / "conformance"
        / "media.editorial_reedit_application.v1"
        / "contract.json",
        "applicationManifestBlobSha1": root
        / "conformance"
        / "media.editorial_reedit_application.v1"
        / "manifest.json",
        "applicationSchemaBlobSha1": root
        / "conformance"
        / "media.editorial_reedit_application.v1"
        / "schema.json",
        "implementationBlobSha1": root / "src" / "editorial-reedit-r19.js",
        "runnerBlobSha1": root / "tools" / "run-r19-editorial-reedit.mjs",
        "renderExportManifestBlobSha1": root
        / "conformance"
        / "media.render_export.v1"
        / "manifest.json",
        "renderExportSchemaBlobSha1": root
        / "conformance"
        / "media.render_export.v1"
        / "schema.json",
    }
    observed = {
        "repository": MEDIA_R19["repository"],
        "branch": MEDIA_R19["branch"],
        "sha": _git_head(root),
        "ciRunId": MEDIA_R19["ciRunId"],
        "applicationContract": MEDIA_R19["applicationContract"],
        "requestContract": MEDIA_R19["requestContract"],
        "renderExportContract": MEDIA_R19["renderExportContract"],
    }
    for key, path in checks.items():
        if not path.is_file():
            raise DependencyDrift(f"Media R19 required file missing: {path}")
        digest = _git_blob_sha(path)
        observed[key] = digest
        if digest != MEDIA_R19[key]:
            raise DependencyDrift(f"Media R19 {key} drift")
    return observed


def observe_growth_r25_checkout(growth_checkout: Path) -> dict[str, Any]:
    root = Path(growth_checkout).resolve()
    head = _git_head(root)
    observed = _clone(GROWTH_R25_OBSERVED)
    observed["checkoutSha"] = head
    if head != GROWTH_R25_OBSERVED["observedSha"]:
        raise DependencyUnavailable(
            "Growth R25 branch moved beyond the pinned observed dependency; "
            "R27 requires a new exact contract/blob pin before ingestion"
        )
    for rel, expected in (
        (
            "conformance/growth.live_video_review_capture.v1/contract.json",
            GROWTH_R25_OBSERVED["observedContractBlobSha1"],
        ),
        (
            "conformance/growth.live_video_review_capture.v1/schema.json",
            GROWTH_R25_OBSERVED["observedSchemaBlobSha1"],
        ),
        (
            "growth_analytics/live_review_ingest.py",
            GROWTH_R25_OBSERVED["observedImplementationBlobSha1"],
        ),
    ):
        path = root / rel
        if not path.is_file() or _git_blob_sha(path) != expected:
            raise DependencyDrift(f"observed Growth R24/R25 dependency drift: {rel}")
    return observed


def observe_media_r20_checkout(media_checkout: Path) -> dict[str, Any]:
    root = Path(media_checkout).resolve()
    head = _git_head(root)
    observed = _clone(MEDIA_R20_OBSERVED)
    observed["checkoutSha"] = head
    if head != MEDIA_R20_OBSERVED["observedSha"]:
        raise DependencyUnavailable(
            "Media R20 branch moved beyond the pinned observed dependency; "
            "R27 requires exact dynamic review package pins before use"
        )
    return observed


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": REPORT_VERSION,
        "creatorBaseSha": CREATOR_R26_BASE_SHA,
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": False,
        "REAL_REEDIT_EXECUTED": False,
        "PUBLISH_HANDOFF_READY": False,
        "state": "BLOCKED_WAITING_REAL_CAPTURE",
        "mediaR19": _clone(MEDIA_R19),
        "growthR25": _clone(GROWTH_R25_OBSERVED),
        "mediaR20": _clone(MEDIA_R20_OBSERVED),
        "blockers": [
            {
                "code": "GROWTH_R25_CREATOR_READY_ENVELOPE_UNAVAILABLE",
                "detail": GROWTH_R25_OBSERVED["missing"],
            },
            {
                "code": "GENUINE_BRIDGE_R29_GROWTH_R25_CAPTURE_NOT_AVAILABLE",
                "detail": (
                    "No genuine Bridge R29 -> Growth R25 Creator-ready review "
                    "artifact is attached or otherwise available in this Creator agent context."
                ),
            },
            {
                "code": "MEDIA_R20_DYNAMIC_REVIEW_PACKAGE_UNAVAILABLE",
                "detail": MEDIA_R20_OBSERVED["missing"],
            },
        ],
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanLevelQualityClaimed": False,
        "safety": {
            "liveSocialProviderMutation": False,
            "credentials": False,
            "captcha2faBypass": False,
            "humanLevelClaim": False,
            "fixturePromotedToReal": False,
        },
    }
    report["reportDigest"] = _sha(report)
    return report


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            event = json.loads(line)
            material = dict(event)
            digest = material.pop("eventDigest", None)
            if (
                event.get("ledgerVersion") != LEDGER_VERSION
                or _sha(material) != digest
            ):
                raise R27Error("R27 ledger corruption")
            if event.get("sequence") != len(self.events) + 1:
                raise R27Error("R27 ledger sequence mismatch")
            key = event.get("eventKey")
            if key in self.by_key:
                raise R27Error("R27 duplicate durable event key")
            reels._reject_secrets(event["payload"])
            self.events.append(event)
            self.by_key[key] = event

    def append_once(
        self,
        key: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if (
                prior["eventType"] != event_type
                or prior["payload"] != normalized
            ):
                raise ReviewReplayConflict(
                    f"conflicting durable replay for {key}"
                )
            return "duplicate"
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": key,
            "eventType": event_type,
            "payload": normalized,
        }
        event["eventDigest"] = _sha(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self.by_key[key] = event
        return "committed"

    @property
    def digest(self) -> str:
        return _sha(self.events)

    @property
    def preterminal_digest(self) -> str:
        return _sha(
            [event for event in self.events if event["eventKey"] != "terminal"]
        )


def validate_candidate_context(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contractVersion",
        "loopId",
        "briefDigest",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
        "ledgerDigest",
        "source",
        "candidate",
        "timeline",
        "exportSpec",
        "contextDigest",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ReviewLineageError("R27 candidate context fields invalid")
    if value["contractVersion"] != CANDIDATE_CONTEXT_VERSION:
        raise ReviewLineageError("R27 candidate context contract mismatch")
    for key in (
        "briefDigest",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
        "ledgerDigest",
    ):
        _hex(value[key], 64, f"context.{key}")
    _nonempty(value["loopId"], "context.loopId")
    source = value["source"]
    if not isinstance(source, Mapping) or set(source) != {
        "sourceId",
        "sha256",
        "size",
    }:
        raise ReviewLineageError("R27 context source fields invalid")
    _nonempty(source["sourceId"], "context.source.sourceId")
    _hex(source["sha256"], 64, "context.source.sha256")
    if (
        isinstance(source["size"], bool)
        or not isinstance(source["size"], int)
        or source["size"] <= 0
    ):
        raise ReviewLineageError("context.source.size invalid")
    candidate = value["candidate"]
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidateId",
        "roundIndex",
        "finalPath",
        "renderSha256",
        "renderSize",
        "renderExportPath",
        "renderExportSha256",
        "renderProducerSha",
    }:
        raise ReviewLineageError("R27 context candidate fields invalid")
    _nonempty(candidate["candidateId"], "candidate.candidateId")
    if (
        isinstance(candidate["roundIndex"], bool)
        or not isinstance(candidate["roundIndex"], int)
        or not 0 <= candidate["roundIndex"] <= MAX_REEDIT_ROUNDS
    ):
        raise RoundLimitError("candidate roundIndex invalid")
    _hex(candidate["renderSha256"], 64, "candidate.renderSha256")
    _hex(candidate["renderExportSha256"], 64, "candidate.renderExportSha256")
    _hex(candidate["renderProducerSha"], 40, "candidate.renderProducerSha")
    if (
        isinstance(candidate["renderSize"], bool)
        or not isinstance(candidate["renderSize"], int)
        or candidate["renderSize"] <= 0
    ):
        raise ReviewLineageError("candidate.renderSize invalid")
    _nonempty(candidate["finalPath"], "candidate.finalPath")
    _nonempty(candidate["renderExportPath"], "candidate.renderExportPath")
    if not isinstance(value["timeline"], Mapping):
        raise ReviewLineageError("candidate timeline must be object")
    if not isinstance(value["exportSpec"], Mapping):
        raise ReviewLineageError("candidate exportSpec must be object")
    material = dict(value)
    digest = material.pop("contextDigest")
    if _sha(material) != digest:
        raise ReviewLineageError("candidate context digest mismatch")
    return _clone(value)


def build_candidate_context(
    *,
    loop_id: str,
    brief_digest: str,
    semantic_analysis_digest: str,
    semantic_directives_digest: str,
    ledger_digest: str,
    source: Mapping[str, Any],
    candidate: Mapping[str, Any],
    timeline: Mapping[str, Any],
    export_spec: Mapping[str, Any],
) -> dict[str, Any]:
    value = {
        "contractVersion": CANDIDATE_CONTEXT_VERSION,
        "loopId": loop_id,
        "briefDigest": brief_digest,
        "semanticAnalysisDigest": semantic_analysis_digest,
        "semanticDirectivesDigest": semantic_directives_digest,
        "ledgerDigest": ledger_digest,
        "source": _clone(source),
        "candidate": _clone(candidate),
        "timeline": _clone(timeline),
        "exportSpec": _clone(export_spec),
        "contextDigest": "",
    }
    material = dict(value)
    material.pop("contextDigest")
    value["contextDigest"] = _sha(material)
    return validate_candidate_context(value)


def _fixture_producer_descriptor() -> dict[str, Any]:
    return {
        "repository": "foto6/video3",
        "branch": "test-fixture-only",
        "sha": "0" * 40,
        "ciRunId": 0,
        "contractVersion": "test_fixture",
        "manifestBlobSha1": "0" * 40,
        "schemaBlobSha1": "0" * 40,
    }


def validate_growth_r25_envelope(
    value: Mapping[str, Any],
    *,
    allow_test_fixture: bool = False,
) -> dict[str, Any]:
    required = {
        "contractVersion",
        "producer",
        "capture",
        "review",
        "evidenceBoundary",
        "envelopeDigest",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ReviewLineageError("R27 external review envelope fields invalid")
    if value["contractVersion"] != ENVELOPE_VERSION:
        raise ReviewLineageError("R27 external review envelope contract mismatch")

    evidence = value["evidenceBoundary"]
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "realExternalCapture",
        "fixture",
        "humanGroundTruth",
        "livePlatformEvidence",
    }:
        raise ReviewLineageError("R27 evidence boundary fields invalid")
    if evidence["humanGroundTruth"] is not False:
        raise ReviewLineageError("external review cannot claim human ground truth")
    if evidence["livePlatformEvidence"] is not False:
        raise ReviewLineageError(
            "model review cannot be promoted to live platform evidence"
        )
    fixture = evidence["fixture"] is True
    real = evidence["realExternalCapture"] is True
    if fixture == real:
        raise ReviewLineageError(
            "review envelope must be exactly one of real capture or fixture"
        )

    producer = value["producer"]
    if not isinstance(producer, Mapping) or set(producer) != {
        "repository",
        "branch",
        "sha",
        "ciRunId",
        "contractVersion",
        "manifestBlobSha1",
        "schemaBlobSha1",
    }:
        raise ReviewLineageError("R27 producer fields invalid")
    if fixture:
        if not allow_test_fixture:
            raise DependencyUnavailable(
                "fixture review cannot satisfy a real Growth R25 capture"
            )
        if producer != _fixture_producer_descriptor():
            raise DependencyDrift("fixture producer descriptor mismatch")
    else:
        if not GROWTH_R25_OBSERVED["creatorReadyEnvelopeAvailable"]:
            raise DependencyUnavailable(
                "Growth R25 Creator-ready envelope is not exact-green/pinned: "
                + GROWTH_R25_OBSERVED["missing"]
            )

    capture = value["capture"]
    if not isinstance(capture, Mapping) or set(capture) != {
        "captureId",
        "captureDigest",
        "conversationId",
        "reviewRequestId",
        "assistantMessageId",
        "bridgeProducerSha",
        "rawResponseSha256",
    }:
        raise ReviewLineageError("R27 capture fields invalid")
    for key in ("captureDigest", "rawResponseSha256"):
        _hex(capture[key], 64, f"capture.{key}")
    _hex(capture["bridgeProducerSha"], 40, "capture.bridgeProducerSha")
    for key in (
        "captureId",
        "conversationId",
        "reviewRequestId",
        "assistantMessageId",
    ):
        _nonempty(capture[key], f"capture.{key}")

    review = value["review"]
    if not isinstance(review, Mapping) or set(review) != {
        "state",
        "roundIndex",
        "source",
        "candidate",
        "criticOutputDigest",
        "handoff",
    }:
        raise ReviewLineageError("R27 review fields invalid")
    state = review["state"]
    if state not in SUPPORTED_STATES:
        raise ReviewLineageError("R27 review state invalid")
    round_index = review["roundIndex"]
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or not 0 <= round_index <= MAX_REEDIT_ROUNDS
    ):
        raise RoundLimitError("R27 review round invalid")
    _hex(review["criticOutputDigest"], 64, "review.criticOutputDigest")
    source = review["source"]
    if not isinstance(source, Mapping) or set(source) != {
        "sourceId",
        "sha256",
        "size",
    }:
        raise ReviewLineageError("R27 review source fields invalid")
    candidate = review["candidate"]
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidateId",
        "renderSha256",
        "renderSize",
        "renderExportSha256",
        "renderProducerSha",
        "attachmentIdentity",
        "attachmentSha256",
        "attachmentSize",
    }:
        raise ReviewLineageError("R27 review candidate fields invalid")
    _nonempty(source["sourceId"], "review.source.sourceId")
    _hex(source["sha256"], 64, "review.source.sha256")
    _nonempty(candidate["candidateId"], "review.candidate.candidateId")
    for key in (
        "renderSha256",
        "renderExportSha256",
        "attachmentSha256",
    ):
        _hex(candidate[key], 64, f"review.candidate.{key}")
    _hex(candidate["renderProducerSha"], 40, "review.candidate.renderProducerSha")
    _nonempty(
        candidate["attachmentIdentity"],
        "review.candidate.attachmentIdentity",
    )
    if (
        candidate["renderSha256"] != candidate["attachmentSha256"]
        or candidate["renderSize"] != candidate["attachmentSize"]
    ):
        raise ReviewLineageError("review render/attachment binding mismatch")
    try:
        handoff = r26.parse_growth_r23_handoff(review["handoff"])
    except r26.RealReviewError as exc:
        raise ReviewLineageError(
            f"nested Growth handoff invalid: {exc}"
        ) from exc
    binding = handoff["binding"]
    if state != handoff["state"]:
        raise ReviewLineageError("R27 state differs from Growth handoff")
    if round_index != handoff["reedit_round"]:
        raise RoundLimitError("R27 round differs from Growth handoff")
    if review["criticOutputDigest"] != binding["critic_output_digest"]:
        raise ReviewLineageError("R27 critic output digest mismatch")
    expected = {
        "source_id": source["sourceId"],
        "source_sha256": source["sha256"],
        "source_size": source["size"],
        "candidate_id": candidate["candidateId"],
        "render_sha256": candidate["renderSha256"],
        "render_size": candidate["renderSize"],
        "render_export_sha256": candidate["renderExportSha256"],
        "media_producer_sha": candidate["renderProducerSha"],
        "attachment_identity": candidate["attachmentIdentity"],
        "attachment_sha256": candidate["attachmentSha256"],
        "attachment_size": candidate["attachmentSize"],
    }
    for binding_key, expected_value in expected.items():
        if binding[binding_key] != expected_value:
            raise ReviewLineageError(
                f"R27 review handoff lineage mismatch: {binding_key}"
            )
    material = dict(value)
    digest = material.pop("envelopeDigest")
    if _sha(material) != digest:
        raise ReviewLineageError("R27 review envelope digest mismatch")
    return _clone(value)


def build_fixture_envelope(
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    parsed = r26.parse_growth_r23_handoff(handoff)
    b = parsed["binding"]
    value = {
        "contractVersion": ENVELOPE_VERSION,
        "producer": _fixture_producer_descriptor(),
        "capture": {
            "captureId": "fixture:" + parsed["handoff_id"],
            "captureDigest": _sha(
                {"handoffDigest": parsed["handoff_digest"], "fixture": True}
            ),
            "conversationId": "fixture-conversation",
            "reviewRequestId": "fixture-review-request",
            "assistantMessageId": "fixture-assistant-message",
            "bridgeProducerSha": "0" * 40,
            "rawResponseSha256": _sha(parsed),
        },
        "review": {
            "state": parsed["state"],
            "roundIndex": parsed["reedit_round"],
            "source": {
                "sourceId": b["source_id"],
                "sha256": b["source_sha256"],
                "size": b["source_size"],
            },
            "candidate": {
                "candidateId": b["candidate_id"],
                "renderSha256": b["render_sha256"],
                "renderSize": b["render_size"],
                "renderExportSha256": b["render_export_sha256"],
                "renderProducerSha": b["media_producer_sha"],
                "attachmentIdentity": b["attachment_identity"],
                "attachmentSha256": b["attachment_sha256"],
                "attachmentSize": b["attachment_size"],
            },
            "criticOutputDigest": b["critic_output_digest"],
            "handoff": parsed,
        },
        "evidenceBoundary": {
            "realExternalCapture": False,
            "fixture": True,
            "humanGroundTruth": False,
            "livePlatformEvidence": False,
        },
        "envelopeDigest": "",
    }
    material = dict(value)
    material.pop("envelopeDigest")
    value["envelopeDigest"] = _sha(material)
    return validate_growth_r25_envelope(value, allow_test_fixture=True)


def validate_review_against_context(
    envelope: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    candidate_root: Path,
) -> None:
    review = envelope["review"]
    source = review["source"]
    candidate = review["candidate"]
    if source != context["source"]:
        raise ReviewLineageError("review source differs from candidate context")
    ctx_candidate = context["candidate"]
    for review_key, context_key in (
        ("candidateId", "candidateId"),
        ("renderSha256", "renderSha256"),
        ("renderSize", "renderSize"),
        ("renderExportSha256", "renderExportSha256"),
        ("renderProducerSha", "renderProducerSha"),
    ):
        if candidate[review_key] != ctx_candidate[context_key]:
            raise ReviewLineageError(
                f"review candidate differs from context: {review_key}"
            )
    if review["roundIndex"] != ctx_candidate["roundIndex"]:
        raise RoundLimitError("review round differs from candidate context")

    root = Path(candidate_root).resolve()
    final_path = (root / ctx_candidate["finalPath"]).resolve()
    export_path = (root / ctx_candidate["renderExportPath"]).resolve()
    try:
        final_path.relative_to(root)
        export_path.relative_to(root)
    except ValueError as exc:
        raise ReviewLineageError("candidate path escapes candidate root") from exc
    if not final_path.is_file() or not export_path.is_file():
        raise ReviewLineageError("candidate bytes/sidecar missing")
    if (
        _file_sha(final_path) != ctx_candidate["renderSha256"]
        or _file_size(final_path) != ctx_candidate["renderSize"]
    ):
        raise ReviewLineageError("candidate MP4 bytes differ from context")
    if _file_sha(export_path) != ctx_candidate["renderExportSha256"]:
        raise ReviewLineageError("candidate render-export bytes differ from context")


def _r19_request(
    *,
    envelope: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    review = envelope["review"]
    candidate = context["candidate"]
    request_id = "r27-" + envelope["envelopeDigest"][:24]
    return {
        "contractVersion": MEDIA_R19["requestContract"],
        "requestId": request_id,
        "handoff": _clone(review["handoff"]),
        "candidate": {
            "candidateId": candidate["candidateId"],
            "source": _clone(context["source"]),
            "finalPath": candidate["finalPath"],
            "renderSha256": candidate["renderSha256"],
            "renderSize": candidate["renderSize"],
            "renderExportPath": candidate["renderExportPath"],
            "renderExportSha256": candidate["renderExportSha256"],
            "renderProducerSha": candidate["renderProducerSha"],
        },
        "timeline": _clone(context["timeline"]),
        "exportSpec": _clone(context["exportSpec"]),
        "expectedPlanDigest": None,
    }


def _parse_r19_log(stdout: str) -> dict[str, Any]:
    lines = [
        line for line in stdout.splitlines()
        if line.startswith("R19_EDITORIAL_REEDIT ")
    ]
    if not lines:
        raise MediaR19Error("Media R19 did not emit result line")
    try:
        value = json.loads(lines[-1].split(" ", 1)[1])
    except Exception as exc:
        raise MediaR19Error("Media R19 result line is not valid JSON") from exc
    if value.get("producerSha") != MEDIA_R19["sha"]:
        raise MediaR19Error("Media R19 result producer SHA mismatch")
    if value.get("status") != "succeeded":
        raise MediaR19Error("Media R19 did not succeed")
    return value


def execute_media_r19_reedit(
    *,
    media_checkout: Path,
    candidate_root: Path,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    verify_media_r19_checkout(media_checkout)
    context = validate_candidate_context(context)
    validate_review_against_context(
        envelope,
        context,
        candidate_root=candidate_root,
    )
    if envelope["review"]["state"] != "targeted_reedit":
        raise MediaR19Error("Media R19 may execute only targeted_reedit")
    round_index = envelope["review"]["roundIndex"]
    if round_index >= MAX_REEDIT_ROUNDS:
        raise RoundLimitError("targeted re-edit requested beyond max round 2")

    root = Path(candidate_root).resolve()
    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    request = _r19_request(envelope=envelope, context=context)
    request_dir = root / ".creator-r27"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{request['requestId']}.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    media_output = request_dir / request["requestId"] / "media-r19"
    command = [
        "node",
        str(
            Path(media_checkout).resolve()
            / "tools"
            / "run-r19-editorial-reedit.mjs"
        ),
        "--request",
        str(request_path),
        "--sandbox-root",
        str(root),
        "--output-dir",
        str(media_output),
    ]
    media_env = dict(os.environ)
    # Media R19 intentionally cross-checks GITHUB_SHA against its own checkout.
    # Creator CI's GITHUB_SHA belongs to video1, so bind only this child process
    # to the exact Media producer without mutating caller/global environment.
    media_env["GITHUB_SHA"] = MEDIA_R19["sha"]
    result = subprocess.run(
        command,
        cwd=Path(media_checkout).resolve(),
        env=media_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=240,
    )
    if result.returncode != 0:
        raise MediaR19Error(
            "Media R19 execution failed: " + result.stderr[-4000:]
        )
    log = _parse_r19_log(result.stdout)

    final_path = media_output / "final.mp4"
    application_path = (
        media_output / "media.editorial_reedit_application.v1.json"
    )
    render_export_path = media_output / "media.render_export.v1.json"
    if not all(
        path.is_file()
        for path in (final_path, application_path, render_export_path)
    ):
        raise MediaR19Error("Media R19 output evidence incomplete")

    application = json.loads(application_path.read_text(encoding="utf-8"))
    render_export = json.loads(render_export_path.read_text(encoding="utf-8"))
    if application.get("contractVersion") != MEDIA_R19["applicationContract"]:
        raise MediaR19Error("Media R19 application contract mismatch")
    if application.get("producer") != {
        "repository": "foto6/video2",
        "sha": MEDIA_R19["sha"],
    }:
        raise MediaR19Error("Media R19 application producer mismatch")
    if application.get("humanQuality") is not False:
        raise MediaR19Error("Media R19 may not claim human quality")
    if application.get("qa", {}).get("technicalPassed") is not True:
        raise MediaR19Error("Media R19 technical QA failed")
    if any(
        row.get("status") != "applied"
        for row in application.get("applications", [])
    ):
        raise MediaR19Error("Media R19 left unsupported directive")
    after_sha = _file_sha(final_path)
    after_size = _file_size(final_path)
    before_sha = context["candidate"]["renderSha256"]
    if after_sha != application["output"]["sha256"]:
        raise MediaR19Error("Media R19 final MP4 SHA differs from application")
    if after_size != application["output"]["size"]:
        raise MediaR19Error("Media R19 final MP4 size differs from application")
    if after_sha == before_sha:
        raise MediaR19Error("actionable re-edit did not change MP4 bytes")
    render_export_sha = _file_sha(render_export_path)
    if render_export_sha != application["output"]["renderExportSha256"]:
        raise MediaR19Error("Media R19 render-export SHA mismatch")
    if render_export.get("producer", {}).get("sha") != MEDIA_R19["sha"]:
        raise MediaR19Error("Media R19 render-export producer mismatch")
    artifact = render_export.get("artifact") or {}
    if artifact.get("sha256") != after_sha or artifact.get("size") != after_size:
        raise MediaR19Error("Media R19 render-export artifact mismatch")

    evidence = {
        "contractVersion": "creator.media_r19_reedit_result.r27.v1",
        "producer": _clone(MEDIA_R19),
        "requestId": request["requestId"],
        "reviewEnvelopeDigest": envelope["envelopeDigest"],
        "growthHandoffDigest": envelope["review"]["handoff"]["handoff_digest"],
        "criticOutputDigest": envelope["review"]["criticOutputDigest"],
        "roundIndex": round_index,
        "before": {
            "candidateId": context["candidate"]["candidateId"],
            "sha256": before_sha,
            "size": context["candidate"]["renderSize"],
            "renderExportSha256": context["candidate"][
                "renderExportSha256"
            ],
        },
        "after": {
            "sha256": after_sha,
            "size": after_size,
            "renderExportSha256": render_export_sha,
            "artifactManifestDigest": artifact.get(
                "artifactManifestDigest"
            ),
            "applicationSidecarSha256": _file_sha(application_path),
            "planDigest": application["planDigest"],
            "timelineDigest": application["outputTimelineDigest"],
            "technicalQaDigest": application["qa"][
                "technicalEvidenceSha256"
            ],
        },
        "applications": application["applications"],
        "replayed": bool(log.get("replayed")),
        "logicalEffects": 0 if log.get("replayed") else 1,
        "humanQuality": False,
        "providerInvoked": False,
        "liveProviderMutation": False,
    }
    # Replay state and logical-effect count describe this invocation, not
    # the durable Media result. Exclude them from the canonical result identity
    # so first execution and exact Media R19 replay bind to the same output.
    durable_result = {
        key: value
        for key, value in evidence.items()
        if key not in {"replayed", "logicalEffects"}
    }
    evidence["resultDigest"] = _sha(durable_result)

    round_out = work_root / f"round-{round_index + 1}"
    round_out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final_path, round_out / "final.mp4")
    shutil.copyfile(
        application_path,
        round_out / "media.editorial_reedit_application.v1.json",
    )
    shutil.copyfile(
        render_export_path,
        round_out / "media.render_export.v1.json",
    )
    (round_out / "creator.media_r19_reedit_result.r27.v1.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "evidence": evidence,
        "application": application,
        "renderExport": render_export,
        "finalPath": str(round_out / "final.mp4"),
        "applicationPath": str(
            round_out / "media.editorial_reedit_application.v1.json"
        ),
        "renderExportPath": str(round_out / "media.render_export.v1.json"),
    }


def build_next_review_boundary(
    *,
    source: Mapping[str, Any],
    prior_context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    media_result: Mapping[str, Any],
) -> dict[str, Any]:
    next_round = envelope["review"]["roundIndex"] + 1
    if next_round > MAX_REEDIT_ROUNDS:
        raise RoundLimitError("next review round exceeds max round 2")
    after = media_result["evidence"]["after"]
    value = {
        "contractVersion": NEXT_REVIEW_VERSION,
        "state": (
            "READY_FOR_MEDIA_R20_DYNAMIC_PACKAGE"
            if MEDIA_R20_OBSERVED["dynamicReviewPackageAvailable"]
            else "BLOCKED_MEDIA_R20_DYNAMIC_PACKAGE_UNAVAILABLE"
        ),
        "roundIndex": next_round,
        "source": _clone(source),
        "candidate": {
            "candidateId": (
                prior_context["candidate"]["candidateId"]
                + f":r19:{next_round}"
            ),
            "renderSha256": after["sha256"],
            "renderSize": after["size"],
            "renderExportSha256": after["renderExportSha256"],
            "renderProducerSha": MEDIA_R19["sha"],
        },
        "priorReviewEnvelopeDigest": envelope["envelopeDigest"],
        "priorCriticOutputDigest": envelope["review"][
            "criticOutputDigest"
        ],
        "mediaR19ResultDigest": media_result["evidence"]["resultDigest"],
        "mediaR20": _clone(MEDIA_R20_OBSERVED),
        "providerInvoked": False,
        "liveProviderMutation": False,
    }
    value["requestDigest"] = _sha(value)
    return value


def _r27_media_render(
    *,
    context: Mapping[str, Any],
    media_result: Mapping[str, Any],
    round_index: int,
) -> dict[str, Any]:
    after = media_result["evidence"]["after"]
    return {
        "contract_version": "creator.media_r19_render.r27.v1",
        "repository": "foto6/video2",
        "commit_sha": MEDIA_R19["sha"],
        "source_class": "provider",
        "source_id": context["source"]["sourceId"],
        "source_sha256": context["source"]["sha256"],
        "candidate_id": (
            context["candidate"]["candidateId"] + f":r19:{round_index}"
        ),
        "round_index": round_index,
        "plan_digest": after["planDigest"],
        "render_sha256": after["sha256"],
        "timeline_digest": after["timelineDigest"],
        "artifact_manifest_digest": after["artifactManifestDigest"],
        "technical_qa": {
            "passed": True,
            "qa_digest": after["technicalQaDigest"],
            "checks": [],
        },
        "render_provenance": {
            "mediaR19ProducerSha": MEDIA_R19["sha"],
            "applicationSidecarSha256": after[
                "applicationSidecarSha256"
            ],
            "renderExportSha256": after["renderExportSha256"],
            "reviewEnvelopeDigest": media_result["evidence"][
                "reviewEnvelopeDigest"
            ],
            "criticOutputDigest": media_result["evidence"][
                "criticOutputDigest"
            ],
        },
        "human_ground_truth": False,
    }


def _validate_r27_media_render(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_source_sha256: str,
    expected_candidate_id: str,
    expected_plan_digest: str,
) -> dict[str, Any]:
    if value.get("contract_version") != "creator.media_r19_render.r27.v1":
        raise r23.EditorPublishHandoffError("R27 Media render contract mismatch")
    if value.get("commit_sha") != MEDIA_R19["sha"]:
        raise r23.EditorPublishHandoffError("R27 Media R19 pin mismatch")
    if value.get("source_id") != expected_source_id:
        raise r23.EditorPublishHandoffError("R27 Media source ID mismatch")
    if value.get("source_sha256") != expected_source_sha256:
        raise r23.EditorPublishHandoffError("R27 Media source SHA mismatch")
    if value.get("candidate_id") != expected_candidate_id:
        raise r23.EditorPublishHandoffError("R27 Media candidate mismatch")
    if value.get("plan_digest") != expected_plan_digest:
        raise r23.EditorPublishHandoffError("R27 Media plan mismatch")
    if value.get("technical_qa", {}).get("passed") is not True:
        raise r23.EditorOutcomeIneligible("R27 Media QA failed")
    if value.get("human_ground_truth") is not False:
        raise r23.EditorPublishHandoffError(
            "R27 Media cannot claim human ground truth"
        )
    return _clone(value)


def _validate_terminal_r27_review(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_render_sha256: str,
) -> dict[str, Any]:
    envelope = validate_growth_r25_envelope(
        value,
        allow_test_fixture=True,
    )
    review = envelope["review"]
    if review["state"] != "winner":
        raise r23.EditorOutcomeIneligible(
            "only terminal real-review winner may publish"
        )
    if review["source"]["sourceId"] != expected_source_id:
        raise r23.EditorPublishHandoffError("R27 terminal source mismatch")
    if review["candidate"]["renderSha256"] != expected_render_sha256:
        raise r23.EditorPublishHandoffError("R27 terminal render mismatch")
    return envelope


def _winner_decision(
    *,
    candidate_id: str,
    render_sha256: str,
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    decision = {
        "contractVersion": r22.DECISION_VERSION,
        "roundIndex": envelope["review"]["roundIndex"],
        "state": "winner",
        "winnerCandidateId": candidate_id,
        "reason": "terminal externally captured Growth R25 review envelope",
        "evaluations": [
            {
                "candidateId": candidate_id,
                "renderSha256": render_sha256,
                "reviewEnvelopeDigest": envelope["envelopeDigest"],
                "criticOutputDigest": envelope["review"][
                    "criticOutputDigest"
                ],
            }
        ],
        "humanLevelQualityClaimed": False,
        "aestheticSuperiorityClaimed": False,
    }
    decision["decisionDigest"] = _sha(decision)
    return decision


def build_final_bundle(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    render: Mapping[str, Any],
    ledger: Ledger,
) -> dict[str, Any]:
    candidate_id = render["candidate_id"]
    decision = _winner_decision(
        candidate_id=candidate_id,
        render_sha256=render["render_sha256"],
        envelope=envelope,
    )
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": candidate_id,
        "roundIndex": envelope["review"]["roundIndex"],
        "render": _clone(render),
        "critic": _clone(envelope),
        "decision": decision,
        "lineage": {
            "loopId": context["loopId"],
            "sourceId": context["source"]["sourceId"],
            "sourceSha256": context["source"]["sha256"],
            "briefDigest": context["briefDigest"],
            "semanticAnalysisDigest": context["semanticAnalysisDigest"],
            "semanticDirectivesDigest": context["semanticDirectivesDigest"],
            "ledgerDigest": ledger.preterminal_digest,
            "growthCriticPin": {
                "growthR25": _clone(GROWTH_R25_OBSERVED),
                "reviewEnvelopeDigest": envelope["envelopeDigest"],
                "criticOutputDigest": envelope["review"][
                    "criticOutputDigest"
                ],
            },
            "mediaRenderExport": {
                "acceptedMediaR19ProducerSha": MEDIA_R19["sha"],
                "applicationContract": MEDIA_R19["applicationContract"],
                "renderExportContract": MEDIA_R19["renderExportContract"],
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def _current_render_from_context(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = context["candidate"]
    return {
        "contract_version": "creator.media_r19_render.r27.v1",
        "repository": "foto6/video2",
        "commit_sha": candidate["renderProducerSha"],
        "source_class": "provider",
        "source_id": context["source"]["sourceId"],
        "source_sha256": context["source"]["sha256"],
        "candidate_id": candidate["candidateId"],
        "round_index": candidate["roundIndex"],
        "plan_digest": _sha(
            {
                "candidateId": candidate["candidateId"],
                "renderSha256": candidate["renderSha256"],
                "roundIndex": candidate["roundIndex"],
            }
        ),
        "render_sha256": candidate["renderSha256"],
        "timeline_digest": _sha(context["timeline"]),
        "artifact_manifest_digest": candidate["renderExportSha256"],
        "technical_qa": {
            "passed": True,
            "qa_digest": _sha(
                {"renderExportSha256": candidate["renderExportSha256"]}
            ),
            "checks": [],
        },
        "render_provenance": {
            "reviewedCandidate": True,
            "renderExportSha256": candidate["renderExportSha256"],
        },
        "human_ground_truth": False,
    }


def run_review_execution(
    *,
    media_checkout: Path,
    growth_r25_checkout: Path,
    candidate_root: Path,
    candidate_context_path: Path,
    review_envelope_path: Path,
    out_dir: Path,
    allow_test_fixture: bool = False,
    inject_lost_ack_after_media: bool = False,
) -> dict[str, Any]:
    media_pin = verify_media_r19_checkout(media_checkout)
    growth_observed = observe_growth_r25_checkout(growth_r25_checkout)
    context = validate_candidate_context(
        json.loads(Path(candidate_context_path).read_text(encoding="utf-8"))
    )
    envelope = validate_growth_r25_envelope(
        json.loads(Path(review_envelope_path).read_text(encoding="utf-8")),
        allow_test_fixture=allow_test_fixture,
    )
    validate_review_against_context(
        envelope,
        context,
        candidate_root=candidate_root,
    )
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out_dir / "real-live-review-ledger.jsonl")
    ledger.append_once(
        "start",
        "r27_started",
        {
            "candidateContextDigest": context["contextDigest"],
            "mediaR19": media_pin,
            "growthR25Observed": growth_observed,
        },
    )
    event_key = "review:" + str(envelope["review"]["roundIndex"])
    review_status = ledger.append_once(
        event_key,
        "growth_r25_external_review",
        {
            "envelopeDigest": envelope["envelopeDigest"],
            "captureId": envelope["capture"]["captureId"],
            "captureDigest": envelope["capture"]["captureDigest"],
            "criticOutputDigest": envelope["review"]["criticOutputDigest"],
            "state": envelope["review"]["state"],
            "roundIndex": envelope["review"]["roundIndex"],
            "renderSha256": envelope["review"]["candidate"][
                "renderSha256"
            ],
        },
    )

    real_review = envelope["evidenceBoundary"]["realExternalCapture"] is True
    state = envelope["review"]["state"]
    if state == "targeted_reedit":
        if envelope["review"]["roundIndex"] >= MAX_REEDIT_ROUNDS:
            raise RoundLimitError("cannot execute a third re-edit round")
        media_key = "media:" + envelope["envelopeDigest"]
        media_already_durable = media_key in ledger.by_key
        result = execute_media_r19_reedit(
            media_checkout=media_checkout,
            candidate_root=candidate_root,
            context=context,
            envelope=envelope,
            work_root=out_dir,
        )
        if (
            inject_lost_ack_after_media
            and not media_already_durable
            and result["evidence"]["logicalEffects"] == 1
        ):
            raise InjectedLostAck(
                "injected lost ACK after exact Media R19 accepted re-edit"
            )
        ledger.append_once(
            media_key,
            "media_r19_reedit",
            {
                "reviewEnvelopeDigest": envelope["envelopeDigest"],
                "criticOutputDigest": envelope["review"][
                    "criticOutputDigest"
                ],
                "beforeSha256": result["evidence"]["before"]["sha256"],
                "afterSha256": result["evidence"]["after"]["sha256"],
                "afterSize": result["evidence"]["after"]["size"],
                "renderExportSha256": result["evidence"]["after"][
                    "renderExportSha256"
                ],
                "applicationSidecarSha256": result["evidence"]["after"][
                    "applicationSidecarSha256"
                ],
                "mediaR19ResultDigest": result["evidence"]["resultDigest"],
            },
        )
        next_review = build_next_review_boundary(
            source=context["source"],
            prior_context=context,
            envelope=envelope,
            media_result=result,
        )
        (out_dir / "next-review-request.json").write_text(
            json.dumps(next_review, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = {
            "contractVersion": CONTRACT_VERSION,
            "state": next_review["state"],
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": real_review,
            "REAL_REEDIT_EXECUTED": real_review,
            "PUBLISH_HANDOFF_READY": False,
            "reviewEnvelopeDigest": envelope["envelopeDigest"],
            "criticOutputDigest": envelope["review"]["criticOutputDigest"],
            "beforeRenderSha256": result["evidence"]["before"]["sha256"],
            "afterRenderSha256": result["evidence"]["after"]["sha256"],
            "afterRenderSize": result["evidence"]["after"]["size"],
            "mediaR19ResultDigest": result["evidence"]["resultDigest"],
            "mediaR19LogicalEffects": result["evidence"]["logicalEffects"],
            "mediaR19Replay": result["evidence"]["replayed"],
            "nextReviewRequestDigest": next_review["requestDigest"],
            "mediaR19": media_pin,
            "growthR25Observed": growth_observed,
            "mediaR20": _clone(MEDIA_R20_OBSERVED),
            "reviewReplay": review_status == "duplicate",
            "mediaReplay": result["evidence"]["replayed"],
            "maxReeditRounds": MAX_REEDIT_ROUNDS,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "humanLevelQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
        report["reportDigest"] = _sha(report)
        (out_dir / "real_live_review_execution.r27.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    if state != "winner":
        terminal_state = (
            "human_review_required" if state == "human_review" else state
        )
        ledger.append_once(
            "terminal",
            "nonpublishable_review_outcome",
            {
                "state": terminal_state,
                "envelopeDigest": envelope["envelopeDigest"],
                "renderSha256": context["candidate"]["renderSha256"],
            },
        )
        report = {
            "contractVersion": CONTRACT_VERSION,
            "state": terminal_state,
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": real_review,
            "REAL_REEDIT_EXECUTED": False,
            "PUBLISH_HANDOFF_READY": False,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "humanLevelQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
        report["reportDigest"] = _sha(report)
        (out_dir / "real_live_review_execution.r27.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    root = Path(candidate_root).resolve()
    candidate_path = (root / context["candidate"]["finalPath"]).resolve()
    final_path = out_dir / "final.mp4"
    shutil.copyfile(candidate_path, final_path)
    final_asset = r21.probe_media(final_path)
    if final_asset.sha256 != context["candidate"]["renderSha256"]:
        raise ReviewLineageError("winner final.mp4 differs from reviewed bytes")
    render = _current_render_from_context(context)
    bundle = build_final_bundle(
        context=context,
        envelope=envelope,
        render=render,
        ledger=ledger,
    )
    (out_dir / "editor-final-bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "contractVersion": CONTRACT_VERSION,
        "state": "WINNER_AWAITING_RELEASE_AUTHORIZATION",
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": real_review,
        "REAL_REEDIT_EXECUTED": False,
        "PUBLISH_HANDOFF_READY": False,
        "winnerCandidateId": bundle["winnerCandidateId"],
        "finalRenderSha256": final_asset.sha256,
        "finalRenderSize": final_asset.size_bytes,
        "bundleDigest": bundle["bundleDigest"],
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    report["reportDigest"] = _sha(report)
    (out_dir / "real_live_review_execution.r27.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def materialize_publish_handoff(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    bundle: Mapping[str, Any],
    final_path: Path,
    release_authorization: Mapping[str, Any],
    platform: str,
    account_id: str,
    destination: str,
    credential_ref: str,
    authorization_ref: str,
    caption: str,
    cta: str,
) -> dict[str, Any]:
    if envelope["review"]["state"] != "winner":
        raise r23.EditorOutcomeIneligible(
            "nonwinner review cannot create publish handoff"
        )
    asset = r21.probe_media(final_path)
    handoff = r23.build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=asset,
        release_authorization=release_authorization,
        platform=platform,
        account_id=account_id,
        destination=destination,
        credential_ref=credential_ref,
        authorization_ref=authorization_ref,
        caption=caption,
        cta=cta,
        allow_synthetic_editor=False,
        media_render_validator=_validate_r27_media_render,
        growth_critic_validator=_validate_terminal_r27_review,
    )
    return handoff


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-live-review-r27")
    sub = parser.add_subparsers(dest="command", required=True)

    ready = sub.add_parser("readiness")
    ready.add_argument("--out")

    run = sub.add_parser("run")
    run.add_argument("--media-r19-checkout", required=True)
    run.add_argument("--growth-r25-checkout", required=True)
    run.add_argument("--candidate-root", required=True)
    run.add_argument("--candidate-context", required=True)
    run.add_argument("--review-envelope", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--allow-test-fixture", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        report = readiness_report()
        if args.out:
            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, sort_keys=True))
        return 2

    try:
        report = run_review_execution(
            media_checkout=Path(args.media_r19_checkout),
            growth_r25_checkout=Path(args.growth_r25_checkout),
            candidate_root=Path(args.candidate_root),
            candidate_context_path=Path(args.candidate_context),
            review_envelope_path=Path(args.review_envelope),
            out_dir=Path(args.out),
            allow_test_fixture=bool(args.allow_test_fixture),
        )
    except Exception as exc:
        blocked = {
            "contractVersion": CONTRACT_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": False,
            "REAL_REEDIT_EXECUTED": False,
            "PUBLISH_HANDOFF_READY": False,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "humanLevelQualityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
