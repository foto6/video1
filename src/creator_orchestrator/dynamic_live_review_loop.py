from __future__ import annotations

import argparse
import copy
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
from . import live_review_execution as r27
from . import publish_execution as r21
from . import real_review_closed_loop as r26

CONTRACT_VERSION = "creator.dynamic_live_review_loop.r28.v1"
LEDGER_VERSION = "creator.dynamic_live_review_loop_ledger.r28.v1"
CONTEXT_VERSION = "creator.dynamic_review_candidate_context.r28.v1"
AUTHORITY_VERSION = "creator.dynamic_review_authority.r28.v1"
MEDIA_RESULT_VERSION = "creator.media_r20_reedit_result.r28.v1"
PACKAGE_RESULT_VERSION = "creator.media_r20_review_package_result.r28.v1"
REPORT_VERSION = "creator.dynamic_live_review_loop.r28.readiness.v1"
CREATOR_R27_BASE_SHA = "6efc98006f9b0d79b0dd5d5ac070fbc9d9f423f9"
MAX_REEDIT_ROUNDS = 2

GROWTH_R25_AUTHORITY = {
    "authorityVersion": AUTHORITY_VERSION,
    "family": "growth_r25_r26_creator_external_review",
    "repository": "foto6/video3",
    "producerSha": "2c441ebaa017c7da72461316401aeaf445e3d6e5",
    "ciRunId": 36988158233,
    "envelopeContract": "growth.creator_external_review_envelope.r25.v1",
    "ingestContract": "growth.real_capture_ingest.r25.v1",
    "ingestContractBlobSha1": "86a2fe264148a2bf3572158c2a44d66be93ec3af",
    "ingestSchemaBlobSha1": "b7f8663080b9058ea7db23d4123b8d00bd59e3d9",
    "ingestImplementationBlobSha1": "ffd0233715e68d8f4374755942bf5de65ac3cfec",
    "handoffContract": "growth.creator_reedit_handoff.v1",
    "handoffContractBlobSha1": "ced853aad722aad4c7a88e9a41756baa1b2892a6",
    "handoffSchemaBlobSha1": "ba9ada04488760147136dcaaf012206405c04653",
    "handoffAdapterAuthorityBlobSha1": "a4f5b1219c874ae13c05651e584dd7fbf5d4449a",
    "currentAdapterBlobSha1": "c358d31866cdea842202fef6add992d102a58f90",
    "testFixture": False,
}

MEDIA_R20_AUTHORITY = {
    "authorityVersion": AUTHORITY_VERSION,
    "family": "media_r19_r20_editorial_dynamic_review",
    "repository": "foto6/video2",
    "producerSha": "b22174db3c772a49a21fb9f8b1d40828bf258005",
    "ciRunId": 36988788032,
    "applicationContract": "media.editorial_reedit_application.v1",
    "applicationContractBlobSha1": "6b3350c5f1524fe49a49d5637514e2fb1a808bcf",
    "applicationManifestBlobSha1": "502c32253d370e9b4e3d53f4a70de317f89dd21b",
    "applicationSchemaBlobSha1": "7cabf91f08ae11b68cc4a7eec88d358a46730289",
    "r19ImplementationBlobSha1": "8110a086b5b319bd2601860845c6afbf97681921",
    "r19RunnerBlobSha1": "7dbec612621aa42baaf2946cdac61d070e3ff41f",
    "renderExportContract": "media.render_export.v1",
    "renderExportManifestBlobSha1": "945acb01ff0269d89b91463aa8d862f500e055b2",
    "renderExportSchemaBlobSha1": "6353d32d785a2a1f1441bac4cfd0271b46b41d4a",
    "dynamicPackageContract": "media.dynamic_review_package.r20.v1",
    "dynamicRequestContract": "media.dynamic_review_request.r20.v1",
    "dynamicBridgeHandoffContract": "media.bridge_live_review_handoff.r20.v1",
    "dynamicContractBlobSha1": "bf650ad1552686d830965edad3fd62451ec0ec22",
    "dynamicManifestBlobSha1": "da4af21cae8dffacb9cc303576fb08cb671e02ce",
    "dynamicSchemaBlobSha1": "680aa69dfb595f31e93fb2bdfe0fdae2ac5ca25b",
    "dynamicImplementationBlobSha1": "cebaa1083d121844b5f7d5a78196d201f860d8a8",
    "dynamicRunnerBlobSha1": "33c742f1e0314e462fb3e97337bf82883ec80f00",
    "testFixture": False,
}

BRIDGE_R29_OBSERVED = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "ed9a35290f94607d7577f1ee9301de1bb44334f2",
    "ciRunId": 36989658042,
    "captureContract": "bridge.existing_chat_video_review_capture.v1",
    "implementationBlobSha1": "b67fccc81c4e06262222ee15d0bc20a39bd23c2f",
    "contractTestBlobSha1": "cb09cd3e4c2836d59784d94c4f10f6a2d6d0844f",
    "dynamicR30AuthorityAvailable": False,
}

MISSING_DYNAMIC_CAPTURE_AUTHORITY = {
    "growthR26": {
        "requiredFamily": "growth.creator_external_review_envelope.r26.*",
        "requiredEvidence": [
            "exact producer SHA",
            "exact-head successful CI run",
            "exact envelope/ingest contract",
            "exact contract/schema/implementation blob IDs",
        ],
        "available": False,
    },
    "bridgeR30": {
        "requiredFamily": "bridge dynamic round-by-round video review capture R30",
        "requiredEvidence": [
            "exact producer SHA",
            "exact-head successful CI run",
            "exact request/capture contracts",
            "exact contract/implementation blob IDs",
        ],
        "available": False,
    },
}

SUPPORTED_STATES = {
    "targeted_reedit",
    "winner",
    "tie",
    "insufficient_evidence",
    "human_review",
}


class R28Error(ValueError):
    pass


class AuthorityError(R28Error):
    pass


class AuthorityDrift(AuthorityError):
    pass


class ReviewLineageError(R28Error):
    pass


class ReviewReplayConflict(R28Error):
    pass


class RoundRegression(R28Error):
    pass


class MissingMediaApplicationEvidence(R28Error):
    pass


class MediaR20Error(R28Error):
    pass


class PackageDigestDrift(R28Error):
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
        raise R28Error(f"{field} must be lowercase {size}-hex")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R28Error(f"{field} must be non-empty")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R28Error(f"{field} must be a positive integer")
    return value


def _git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(path).resolve(),
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


def _profile_digest(profile: Mapping[str, Any]) -> str:
    return _sha(profile)


def validate_growth_authority(profile: Mapping[str, Any]) -> dict[str, Any]:
    required = set(GROWTH_R25_AUTHORITY)
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise AuthorityError("Growth authority profile fields mismatch")
    if profile["authorityVersion"] != AUTHORITY_VERSION:
        raise AuthorityError("Growth authority version mismatch")
    if profile["family"] != "growth_r25_r26_creator_external_review":
        raise AuthorityError("Growth authority family mismatch")
    if profile["repository"] != "foto6/video3":
        raise AuthorityError("Growth authority repository mismatch")
    _hex(profile["producerSha"], 40, "growth.producerSha")
    _positive_int(profile["ciRunId"], "growth.ciRunId")
    for key in (
        "ingestContractBlobSha1",
        "ingestSchemaBlobSha1",
        "ingestImplementationBlobSha1",
        "handoffContractBlobSha1",
        "handoffSchemaBlobSha1",
        "handoffAdapterAuthorityBlobSha1",
        "currentAdapterBlobSha1",
    ):
        _hex(profile[key], 40, f"growth.{key}")
    if profile["envelopeContract"] not in {
        "growth.creator_external_review_envelope.r25.v1",
    }:
        raise AuthorityError(
            "unsupported Growth R25/R26 envelope contract; exact parser required"
        )
    if profile["ingestContract"] != "growth.real_capture_ingest.r25.v1":
        raise AuthorityError("Growth ingest contract mismatch")
    if profile["handoffContract"] != "growth.creator_reedit_handoff.v1":
        raise AuthorityError("Growth handoff contract mismatch")
    if not isinstance(profile["testFixture"], bool):
        raise AuthorityError("growth.testFixture must be boolean")
    return _clone(profile)


def validate_media_authority(profile: Mapping[str, Any]) -> dict[str, Any]:
    required = set(MEDIA_R20_AUTHORITY)
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise AuthorityError("Media authority profile fields mismatch")
    if profile["authorityVersion"] != AUTHORITY_VERSION:
        raise AuthorityError("Media authority version mismatch")
    if profile["family"] != "media_r19_r20_editorial_dynamic_review":
        raise AuthorityError("Media authority family mismatch")
    if profile["repository"] != "foto6/video2":
        raise AuthorityError("Media authority repository mismatch")
    _hex(profile["producerSha"], 40, "media.producerSha")
    _positive_int(profile["ciRunId"], "media.ciRunId")
    for key in (
        "applicationContractBlobSha1",
        "applicationManifestBlobSha1",
        "applicationSchemaBlobSha1",
        "r19ImplementationBlobSha1",
        "r19RunnerBlobSha1",
        "renderExportManifestBlobSha1",
        "renderExportSchemaBlobSha1",
        "dynamicContractBlobSha1",
        "dynamicManifestBlobSha1",
        "dynamicSchemaBlobSha1",
        "dynamicImplementationBlobSha1",
        "dynamicRunnerBlobSha1",
    ):
        _hex(profile[key], 40, f"media.{key}")
    if profile["applicationContract"] != "media.editorial_reedit_application.v1":
        raise AuthorityError("Media application contract mismatch")
    if profile["renderExportContract"] != "media.render_export.v1":
        raise AuthorityError("Media render-export contract mismatch")
    if profile["dynamicPackageContract"] != "media.dynamic_review_package.r20.v1":
        raise AuthorityError("Media dynamic package contract mismatch")
    if profile["dynamicRequestContract"] != "media.dynamic_review_request.r20.v1":
        raise AuthorityError("Media dynamic request contract mismatch")
    if not isinstance(profile["testFixture"], bool):
        raise AuthorityError("media.testFixture must be boolean")
    return _clone(profile)


def verify_growth_checkout(
    checkout: Path,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    profile = validate_growth_authority(profile)
    root = Path(checkout).resolve()
    if _git_head(root) != profile["producerSha"]:
        raise AuthorityDrift("Growth checkout producer SHA drift")
    checks = {
        "ingestContractBlobSha1": (
            root / "conformance/growth.real_capture_ingest.r25.v1/contract.json"
        ),
        "ingestSchemaBlobSha1": (
            root / "conformance/growth.real_capture_ingest.r25.v1/schema.json"
        ),
        "ingestImplementationBlobSha1": (
            root / "growth_analytics/real_capture_r25.py"
        ),
        "handoffContractBlobSha1": (
            root / "conformance/growth.creator_reedit_handoff.v1/contract.json"
        ),
        "handoffSchemaBlobSha1": (
            root / "conformance/growth.creator_reedit_handoff.v1/schema.json"
        ),
        "currentAdapterBlobSha1": (
            root / "growth_analytics/critic_reedit_adapter.py"
        ),
    }
    observed = {}
    for key, path in checks.items():
        if not path.is_file():
            raise AuthorityDrift(f"Growth authority file missing: {path}")
        observed[key] = _git_blob_sha(path)
        if observed[key] != profile[key]:
            raise AuthorityDrift(f"Growth authority blob drift: {key}")
    return {
        "profile": profile,
        "profileDigest": _profile_digest(profile),
        "checkoutSha": _git_head(root),
        "observedBlobs": observed,
    }


def verify_media_checkout(
    checkout: Path,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    profile = validate_media_authority(profile)
    root = Path(checkout).resolve()
    if _git_head(root) != profile["producerSha"]:
        raise AuthorityDrift("Media checkout producer SHA drift")
    checks = {
        "applicationContractBlobSha1": (
            root / "conformance/media.editorial_reedit_application.v1/contract.json"
        ),
        "applicationManifestBlobSha1": (
            root / "conformance/media.editorial_reedit_application.v1/manifest.json"
        ),
        "applicationSchemaBlobSha1": (
            root / "conformance/media.editorial_reedit_application.v1/schema.json"
        ),
        "r19ImplementationBlobSha1": root / "src/editorial-reedit-r19.js",
        "r19RunnerBlobSha1": root / "tools/run-r19-editorial-reedit.mjs",
        "renderExportManifestBlobSha1": (
            root / "conformance/media.render_export.v1/manifest.json"
        ),
        "renderExportSchemaBlobSha1": (
            root / "conformance/media.render_export.v1/schema.json"
        ),
        "dynamicContractBlobSha1": (
            root / "conformance/media.dynamic_review_package.r20.v1/contract.json"
        ),
        "dynamicManifestBlobSha1": (
            root / "conformance/media.dynamic_review_package.r20.v1/manifest.json"
        ),
        "dynamicSchemaBlobSha1": (
            root / "conformance/media.dynamic_review_package.r20.v1/schema.json"
        ),
        "dynamicImplementationBlobSha1": root / "src/dynamic-review-r20.js",
        "dynamicRunnerBlobSha1": root / "tools/build-r20-dynamic-review.mjs",
    }
    observed = {}
    for key, path in checks.items():
        if not path.is_file():
            raise AuthorityDrift(f"Media authority file missing: {path}")
        observed[key] = _git_blob_sha(path)
        if observed[key] != profile[key]:
            raise AuthorityDrift(f"Media authority blob drift: {key}")
    return {
        "profile": profile,
        "profileDigest": _profile_digest(profile),
        "checkoutSha": _git_head(root),
        "observedBlobs": observed,
    }


def _validate_editorial_descriptor(
    value: Mapping[str, Any] | None,
    *,
    round_index: int,
) -> dict[str, Any] | None:
    if value is None:
        if round_index > 0:
            raise MissingMediaApplicationEvidence(
                "re-edit candidate requires Media application evidence"
            )
        return None
    required = {
        "path",
        "fileSha256",
        "digest",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise MissingMediaApplicationEvidence(
            "editorialApplication fields mismatch"
        )
    for key in ("fileSha256", "digest"):
        _hex(value[key], 64, f"editorialApplication.{key}")
    _nonempty(value["path"], "editorialApplication.path")
    if round_index == 0:
        raise MissingMediaApplicationEvidence(
            "round-0 candidate cannot carry re-edit application evidence"
        )
    return _clone(value)


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
        raise ReviewLineageError("R28 candidate context fields mismatch")
    if value["contractVersion"] != CONTEXT_VERSION:
        raise ReviewLineageError("R28 candidate context contract mismatch")
    _nonempty(value["loopId"], "context.loopId")
    for key in (
        "briefDigest",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
        "ledgerDigest",
    ):
        _hex(value[key], 64, f"context.{key}")
    source = value["source"]
    if not isinstance(source, Mapping) or set(source) != {
        "sourceId", "sha256", "size", "path"
    }:
        raise ReviewLineageError("R28 source fields mismatch")
    _nonempty(source["sourceId"], "source.sourceId")
    _hex(source["sha256"], 64, "source.sha256")
    _positive_int(source["size"], "source.size")
    _nonempty(source["path"], "source.path")
    candidate = value["candidate"]
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidateId",
        "roundIndex",
        "finalPath",
        "renderSha256",
        "renderSize",
        "renderExportPath",
        "renderExportSha256",
        "renderExportDigest",
        "renderProducerSha",
        "editorialApplication",
    }:
        raise ReviewLineageError("R28 candidate fields mismatch")
    _nonempty(candidate["candidateId"], "candidate.candidateId")
    round_index = candidate["roundIndex"]
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or not 0 <= round_index <= MAX_REEDIT_ROUNDS
    ):
        raise RoundRegression("candidate roundIndex invalid")
    for key in (
        "renderSha256",
        "renderExportSha256",
        "renderExportDigest",
    ):
        _hex(candidate[key], 64, f"candidate.{key}")
    _hex(candidate["renderProducerSha"], 40, "candidate.renderProducerSha")
    _positive_int(candidate["renderSize"], "candidate.renderSize")
    _nonempty(candidate["finalPath"], "candidate.finalPath")
    _nonempty(candidate["renderExportPath"], "candidate.renderExportPath")
    _validate_editorial_descriptor(
        candidate["editorialApplication"],
        round_index=round_index,
    )
    if not isinstance(value["timeline"], Mapping):
        raise ReviewLineageError("timeline must be object")
    if not isinstance(value["exportSpec"], Mapping):
        raise ReviewLineageError("exportSpec must be object")
    material = dict(value)
    digest = material.pop("contextDigest")
    _hex(digest, 64, "contextDigest")
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
        "contractVersion": CONTEXT_VERSION,
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
            if set(event) != {
                "ledgerVersion", "sequence", "eventKey",
                "eventType", "payload", "eventDigest"
            }:
                raise R28Error("R28 ledger fields mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if (
                event["ledgerVersion"] != LEDGER_VERSION
                or _sha(material) != digest
                or event["sequence"] != len(self.events) + 1
            ):
                raise R28Error("R28 ledger corruption")
            key = event["eventKey"]
            if key in self.by_key:
                raise R28Error("R28 duplicate durable key")
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


def _growth_event_producer(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "repository": profile["repository"],
        "sha": profile["producerSha"],
        "ciRunId": profile["ciRunId"],
        "contract": profile["handoffContract"],
        "adapterContract": "growth.web_video_critic_reedit_adapter.v1",
        "contractBlobSha1": profile["handoffContractBlobSha1"],
        "schemaBlobSha1": profile["handoffSchemaBlobSha1"],
        "adapterBlobSha1": profile["handoffAdapterAuthorityBlobSha1"],
    }


def validate_growth_external_review(
    value: Mapping[str, Any],
    *,
    growth_profile: Mapping[str, Any],
    expected_bridge_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = validate_growth_authority(growth_profile)
    required = {
        "contract_version",
        "envelope_id",
        "envelope_digest",
        "creator_event",
        "growth_r25",
        "bridge_r29",
        "capture",
        "handoff",
        "evidence_boundary",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ReviewLineageError("Growth external-review envelope fields mismatch")
    if value["contract_version"] != profile["envelopeContract"]:
        raise AuthorityDrift("Growth envelope contract/profile mismatch")
    growth = value["growth_r25"]
    if not isinstance(growth, Mapping) or set(growth) != {
        "repository",
        "producer_sha",
        "ci_run_id",
        "starting_r24_sha",
        "ingest_contract",
    }:
        raise ReviewLineageError("Growth envelope producer fields mismatch")
    if (
        growth["repository"] != profile["repository"]
        or growth["producer_sha"] != profile["producerSha"]
        or growth["ci_run_id"] != profile["ciRunId"]
        or growth["ingest_contract"] != profile["ingestContract"]
    ):
        raise AuthorityDrift("Growth external-review producer authority drift")
    _hex(growth["starting_r24_sha"], 40, "growth.starting_r24_sha")

    event = value["creator_event"]
    if not isinstance(event, Mapping) or set(event) != {
        "contractVersion",
        "producer",
        "captureMode",
        "reviewIdentity",
        "handoff",
    }:
        raise ReviewLineageError("Growth Creator event fields mismatch")
    if event["contractVersion"] != "creator.external_real_review_event.r26.v1":
        raise ReviewLineageError("Growth Creator event contract mismatch")
    if event["captureMode"] != "external_live_review":
        raise ReviewLineageError("Growth envelope is not external_live_review")
    if event["producer"] != _growth_event_producer(profile):
        raise AuthorityDrift("Growth Creator event producer/blob authority drift")

    handoff = r26.parse_growth_r23_handoff(event["handoff"])
    if handoff["handoff_id"] != event["reviewIdentity"]:
        raise ReviewLineageError("Growth review identity mismatch")
    summary = value["handoff"]
    if not isinstance(summary, Mapping) or set(summary) != {
        "candidate_label",
        "handoff_id",
        "handoff_digest",
        "state",
        "reedit_round",
        "source_id",
        "source_sha256",
        "render_sha256",
        "attachment_sha256",
        "attachment_size",
    }:
        raise ReviewLineageError("Growth envelope handoff summary mismatch")
    binding = handoff["binding"]
    expected_summary = {
        "handoff_id": handoff["handoff_id"],
        "handoff_digest": handoff["handoff_digest"],
        "state": handoff["state"],
        "reedit_round": handoff["reedit_round"],
        "source_id": binding["source_id"],
        "source_sha256": binding["source_sha256"],
        "render_sha256": binding["render_sha256"],
        "attachment_sha256": binding["attachment_sha256"],
        "attachment_size": binding["attachment_size"],
    }
    for key, expected in expected_summary.items():
        if summary[key] != expected:
            raise ReviewLineageError(
                f"Growth envelope handoff summary drift: {key}"
            )
    if summary["candidate_label"] not in {"A", "B"}:
        raise ReviewLineageError("Growth candidate label invalid")

    bridge = value["bridge_r29"]
    if not isinstance(bridge, Mapping):
        raise ReviewLineageError("Bridge authority must be object")
    if expected_bridge_authority is not None and bridge != expected_bridge_authority:
        raise AuthorityDrift("Bridge capture authority does not match runtime profile")
    if bridge.get("repository") != "foto6/WebAIBridge":
        raise AuthorityDrift("Bridge repository mismatch")
    _hex(bridge.get("producer_sha"), 40, "bridge.producer_sha")
    if bridge.get("capture_contract") != (
        "bridge.existing_chat_video_review_capture.v1"
    ):
        raise AuthorityDrift("Bridge capture contract mismatch")
    _hex(bridge.get("contract_blob_sha1"), 40, "bridge.contract_blob_sha1")
    _hex(
        bridge.get("implementation_blob_sha1"),
        40,
        "bridge.implementation_blob_sha1",
    )

    capture = value["capture"]
    if not isinstance(capture, Mapping) or set(capture) != {
        "capture_id",
        "capture_digest",
        "assistant_response_digest",
        "conversation_id",
        "request_id",
    }:
        raise ReviewLineageError("Growth capture fields mismatch")
    _nonempty(capture["capture_id"], "capture.capture_id")
    _hex(capture["capture_digest"], 64, "capture.capture_digest")
    _hex(
        capture["assistant_response_digest"],
        64,
        "capture.assistant_response_digest",
    )
    _nonempty(capture["conversation_id"], "capture.conversation_id")
    _nonempty(capture["request_id"], "capture.request_id")

    if value["evidence_boundary"] != {
        "model_evidence": True,
        "human_ground_truth": False,
        "human_parity_inferred": False,
        "provider_mutation": False,
    }:
        raise ReviewLineageError("Growth evidence boundary drift")
    _nonempty(value["envelope_id"], "envelope_id")
    _hex(value["envelope_digest"], 64, "envelope_digest")
    expected_id = "gr25ce1:" + _sha(
        {
            "growth_producer_sha": profile["producerSha"],
            "capture_digest": capture["capture_digest"],
            "handoff_digest": summary["handoff_digest"],
            "reedit_round": summary["reedit_round"],
        }
    )
    if value["envelope_id"] != expected_id:
        raise ReviewLineageError("Growth envelope identity mismatch")
    material = dict(value)
    material["envelope_digest"] = ""
    if value["envelope_digest"] != _sha(material):
        raise ReviewLineageError("Growth envelope digest mismatch")
    if handoff["state"] not in SUPPORTED_STATES:
        raise ReviewLineageError("Growth handoff state unsupported")
    return _clone(value)


def normalize_review(
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    handoff = envelope["creator_event"]["handoff"]
    binding = handoff["binding"]
    return {
        "state": handoff["state"],
        "roundIndex": handoff["reedit_round"],
        "source": {
            "sourceId": binding["source_id"],
            "sha256": binding["source_sha256"],
            "size": binding["source_size"],
        },
        "candidate": {
            "candidateId": binding["candidate_id"],
            "renderSha256": binding["render_sha256"],
            "renderSize": binding["render_size"],
            "renderExportSha256": binding["render_export_sha256"],
            "renderProducerSha": binding["media_producer_sha"],
            "attachmentIdentity": binding["attachment_identity"],
            "attachmentSha256": binding["attachment_sha256"],
            "attachmentSize": binding["attachment_size"],
        },
        "criticOutputDigest": binding["critic_output_digest"],
        "handoff": _clone(handoff),
        "captureId": envelope["capture"]["capture_id"],
        "captureDigest": envelope["capture"]["capture_digest"],
        "envelopeDigest": envelope["envelope_digest"],
    }


def validate_review_against_context(
    review: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    candidate_root: Path,
) -> None:
    context = validate_candidate_context(context)
    source = review["source"]
    if source != {
        "sourceId": context["source"]["sourceId"],
        "sha256": context["source"]["sha256"],
        "size": context["source"]["size"],
    }:
        raise ReviewLineageError("review source differs from candidate context")
    candidate = context["candidate"]
    expected = {
        "candidateId": candidate["candidateId"],
        "renderSha256": candidate["renderSha256"],
        "renderSize": candidate["renderSize"],
        "renderExportSha256": candidate["renderExportSha256"],
        "renderProducerSha": candidate["renderProducerSha"],
    }
    for key, expected_value in expected.items():
        if review["candidate"][key] != expected_value:
            raise ReviewLineageError(
                f"review candidate lineage mismatch: {key}"
            )
    if review["roundIndex"] != candidate["roundIndex"]:
        raise RoundRegression("review round regressed or skipped")
    if (
        review["candidate"]["attachmentSha256"] != candidate["renderSha256"]
        or review["candidate"]["attachmentSize"] != candidate["renderSize"]
    ):
        raise ReviewLineageError("review attachment/render bytes mismatch")
    root = Path(candidate_root).resolve()
    for rel, sha, size in (
        (
            candidate["finalPath"],
            candidate["renderSha256"],
            candidate["renderSize"],
        ),
        (
            candidate["renderExportPath"],
            candidate["renderExportSha256"],
            None,
        ),
    ):
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ReviewLineageError("candidate path escapes root") from exc
        if not path.is_file():
            raise ReviewLineageError("candidate evidence file missing")
        if _file_sha(path) != sha:
            raise ReviewLineageError("candidate evidence hash drift")
        if size is not None and _file_size(path) != size:
            raise ReviewLineageError("candidate render size drift")
    editorial = candidate["editorialApplication"]
    if editorial is not None:
        path = (root / editorial["path"]).resolve()
        if not path.is_file():
            raise MissingMediaApplicationEvidence(
                "editorial application sidecar missing"
            )
        if _file_sha(path) != editorial["fileSha256"]:
            raise MissingMediaApplicationEvidence(
                "editorial application sidecar hash drift"
            )


def _r19_request(
    *,
    review: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = context["candidate"]
    return {
        "contractVersion": "media.editorial_reedit_request.r19.v1",
        "requestId": "r28-" + review["envelopeDigest"][:24],
        "handoff": _clone(review["handoff"]),
        "candidate": {
            "candidateId": candidate["candidateId"],
            "source": {
                "sourceId": context["source"]["sourceId"],
                "sha256": context["source"]["sha256"],
                "size": context["source"]["size"],
            },
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


def _parse_media_log(stdout: str, producer_sha: str) -> dict[str, Any]:
    lines = [
        line for line in stdout.splitlines()
        if line.startswith("R19_EDITORIAL_REEDIT ")
    ]
    if not lines:
        raise MediaR20Error("Media R19/R20 did not emit result line")
    try:
        value = json.loads(lines[-1].split(" ", 1)[1])
    except Exception as exc:
        raise MediaR20Error("Media result line invalid") from exc
    if value.get("producerSha") != producer_sha:
        raise MediaR20Error("Media result producer SHA mismatch")
    if value.get("status") != "succeeded":
        raise MediaR20Error("Media re-edit did not succeed")
    return value


def _media_semantic_digest(
    media_checkout: Path,
    file_path: Path,
    kind: str,
) -> str:
    export_name = (
        "renderExportDigest"
        if kind == "render"
        else "fingerprint"
    )
    script = (
        "import fs from 'node:fs';"
        "import * as media from "
        + json.dumps((Path(media_checkout).resolve() / "src/index.js").as_uri())
        + ";"
        "const value=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        f"console.log(media.{export_name}(value));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(Path(file_path).resolve())],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise MediaR20Error(
            "Media semantic digest helper failed: " + result.stderr[-2000:]
        )
    digest = result.stdout.strip().splitlines()[-1]
    return _hex(digest, 64, f"Media {kind} semantic digest")


def execute_media_reedit(
    *,
    media_checkout: Path,
    media_profile: Mapping[str, Any],
    candidate_root: Path,
    context: Mapping[str, Any],
    review: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    verify_media_checkout(media_checkout, media_profile)
    context = validate_candidate_context(context)
    validate_review_against_context(
        review,
        context,
        candidate_root=candidate_root,
    )
    if review["state"] != "targeted_reedit":
        raise MediaR20Error("Media re-edit requires targeted_reedit")
    if review["roundIndex"] >= MAX_REEDIT_ROUNDS:
        raise RoundRegression("targeted re-edit exceeds max two rounds")
    root = Path(candidate_root).resolve()
    request = _r19_request(review=review, context=context)
    request_dir = root / ".creator-r28"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{request['requestId']}.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    media_output = request_dir / request["requestId"] / "media-r20"
    env = dict(os.environ)
    env["GITHUB_SHA"] = media_profile["producerSha"]
    result = subprocess.run(
        [
            "node",
            str(
                Path(media_checkout).resolve()
                / "tools/run-r19-editorial-reedit.mjs"
            ),
            "--request",
            str(request_path),
            "--sandbox-root",
            str(root),
            "--output-dir",
            str(media_output),
        ],
        cwd=Path(media_checkout).resolve(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=240,
    )
    if result.returncode != 0:
        raise MediaR20Error(
            "Media R19/R20 re-edit failed: " + result.stderr[-5000:]
        )
    log = _parse_media_log(result.stdout, media_profile["producerSha"])
    final_path = media_output / "final.mp4"
    app_path = media_output / "media.editorial_reedit_application.v1.json"
    export_path = media_output / "media.render_export.v1.json"
    if not all(p.is_file() for p in (final_path, app_path, export_path)):
        raise MissingMediaApplicationEvidence(
            "Media R19/R20 output sidecars incomplete"
        )
    application = json.loads(app_path.read_text(encoding="utf-8"))
    render_export = json.loads(export_path.read_text(encoding="utf-8"))
    if application.get("contractVersion") != media_profile["applicationContract"]:
        raise MediaR20Error("Media application contract drift")
    if application.get("producer") != {
        "repository": media_profile["repository"],
        "sha": media_profile["producerSha"],
    }:
        raise AuthorityDrift("Media application producer drift")
    if application.get("qa", {}).get("technicalPassed") is not True:
        raise MediaR20Error("Media technical QA failed")
    applications = application.get("applications")
    if not isinstance(applications, list) or not applications:
        raise MissingMediaApplicationEvidence(
            "Media application sidecar has no applied directives"
        )
    if any(row.get("status") != "applied" for row in applications):
        raise MissingMediaApplicationEvidence(
            "Media application contains unsupported directive"
        )
    before_sha = context["candidate"]["renderSha256"]
    after_sha = _file_sha(final_path)
    after_size = _file_size(final_path)
    if (
        application.get("output", {}).get("sha256") != after_sha
        or application.get("output", {}).get("size") != after_size
        or after_sha == before_sha
    ):
        raise MediaR20Error("Media output byte lineage mismatch")
    export_file_sha = _file_sha(export_path)
    if application["output"]["renderExportSha256"] != export_file_sha:
        raise MediaR20Error("Media render-export file SHA drift")
    artifact = render_export.get("artifact") or {}
    if (
        render_export.get("producer", {}).get("sha")
        != media_profile["producerSha"]
        or artifact.get("sha256") != after_sha
        or artifact.get("size") != after_size
    ):
        raise MediaR20Error("Media render-export artifact lineage mismatch")
    render_digest = _media_semantic_digest(
        media_checkout, export_path, "render"
    )
    app_digest = _media_semantic_digest(
        media_checkout, app_path, "application"
    )
    next_round = review["roundIndex"] + 1
    next_candidate_id = (
        context["candidate"]["candidateId"]
        + ":r28:"
        + str(next_round)
        + ":"
        + after_sha[:16]
    )
    round_root = Path(out_dir).resolve() / f"round-{next_round}"
    round_root.mkdir(parents=True, exist_ok=True)
    copied_final = round_root / "final.mp4"
    copied_app = round_root / "media.editorial_reedit_application.v1.json"
    copied_export = round_root / "media.render_export.v1.json"
    shutil.copyfile(final_path, copied_final)
    shutil.copyfile(app_path, copied_app)
    shutil.copyfile(export_path, copied_export)
    sandbox_root = Path(candidate_root).resolve()
    for p in (copied_final, copied_app, copied_export):
        try:
            p.resolve().relative_to(sandbox_root)
        except ValueError as exc:
            raise MediaR20Error(
                "R28 output must remain under candidate sandbox root"
            ) from exc
    evidence = {
        "contractVersion": MEDIA_RESULT_VERSION,
        "producerAuthorityDigest": _profile_digest(media_profile),
        "reviewEnvelopeDigest": review["envelopeDigest"],
        "captureDigest": review["captureDigest"],
        "criticOutputDigest": review["criticOutputDigest"],
        "roundIndex": review["roundIndex"],
        "nextRoundIndex": next_round,
        "before": {
            "candidateId": context["candidate"]["candidateId"],
            "sha256": before_sha,
            "size": context["candidate"]["renderSize"],
            "renderExportSha256": context["candidate"][
                "renderExportSha256"
            ],
        },
        "after": {
            "candidateId": next_candidate_id,
            "sha256": after_sha,
            "size": after_size,
            "renderExportSha256": export_file_sha,
            "renderExportDigest": render_digest,
            "applicationSidecarSha256": _file_sha(copied_app),
            "applicationDigest": app_digest,
            "planDigest": application["planDigest"],
            "timelineDigest": application["outputTimelineDigest"],
            "technicalQaDigest": application["qa"][
                "technicalEvidenceSha256"
            ],
        },
        "applications": applications,
        "replayed": bool(log.get("replayed")),
        "logicalEffects": 0 if log.get("replayed") else 1,
        "providerInvoked": False,
        "liveProviderMutation": False,
        "humanQuality": False,
    }
    durable = {
        k: v for k, v in evidence.items()
        if k not in {"replayed", "logicalEffects"}
    }
    evidence["resultDigest"] = _sha(durable)
    return {
        "evidence": evidence,
        "application": application,
        "renderExport": render_export,
        "finalPath": str(copied_final),
        "applicationPath": str(copied_app),
        "renderExportPath": str(copied_export),
    }


def build_next_context(
    *,
    prior: Mapping[str, Any],
    media_result: Mapping[str, Any],
    candidate_root: Path,
) -> dict[str, Any]:
    prior = validate_candidate_context(prior)
    after = media_result["evidence"]["after"]
    root = Path(candidate_root).resolve()
    final_path = Path(media_result["finalPath"]).resolve()
    app_path = Path(media_result["applicationPath"]).resolve()
    export_path = Path(media_result["renderExportPath"]).resolve()
    source_path = (root / prior["source"]["path"]).resolve()
    for p in (final_path, app_path, export_path, source_path):
        try:
            p.relative_to(root)
        except ValueError as exc:
            raise ReviewLineageError(
                "next candidate evidence escapes candidate root"
            ) from exc
    candidate = {
        "candidateId": after["candidateId"],
        "roundIndex": media_result["evidence"]["nextRoundIndex"],
        "finalPath": final_path.relative_to(root).as_posix(),
        "renderSha256": after["sha256"],
        "renderSize": after["size"],
        "renderExportPath": export_path.relative_to(root).as_posix(),
        "renderExportSha256": after["renderExportSha256"],
        "renderExportDigest": after["renderExportDigest"],
        "renderProducerSha": MEDIA_R20_AUTHORITY["producerSha"],
        "editorialApplication": {
            "path": app_path.relative_to(root).as_posix(),
            "fileSha256": after["applicationSidecarSha256"],
            "digest": after["applicationDigest"],
        },
    }
    return build_candidate_context(
        loop_id=prior["loopId"],
        brief_digest=prior["briefDigest"],
        semantic_analysis_digest=prior["semanticAnalysisDigest"],
        semantic_directives_digest=prior["semanticDirectivesDigest"],
        ledger_digest=prior["ledgerDigest"],
        source=prior["source"],
        candidate=candidate,
        timeline={
            **_clone(prior["timeline"]),
            "r28OutputTimelineDigest": after["timelineDigest"],
        },
        export_spec=prior["exportSpec"],
    )


def _dynamic_descriptor(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    context = validate_candidate_context(context)
    candidate = context["candidate"]
    return {
        "candidateId": candidate["candidateId"],
        "roundNumber": candidate["roundIndex"],
        "source": _clone(context["source"]),
        "render": {
            "path": candidate["finalPath"],
            "sha256": candidate["renderSha256"],
            "size": candidate["renderSize"],
        },
        "renderExport": {
            "path": candidate["renderExportPath"],
            "fileSha256": candidate["renderExportSha256"],
            "digest": candidate["renderExportDigest"],
        },
        "renderProducerSha": candidate["renderProducerSha"],
        "editorialApplication": _clone(
            candidate["editorialApplication"]
        ),
        "reviewDerivative": None,
    }


def build_dynamic_package(
    *,
    media_checkout: Path,
    media_profile: Mapping[str, Any],
    candidate_root: Path,
    before_context: Mapping[str, Any],
    after_context: Mapping[str, Any],
    out_dir: Path,
    bridge_target: Mapping[str, Any],
) -> dict[str, Any]:
    verify_media_checkout(media_checkout, media_profile)
    before = validate_candidate_context(before_context)
    after = validate_candidate_context(after_context)
    if after["candidate"]["roundIndex"] != before["candidate"]["roundIndex"] + 1:
        raise RoundRegression("dynamic package candidate round regression")
    if after["candidate"]["roundIndex"] > MAX_REEDIT_ROUNDS:
        raise RoundRegression("dynamic package exceeds max round")
    if after["candidate"]["editorialApplication"] is None:
        raise MissingMediaApplicationEvidence(
            "next candidate missing Media application evidence"
        )
    request = {
        "contractVersion": media_profile["dynamicRequestContract"],
        "candidates": [
            _dynamic_descriptor(before),
            _dynamic_descriptor(after),
        ],
        "bridgeTarget": _clone(bridge_target),
        "duplicatePolicy": "reject",
    }
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    request_path = out_dir / "media.dynamic_review_request.r20.v1.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    package_dir = out_dir / "package"
    env = dict(os.environ)
    env["GITHUB_SHA"] = media_profile["producerSha"]
    result = subprocess.run(
        [
            "node",
            str(
                Path(media_checkout).resolve()
                / "tools/build-r20-dynamic-review.mjs"
            ),
            "--request",
            str(request_path),
            "--sandbox-root",
            str(Path(candidate_root).resolve()),
            "--output-dir",
            str(package_dir),
        ],
        cwd=Path(media_checkout).resolve(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise MediaR20Error(
            "Media R20 dynamic package failed: " + result.stderr[-5000:]
        )
    lines = [
        line for line in result.stdout.splitlines()
        if line.startswith("R20_DYNAMIC_REVIEW ")
    ]
    if not lines:
        raise MediaR20Error("Media R20 package result line missing")
    log = json.loads(lines[-1].split(" ", 1)[1])
    package_path = package_dir / "media.dynamic_review_package.r20.v1.json"
    evidence_path = (
        package_dir / "media.dynamic_review_package.r20.evidence.json"
    )
    if not package_path.is_file() or not evidence_path.is_file():
        raise MediaR20Error("Media R20 package evidence incomplete")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        package.get("contractVersion") != media_profile["dynamicPackageContract"]
        or package.get("packageProducer") != {
            "repository": media_profile["repository"],
            "sha": media_profile["producerSha"],
        }
        or package.get("humanQuality") is not False
    ):
        raise AuthorityDrift("Media R20 dynamic package authority drift")
    if (
        package.get("modelReview", {}).get("performed") is not False
        or package.get("bridgeHandoff", {}).get("liveExecutionPerformed")
        is not False
    ):
        raise MediaR20Error("Media R20 package cannot claim live review")
    if log.get("packageDigest") != evidence.get("packageDigest"):
        raise PackageDigestDrift("Media R20 package digest/log drift")
    package_file_sha = _file_sha(package_path)
    if evidence.get("packageFileSha256") != package_file_sha:
        raise PackageDigestDrift("Media R20 package file SHA drift")
    if package.get("sealedMapping", {}).get("digest") != log.get(
        "sealedMappingDigest"
    ):
        raise PackageDigestDrift("Media R20 sealed mapping digest drift")
    if package.get("source", {}).get("sha256") != before["source"]["sha256"]:
        raise ReviewLineageError("Media R20 package source drift")
    result_evidence = {
        "contractVersion": PACKAGE_RESULT_VERSION,
        "producerAuthorityDigest": _profile_digest(media_profile),
        "roundIndex": after["candidate"]["roundIndex"],
        "beforeCandidateId": before["candidate"]["candidateId"],
        "afterCandidateId": after["candidate"]["candidateId"],
        "beforeRenderSha256": before["candidate"]["renderSha256"],
        "afterRenderSha256": after["candidate"]["renderSha256"],
        "packageDigest": log["packageDigest"],
        "packageFileSha256": package_file_sha,
        "sealedMappingDigest": log["sealedMappingDigest"],
        "promptDigest": log["promptDigest"],
        "bridgeRequestId": package["bridgeHandoff"]["requestId"],
        "bridgeIdempotencyKey": package["bridgeHandoff"][
            "idempotencyKey"
        ],
        "modelReviewPerformed": False,
        "liveProviderMutation": False,
        "humanQuality": False,
    }
    result_evidence["resultDigest"] = _sha(result_evidence)
    (out_dir / "creator.media_r20_review_package_result.r28.v1.json").write_text(
        json.dumps(result_evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "evidence": result_evidence,
        "package": package,
        "evidenceDocument": evidence,
        "packagePath": str(package_path),
        "packageEvidencePath": str(evidence_path),
    }


def _media_render_from_context(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    context = validate_candidate_context(context)
    candidate = context["candidate"]
    return {
        "contract_version": "creator.media_r20_render.r28.v1",
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
            "renderExportDigest": candidate["renderExportDigest"],
            "editorialApplication": candidate["editorialApplication"],
        },
        "human_ground_truth": False,
    }


def _winner_decision(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = context["candidate"]
    decision = {
        "contractVersion": r22.DECISION_VERSION,
        "roundIndex": candidate["roundIndex"],
        "state": "winner",
        "winnerCandidateId": candidate["candidateId"],
        "reason": "terminal exact-authority external Growth review envelope",
        "evaluations": [
            {
                "candidateId": candidate["candidateId"],
                "renderSha256": candidate["renderSha256"],
                "reviewEnvelopeDigest": envelope["envelope_digest"],
                "criticOutputDigest": envelope["creator_event"][
                    "handoff"
                ]["binding"]["critic_output_digest"],
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
    ledger: Ledger,
    growth_profile: Mapping[str, Any],
    media_profile: Mapping[str, Any],
) -> dict[str, Any]:
    context = validate_candidate_context(context)
    render = _media_render_from_context(context)
    decision = _winner_decision(context=context, envelope=envelope)
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": context["candidate"]["candidateId"],
        "roundIndex": context["candidate"]["roundIndex"],
        "render": render,
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
                "authorityProfileDigest": _profile_digest(growth_profile),
                "producerSha": growth_profile["producerSha"],
                "envelopeDigest": envelope["envelope_digest"],
                "captureDigest": envelope["capture"]["capture_digest"],
            },
            "mediaRenderExport": {
                "authorityProfileDigest": _profile_digest(media_profile),
                "producerSha": context["candidate"]["renderProducerSha"],
                "renderExportDigest": context["candidate"][
                    "renderExportDigest"
                ],
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def _validate_terminal_media(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_source_sha256: str,
    expected_candidate_id: str,
    expected_plan_digest: str,
) -> dict[str, Any]:
    if value.get("contract_version") != "creator.media_r20_render.r28.v1":
        raise r23.EditorPublishHandoffError("R28 Media render contract mismatch")
    if value.get("source_id") != expected_source_id:
        raise r23.EditorPublishHandoffError("R28 Media source ID mismatch")
    if value.get("source_sha256") != expected_source_sha256:
        raise r23.EditorPublishHandoffError("R28 Media source SHA mismatch")
    if value.get("candidate_id") != expected_candidate_id:
        raise r23.EditorPublishHandoffError("R28 Media candidate mismatch")
    if value.get("plan_digest") != expected_plan_digest:
        raise r23.EditorPublishHandoffError("R28 Media plan mismatch")
    if value.get("technical_qa", {}).get("passed") is not True:
        raise r23.EditorOutcomeIneligible("R28 Media QA failed")
    if value.get("human_ground_truth") is not False:
        raise r23.EditorPublishHandoffError(
            "R28 Media cannot claim human ground truth"
        )
    return _clone(value)


def _terminal_growth_validator(
    growth_profile: Mapping[str, Any],
):
    def validate(
        value: Mapping[str, Any],
        *,
        expected_source_id: str,
        expected_render_sha256: str,
    ) -> dict[str, Any]:
        envelope = validate_growth_external_review(
            value,
            growth_profile=growth_profile,
        )
        handoff = envelope["creator_event"]["handoff"]
        if handoff["state"] != "winner":
            raise r23.EditorOutcomeIneligible(
                "only terminal external-review winner may publish"
            )
        binding = handoff["binding"]
        if binding["source_id"] != expected_source_id:
            raise r23.EditorPublishHandoffError(
                "R28 terminal source mismatch"
            )
        if binding["render_sha256"] != expected_render_sha256:
            raise r23.EditorPublishHandoffError(
                "R28 terminal render mismatch"
            )
        return envelope
    return validate


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
    growth_profile: Mapping[str, Any],
) -> dict[str, Any]:
    handoff = envelope["creator_event"]["handoff"]
    if handoff["state"] != "winner":
        raise r23.EditorOutcomeIneligible(
            "nonwinner dynamic review cannot create publish handoff"
        )
    asset = r21.probe_media(final_path)
    return r23.build_editor_publish_handoff(
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
        media_render_validator=_validate_terminal_media,
        growth_critic_validator=_terminal_growth_validator(growth_profile),
    )


def _bridge_target(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "managedChatId",
        "profileId",
        "conversationId",
        "titleHint",
        "expectedAccountMarkerHash",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise R28Error("bridge target fields mismatch")
    for key in ("managedChatId", "profileId", "conversationId", "titleHint"):
        _nonempty(value[key], f"bridgeTarget.{key}")
    _hex(
        value["expectedAccountMarkerHash"],
        64,
        "bridgeTarget.expectedAccountMarkerHash",
    )
    return _clone(value)


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": REPORT_VERSION,
        "creatorBaseSha": CREATOR_R27_BASE_SHA,
        "state": "BLOCKED_WAITING_DYNAMIC_REVIEW_CAPTURE",
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": False,
        "REAL_REEDIT_EXECUTED": False,
        "NEXT_REVIEW_PACKAGE_READY": False,
        "PUBLISH_HANDOFF_READY": False,
        "mediaR20Authority": _clone(MEDIA_R20_AUTHORITY),
        "growthR25Authority": _clone(GROWTH_R25_AUTHORITY),
        "bridgeR29Observed": _clone(BRIDGE_R29_OBSERVED),
        "missingDynamicAuthority": _clone(
            MISSING_DYNAMIC_CAPTURE_AUTHORITY
        ),
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanLevelQualityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    return report


def run_dynamic_review(
    *,
    media_checkout: Path,
    growth_checkout: Path,
    media_authority: Mapping[str, Any],
    growth_authority: Mapping[str, Any],
    candidate_root: Path,
    candidate_context_path: Path,
    review_envelope_path: Path,
    out_dir: Path,
    bridge_target: Mapping[str, Any] | None = None,
    release_authorization_path: Path | None = None,
    publish_target: Mapping[str, str] | None = None,
    inject_lost_ack_after_media: bool = False,
) -> dict[str, Any]:
    media_profile = validate_media_authority(media_authority)
    growth_profile = validate_growth_authority(growth_authority)
    media_pin = verify_media_checkout(media_checkout, media_profile)
    growth_pin = verify_growth_checkout(growth_checkout, growth_profile)
    context = validate_candidate_context(
        json.loads(Path(candidate_context_path).read_text(encoding="utf-8"))
    )
    envelope = validate_growth_external_review(
        json.loads(Path(review_envelope_path).read_text(encoding="utf-8")),
        growth_profile=growth_profile,
    )
    review = normalize_review(envelope)
    validate_review_against_context(
        review,
        context,
        candidate_root=candidate_root,
    )
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out_dir / "dynamic-live-review-ledger.jsonl")
    ledger.append_once(
        "start",
        "r28_started",
        {
            "contextDigest": context["contextDigest"],
            "mediaAuthorityDigest": media_pin["profileDigest"],
            "growthAuthorityDigest": growth_pin["profileDigest"],
        },
    )
    round_index = review["roundIndex"]
    review_key = f"review:{round_index}"
    review_status = ledger.append_once(
        review_key,
        "growth_dynamic_external_review",
        {
            "envelopeDigest": review["envelopeDigest"],
            "captureId": review["captureId"],
            "captureDigest": review["captureDigest"],
            "criticOutputDigest": review["criticOutputDigest"],
            "state": review["state"],
            "roundIndex": round_index,
            "candidateId": review["candidate"]["candidateId"],
            "renderSha256": review["candidate"]["renderSha256"],
        },
    )
    genuine = growth_profile["testFixture"] is False
    state = review["state"]

    if state == "targeted_reedit":
        if round_index >= MAX_REEDIT_ROUNDS:
            raise RoundRegression("targeted re-edit would exceed two rounds")
        media_key = "media:" + review["envelopeDigest"]
        media_prior = ledger.by_key.get(media_key)
        result = execute_media_reedit(
            media_checkout=media_checkout,
            media_profile=media_profile,
            candidate_root=candidate_root,
            context=context,
            review=review,
            out_dir=Path(candidate_root).resolve(),
        )
        if (
            inject_lost_ack_after_media
            and media_prior is None
            and result["evidence"]["logicalEffects"] == 1
        ):
            raise InjectedLostAck(
                "injected lost ACK after exact Media R19/R20 effect"
            )
        ledger.append_once(
            media_key,
            "media_r20_reedit",
            {
                "reviewEnvelopeDigest": review["envelopeDigest"],
                "resultDigest": result["evidence"]["resultDigest"],
                "beforeSha256": result["evidence"]["before"]["sha256"],
                "afterSha256": result["evidence"]["after"]["sha256"],
                "afterSize": result["evidence"]["after"]["size"],
                "applicationSidecarSha256": result["evidence"]["after"][
                    "applicationSidecarSha256"
                ],
                "renderExportSha256": result["evidence"]["after"][
                    "renderExportSha256"
                ],
            },
        )
        next_context = build_next_context(
            prior=context,
            media_result=result,
            candidate_root=candidate_root,
        )
        next_context_path = out_dir / "next-candidate-context.json"
        next_context_path.write_text(
            json.dumps(next_context, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        package_ready = False
        package_result = None
        if bridge_target is not None:
            package_work = (
                Path(candidate_root).resolve()
                / ".creator-r28-packages"
                / review["envelopeDigest"][:24]
            )
            package_result = build_dynamic_package(
                media_checkout=media_checkout,
                media_profile=media_profile,
                candidate_root=candidate_root,
                before_context=context,
                after_context=next_context,
                out_dir=package_work,
                bridge_target=_bridge_target(bridge_target),
            )
            (out_dir / "next-review-package-result.json").write_text(
                json.dumps(
                    package_result["evidence"],
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            package_key = (
                "package:" + str(next_context["candidate"]["roundIndex"])
            )
            ledger.append_once(
                package_key,
                "media_r20_dynamic_review_package",
                {
                    "resultDigest": package_result["evidence"][
                        "resultDigest"
                    ],
                    "packageDigest": package_result["evidence"][
                        "packageDigest"
                    ],
                    "packageFileSha256": package_result["evidence"][
                        "packageFileSha256"
                    ],
                    "sealedMappingDigest": package_result["evidence"][
                        "sealedMappingDigest"
                    ],
                    "beforeRenderSha256": package_result["evidence"][
                        "beforeRenderSha256"
                    ],
                    "afterRenderSha256": package_result["evidence"][
                        "afterRenderSha256"
                    ],
                },
            )
            package_ready = True

        report = {
            "contractVersion": REPORT_VERSION,
            "state": "BLOCKED_WAITING_DYNAMIC_REVIEW_CAPTURE",
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": genuine,
            "REAL_REEDIT_EXECUTED": genuine,
            "NEXT_REVIEW_PACKAGE_READY": package_ready,
            "PUBLISH_HANDOFF_READY": False,
            "reviewReplay": review_status == "duplicate",
            "mediaReplay": result["evidence"]["replayed"],
            "reviewEnvelopeDigest": review["envelopeDigest"],
            "beforeRenderSha256": result["evidence"]["before"]["sha256"],
            "afterRenderSha256": result["evidence"]["after"]["sha256"],
            "afterRenderSize": result["evidence"]["after"]["size"],
            "mediaResultDigest": result["evidence"]["resultDigest"],
            "nextContextDigest": next_context["contextDigest"],
            "nextPackageDigest": (
                None
                if package_result is None
                else package_result["evidence"]["packageDigest"]
            ),
            "nextPackageResultDigest": (
                None
                if package_result is None
                else package_result["evidence"]["resultDigest"]
            ),
            "nextPackagePath": (
                None
                if package_result is None
                else package_result["packagePath"]
            ),
            "roundIndex": round_index,
            "nextRoundIndex": next_context["candidate"]["roundIndex"],
            "maxReeditRounds": MAX_REEDIT_ROUNDS,
            "mediaAuthorityDigest": media_pin["profileDigest"],
            "growthAuthorityDigest": growth_pin["profileDigest"],
            "missingDynamicAuthority": _clone(
                MISSING_DYNAMIC_CAPTURE_AUTHORITY
            ),
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanLevelQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
        report["reportDigest"] = _sha(report)
        (out_dir / "dynamic_live_review_loop.r28.json").write_text(
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
                "envelopeDigest": review["envelopeDigest"],
                "renderSha256": context["candidate"]["renderSha256"],
            },
        )
        report = {
            "contractVersion": REPORT_VERSION,
            "state": terminal_state,
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": genuine,
            "REAL_REEDIT_EXECUTED": False,
            "NEXT_REVIEW_PACKAGE_READY": False,
            "PUBLISH_HANDOFF_READY": False,
            "roundIndex": round_index,
            "maxReeditRounds": MAX_REEDIT_ROUNDS,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanLevelQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
        report["reportDigest"] = _sha(report)
        (out_dir / "dynamic_live_review_loop.r28.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    root = Path(candidate_root).resolve()
    candidate_path = (root / context["candidate"]["finalPath"]).resolve()
    final_path = out_dir / "final.mp4"
    shutil.copyfile(candidate_path, final_path)
    final_asset = r21.probe_media(final_path)
    if (
        final_asset.sha256 != context["candidate"]["renderSha256"]
        or final_asset.size_bytes != context["candidate"]["renderSize"]
    ):
        raise ReviewLineageError("winner final.mp4 byte lineage mismatch")
    bundle = build_final_bundle(
        context=context,
        envelope=envelope,
        ledger=ledger,
        growth_profile=growth_profile,
        media_profile=media_profile,
    )
    (out_dir / "editor-final-bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    publish_handoff = None
    if release_authorization_path is not None:
        if publish_target is None:
            raise R28Error(
                "publish target required with release authorization"
            )
        release_auth = json.loads(
            Path(release_authorization_path).read_text(encoding="utf-8")
        )
        required_target = {
            "platform",
            "accountId",
            "destination",
            "credentialRef",
            "authorizationRef",
            "caption",
            "cta",
        }
        if set(publish_target) != required_target:
            raise R28Error("publish target fields mismatch")
        publish_handoff = materialize_publish_handoff(
            context=context,
            envelope=envelope,
            bundle=bundle,
            final_path=final_path,
            release_authorization=release_auth,
            platform=publish_target["platform"],
            account_id=publish_target["accountId"],
            destination=publish_target["destination"],
            credential_ref=publish_target["credentialRef"],
            authorization_ref=publish_target["authorizationRef"],
            caption=publish_target["caption"],
            cta=publish_target["cta"],
            growth_profile=growth_profile,
        )
        (out_dir / "editor-publish-handoff.json").write_text(
            json.dumps(publish_handoff, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ledger.append_once(
            "publish-handoff",
            "publish_handoff_materialized",
            {
                "handoffDigest": publish_handoff["handoffDigest"],
                "publishRequestDigest": _sha(
                    publish_handoff["publishRequest"]
                ),
                "providerInvoked": False,
            },
        )
    ledger.append_once(
        "terminal",
        "winner_terminal",
        {
            "envelopeDigest": review["envelopeDigest"],
            "winnerCandidateId": context["candidate"]["candidateId"],
            "finalRenderSha256": final_asset.sha256,
            "bundleDigest": bundle["bundleDigest"],
            "publishHandoffDigest": (
                None
                if publish_handoff is None
                else publish_handoff["handoffDigest"]
            ),
        },
    )
    report = {
        "contractVersion": REPORT_VERSION,
        "state": (
            "PUBLISH_HANDOFF_READY"
            if publish_handoff is not None
            else "WINNER_AWAITING_RELEASE_AUTHORIZATION"
        ),
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": genuine,
        "REAL_REEDIT_EXECUTED": (
            genuine and context["candidate"]["roundIndex"] > 0
        ),
        "NEXT_REVIEW_PACKAGE_READY": False,
        "PUBLISH_HANDOFF_READY": publish_handoff is not None,
        "winnerCandidateId": context["candidate"]["candidateId"],
        "finalRenderSha256": final_asset.sha256,
        "finalRenderSize": final_asset.size_bytes,
        "bundleDigest": bundle["bundleDigest"],
        "publishHandoffDigest": (
            None
            if publish_handoff is None
            else publish_handoff["handoffDigest"]
        ),
        "roundIndex": round_index,
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    report["reportDigest"] = _sha(report)
    (out_dir / "dynamic_live_review_loop.r28.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def build_test_growth_envelope(
    *,
    context: Mapping[str, Any],
    state: str = "targeted_reedit",
    growth_profile: Mapping[str, Any] | None = None,
    bridge_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = validate_growth_authority(
        growth_profile or {**GROWTH_R25_AUTHORITY, "testFixture": True}
    )
    context = validate_candidate_context(context)
    candidate = context["candidate"]
    binding = {
        "source_id": context["source"]["sourceId"],
        "source_sha256": context["source"]["sha256"],
        "source_size": context["source"]["size"],
        "media_repository": "foto6/video2",
        "media_producer_sha": candidate["renderProducerSha"],
        "candidate_id": candidate["candidateId"],
        "render_sha256": candidate["renderSha256"],
        "render_size": candidate["renderSize"],
        "render_export_sha256": candidate["renderExportSha256"],
        "attachment_sha256": candidate["renderSha256"],
        "attachment_size": candidate["renderSize"],
        "attachment_identity": (
            "r28-test-attachment:" + candidate["renderSha256"][:16]
        ),
        "review_bundle_digest": "4" * 64,
        "critic_input_digest": "5" * 64,
        "critic_output_digest": "6" * 64,
    }
    directives = []
    if state == "targeted_reedit":
        body = {
            "operation": "trim",
            "start_ms": 100,
            "end_ms": 300,
            "defect_category": "awkward_dead_moment",
            "severity": "major",
            "source_observation_id": "r28-test-observation",
            "evidence": "synthetic conformance evidence only",
            "confidence": 0.9,
            "uncertainty": "synthetic fixture uncertainty",
            "upstream_proposed_edit": "remove bounded pause",
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(binding),
        }
        body["directive_id"] = "gcrd1:" + _sha(body)
        directives = [body]
    handoff = {
        "contract_version": "growth.creator_reedit_handoff.v1",
        "adapter_version": "growth.web_video_critic_reedit_adapter.v1",
        "handoff_id": "",
        "handoff_digest": "",
        "state": state,
        "reedit_round": candidate["roundIndex"],
        "max_reedit_rounds": 2,
        "binding": binding,
        "pairwise": {
            "selection": None,
            "mapped_candidate_id": (
                candidate["candidateId"] if state == "winner" else None
            ),
            "output_digest": None,
        },
        "coverage": {
            "method": "r28_test_fixture",
            "inspected_ranges": [{"start_ms": 0, "end_ms": 5000}],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": "synthetic fixture only",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": "synthetic fixture only",
        "directives": directives,
        "bridge_r26_authority": copy.deepcopy(r26.BRIDGE_R26_AUTHORITY),
        "media_r18_authority": copy.deepcopy(r26.MEDIA_R18_AUTHORITY),
        "evidence_boundary": {
            "model_review_only": True,
            "human_ground_truth": False,
            "human_label": False,
            "live_platform_evidence": False,
            "live_video_review_fabricated": False,
        },
        "authority": {
            "advisory_only": True,
            "creator_mutation": False,
            "media_mutation": False,
            "provider_mutation": False,
            "upload_performed": False,
            "publish_authorized": False,
            "release_authorized": False,
        },
    }
    handoff["handoff_id"] = "gcrh1:" + _sha(
        {
            "critic_output_digest": binding["critic_output_digest"],
            "pairwise_output_digest": None,
            "reedit_round": candidate["roundIndex"],
        }
    )
    material = copy.deepcopy(handoff)
    material["handoff_digest"] = ""
    handoff["handoff_digest"] = _sha(material)
    bridge = bridge_authority or {
        "contract_version": "growth.bridge_r29_capture_authority.v1",
        "repository": "foto6/WebAIBridge",
        "producer_sha": BRIDGE_R29_OBSERVED["producerSha"],
        "capture_contract": BRIDGE_R29_OBSERVED["captureContract"],
        "contract_blob_sha1": BRIDGE_R29_OBSERVED["contractTestBlobSha1"],
        "implementation_blob_sha1": BRIDGE_R29_OBSERVED[
            "implementationBlobSha1"
        ],
    }
    capture_digest = _sha(
        {
            "candidate": candidate["candidateId"],
            "round": candidate["roundIndex"],
            "state": state,
        }
    )
    capture = {
        "capture_id": "r28-test-capture",
        "capture_digest": capture_digest,
        "assistant_response_digest": "7" * 64,
        "conversation_id": "r28-test-conversation",
        "request_id": "r28-test-request",
    }
    event = {
        "contractVersion": "creator.external_real_review_event.r26.v1",
        "producer": _growth_event_producer(profile),
        "captureMode": "external_live_review",
        "reviewIdentity": handoff["handoff_id"],
        "handoff": handoff,
    }
    summary = {
        "candidate_label": "A",
        "handoff_id": handoff["handoff_id"],
        "handoff_digest": handoff["handoff_digest"],
        "state": state,
        "reedit_round": candidate["roundIndex"],
        "source_id": binding["source_id"],
        "source_sha256": binding["source_sha256"],
        "render_sha256": binding["render_sha256"],
        "attachment_sha256": binding["attachment_sha256"],
        "attachment_size": binding["attachment_size"],
    }
    value = {
        "contract_version": profile["envelopeContract"],
        "envelope_id": "",
        "envelope_digest": "",
        "creator_event": event,
        "growth_r25": {
            "repository": profile["repository"],
            "producer_sha": profile["producerSha"],
            "ci_run_id": profile["ciRunId"],
            "starting_r24_sha": "dc0741d5b11c1f7464ac9a6c5db80c0a4535df08",
            "ingest_contract": profile["ingestContract"],
        },
        "bridge_r29": _clone(bridge),
        "capture": capture,
        "handoff": summary,
        "evidence_boundary": {
            "model_evidence": True,
            "human_ground_truth": False,
            "human_parity_inferred": False,
            "provider_mutation": False,
        },
    }
    value["envelope_id"] = "gr25ce1:" + _sha(
        {
            "growth_producer_sha": profile["producerSha"],
            "capture_digest": capture_digest,
            "handoff_digest": handoff["handoff_digest"],
            "reedit_round": candidate["roundIndex"],
        }
    )
    material = copy.deepcopy(value)
    material["envelope_digest"] = ""
    value["envelope_digest"] = _sha(material)
    return validate_growth_external_review(
        value,
        growth_profile=profile,
        expected_bridge_authority=bridge,
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R28Error(f"{path} must contain a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-dynamic-live-review-r28")
    sub = parser.add_subparsers(dest="command", required=True)

    ready = sub.add_parser("readiness")
    ready.add_argument("--out")

    run = sub.add_parser("run")
    run.add_argument("--media-checkout", required=True)
    run.add_argument("--growth-checkout", required=True)
    run.add_argument("--media-authority", required=True)
    run.add_argument("--growth-authority", required=True)
    run.add_argument("--candidate-root", required=True)
    run.add_argument("--candidate-context", required=True)
    run.add_argument("--review-envelope", required=True)
    run.add_argument("--bridge-target")
    run.add_argument("--release-authorization")
    run.add_argument("--publish-target")
    run.add_argument("--out", required=True)
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
        report = run_dynamic_review(
            media_checkout=Path(args.media_checkout),
            growth_checkout=Path(args.growth_checkout),
            media_authority=_load_json(Path(args.media_authority)),
            growth_authority=_load_json(Path(args.growth_authority)),
            candidate_root=Path(args.candidate_root),
            candidate_context_path=Path(args.candidate_context),
            review_envelope_path=Path(args.review_envelope),
            out_dir=Path(args.out),
            bridge_target=(
                None
                if not args.bridge_target
                else _load_json(Path(args.bridge_target))
            ),
            release_authorization_path=(
                None
                if not args.release_authorization
                else Path(args.release_authorization)
            ),
            publish_target=(
                None
                if not args.publish_target
                else _load_json(Path(args.publish_target))
            ),
        )
    except Exception as exc:
        blocked = {
            "contractVersion": REPORT_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": False,
            "REAL_REEDIT_EXECUTED": False,
            "NEXT_REVIEW_PACKAGE_READY": False,
            "PUBLISH_HANDOFF_READY": False,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanLevelQualityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
