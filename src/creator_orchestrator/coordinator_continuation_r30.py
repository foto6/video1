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

from . import autonomous_reels as reels
from . import dynamic_live_review_loop as r28
from . import editor_publish_handoff as r23
from . import exact_dynamic_e2e_r29 as r29
from . import publish_execution as r21

CONTRACT_VERSION = "creator.coordinator_continuation.r30.v1"
JOURNAL_VERSION = "creator.coordinator_continuation_journal.r30.v1"
RESULT_VERSION = "creator.coordinator_continuation_result.r30.v1"
READINESS_VERSION = "creator.coordinator_continuation.r30.readiness.v1"
CREATOR_BASE_SHA = "4a58561b07d615c141fa609d212070c894bfd0cb"
MAX_REEDIT_ROUNDS = 2
MAX_REVIEW_ROUNDS = 3

MEDIA_R22_AUTHORITY = {
    "repository": "foto6/video2",
    "producerSha": "e82a7ac04f3758d0e3e21ea3d05265dbc2822132",
    "ciRunId": 37001071721,
    "liveReviewContract": "media.live_review_artifact.r22.v1",
    "actionsArtifactId": 11224061610,
    "actionsArtifactName": "media-r22-live-review-operator-bundle",
    "actionsArtifactDigest": "sha256:d534f1656e22b72cf42531c827e66516965b4167549906521dee04edafd01734",
    "blobs": {
        "liveReviewContract": "d6e494950b5ab54383733db69912c2384cce188f",
        "liveReviewManifest": "be117e83a44720e8e12284991b755c69c8ea0cde",
        "operatorManifestSchema": "7e78d7be9fffbbda6ee86cf39c4db8e59a635a3d",
        "liveReviewImplementation": "31845333a6919364d81a7c2bc52aad1cb3ae82ed",
        "materializer": "ade9e7181ecccf8e78e7dd966240618c872c9b26",
        "verifier": "86b0a53eed6959af805fd0c492620eb037071e25",
        "r21Contract": "65358261775f0fcd2ab9e21f3f621aee977f29da",
        "r21Schema": "f04925e317d849434852e6b706533f909da47b22",
        "r21Implementation": "c6f556b8a177b6182d787356625094cdcad5a58e",
        "r21Runner": "c93e9a69de31b66189031932ccfa7f2c83cf043c",
        "r19Implementation": "8110a086b5b319bd2601860845c6afbf97681921",
        "r19Runner": "7dbec612621aa42baaf2946cdac61d070e3ff41f",
    },
    "sourceR21": {
        "producerSha": r29.MEDIA_R21_AUTHORITY["producerSha"],
        "ciRunId": r29.MEDIA_R21_AUTHORITY["ciRunId"],
        "contract": r29.MEDIA_R21_AUTHORITY["reviewBundleContract"],
    },
}

GROWTH_R27_AUTHORITY = {
    "repository": "foto6/video3",
    "producerSha": "d80592ad660b7b73ad13298880918a5944411c38",
    "ciRunId": 37002456031,
    "operatorContract": "growth.live_ingest_operator.r27.v1",
    "indexContract": "growth.dynamic_live_review_ingest_index.r27.v1",
    "authorityContract": "growth.exact_dynamic_authorities.r27.v1",
    "authorityProfileDigest": "57ab464f85ba95f1ca4dfefeaeb0a19371ce7d666ca8142daeb86e3162d2c634",
    "actionsArtifactId": 11224342240,
    "actionsArtifactName": "growth-r27-live-ingest-operator",
    "actionsArtifactDigest": "sha256:2d832e4d9d136b0bd3dbe0efe67a95f6e3d4d5847e3c11411352454b94d17f71",
    "blobs": {
        "contract": "040097c5aae0b288de39e35f76eb1816e246568c",
        "indexSchema": "23e7f90b4704fe173bd8842c04f00b1eeb15e5d6",
        "authorityProfiles": "256e8fcf228025a2cc09a3173dd82998fd1658d9",
        "implementation": "125dba66b592ca12934c045c78539cf082a1de07",
    },
    "canonicalGrowthR26": {
        "producerSha": r29.GROWTH_R26_AUTHORITY["producerSha"],
        "ciRunId": r29.GROWTH_R26_AUTHORITY["ciRunId"],
        "contract": r29.GROWTH_R26_AUTHORITY["creatorEnvelopeContract"],
    },
}

BRIDGE_R31_AUTHORITY = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "104281e49122233f251c692abba726ae31cee0d5",
    "ciRunId": 36999908386,
    "resultContract": "bridge.r31_live_dynamic_operator_result.v1",
    "captureContract": "bridge.dynamic_existing_chat_video_review_capture.v1",
    "blobs": {
        "resultSchema": "55f403a2c0dca4a05a5002e104cfc29d20b536b5",
        "manifestSchema": "f90cd2aa4bdc868af845bfba58c612ebef3f32ad",
        "authorityProfileSchema": "25e2cbfe487ba88f70d233774e585691ad4f70c6",
        "preflightSchema": "74b4579b4d9d3d08da04b1181863905f024f367a",
        "preflightImplementation": "c975d934d080deffdcf2a9ac4cf82ca142ba93d3",
        "mediaOperator": "38509af174fc25aa4229c084fc3cd9b2e35b539e",
        "finalizer": "a18a10e681efb249275816ab43ceb55e4acc6643",
        "powershellOperator": "1fd850863fb1e1c31894ccc54f5fcbc296122419",
        "readiness": "f248f94843c5d94737947929aaece33129e1b98a",
    },
    "actionsArtifacts": [
        {
            "platform": "ubuntu-latest",
            "id": 11222903971,
            "digest": "sha256:4929ff7f5b27b2aaaad3501221a9b8955f96a0645356c2b91bed5b0c9746c866",
        },
        {
            "platform": "windows-latest",
            "id": 11222794745,
            "digest": "sha256:eb6e792ff7561f475919f408c585b6f253a830741fc1c7865df4b7f7c9cca3ee",
        },
    ],
}

MEDIA_R22_RUNTIME_PROFILE = {
    "authorityVersion": r28.AUTHORITY_VERSION,
    "family": "media_r19_r20_editorial_dynamic_review",
    "repository": "foto6/video2",
    "producerSha": MEDIA_R22_AUTHORITY["producerSha"],
    "ciRunId": MEDIA_R22_AUTHORITY["ciRunId"],
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


class R30Error(ValueError):
    pass


class AuthorityDrift(R30Error):
    pass


class IndexDrift(R30Error):
    pass


class LineageDrift(R30Error):
    pass


class ReplayConflict(R30Error):
    pass


class RoundOverflow(R30Error):
    pass


class MaterializationDrift(R30Error):
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
        raise R30Error(f"{field} must be lowercase {size}-hex")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R30Error(f"{field} must be non-empty")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R30Error(f"{field} must be positive integer")
    return value


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _profile_digest(value: Mapping[str, Any]) -> str:
    return _sha(value)


def _verify_checkout(
    root: Path,
    *,
    sha: str,
    checks: Mapping[str, tuple[str, str]],
    label: str,
) -> dict[str, Any]:
    root = Path(root).resolve()
    if r28._git_head(root) != sha:
        raise AuthorityDrift(f"{label} checkout SHA drift")
    observed: dict[str, str] = {}
    for name, (rel, expected) in checks.items():
        path = root / rel
        if not path.is_file():
            raise AuthorityDrift(f"{label} missing authority file: {rel}")
        actual = r28._git_blob_sha(path)
        observed[name] = actual
        if actual != expected:
            raise AuthorityDrift(f"{label} blob drift: {name}")
    return {"checkoutSha": sha, "observedBlobs": observed}


def verify_media_r22_checkout(root: Path) -> dict[str, Any]:
    blobs = MEDIA_R22_AUTHORITY["blobs"]
    result = _verify_checkout(
        root,
        sha=MEDIA_R22_AUTHORITY["producerSha"],
        label="Media R22",
        checks={
            "liveReviewContract": (
                "conformance/media.live_review_artifact.r22.v1/contract.json",
                blobs["liveReviewContract"],
            ),
            "liveReviewManifest": (
                "conformance/media.live_review_artifact.r22.v1/manifest.json",
                blobs["liveReviewManifest"],
            ),
            "operatorManifestSchema": (
                "conformance/media.live_review_artifact.r22.v1/operator-manifest.schema.json",
                blobs["operatorManifestSchema"],
            ),
            "liveReviewImplementation": (
                "src/live-review-artifact-r22.js",
                blobs["liveReviewImplementation"],
            ),
            "materializer": (
                "tools/materialize-r22-live-review.mjs",
                blobs["materializer"],
            ),
            "verifier": (
                "tools/verify-r22-live-review.mjs",
                blobs["verifier"],
            ),
            "r21Contract": (
                "conformance/media.review_round_bundle.r21.v1/contract.json",
                blobs["r21Contract"],
            ),
            "r21Schema": (
                "conformance/media.review_round_bundle.r21.v1/schema.json",
                blobs["r21Schema"],
            ),
            "r21Implementation": ("src/review-round-r21.js", blobs["r21Implementation"]),
            "r21Runner": ("tools/build-r21-review-round.mjs", blobs["r21Runner"]),
            "r19Implementation": ("src/editorial-reedit-r19.js", blobs["r19Implementation"]),
            "r19Runner": ("tools/run-r19-editorial-reedit.mjs", blobs["r19Runner"]),
        },
    )
    r28.verify_media_checkout(Path(root), MEDIA_R22_RUNTIME_PROFILE)
    result["profileDigest"] = _profile_digest(MEDIA_R22_AUTHORITY)
    return result


def verify_growth_r27_checkout(root: Path) -> dict[str, Any]:
    blobs = GROWTH_R27_AUTHORITY["blobs"]
    result = _verify_checkout(
        root,
        sha=GROWTH_R27_AUTHORITY["producerSha"],
        label="Growth R27",
        checks={
            "contract": (
                "conformance/growth.live_ingest_operator.r27.v1/contract.json",
                blobs["contract"],
            ),
            "indexSchema": (
                "conformance/growth.live_ingest_operator.r27.v1/index.schema.json",
                blobs["indexSchema"],
            ),
            "authorityProfiles": (
                "conformance/growth.live_ingest_operator.r27.v1/authority-profiles.json",
                blobs["authorityProfiles"],
            ),
            "implementation": (
                "growth_analytics/live_ingest_operator_r27.py",
                blobs["implementation"],
            ),
        },
    )
    result["profileDigest"] = _profile_digest(GROWTH_R27_AUTHORITY)
    return result


def verify_bridge_r31_checkout(root: Path) -> dict[str, Any]:
    blobs = BRIDGE_R31_AUTHORITY["blobs"]
    result = _verify_checkout(
        root,
        sha=BRIDGE_R31_AUTHORITY["producerSha"],
        label="Bridge R31",
        checks={
            "resultSchema": (
                "app/contracts/r31/bridge.r31_live_dynamic_operator_result.v1.schema.json",
                blobs["resultSchema"],
            ),
            "manifestSchema": (
                "app/contracts/r31/bridge.r31_live_dynamic_operator_manifest.v1.schema.json",
                blobs["manifestSchema"],
            ),
            "authorityProfileSchema": (
                "app/contracts/r31/bridge.r31_media_r21_authority_profile.v1.schema.json",
                blobs["authorityProfileSchema"],
            ),
            "preflightSchema": (
                "app/contracts/r31/bridge.r31_live_dynamic_operator_preflight.v1.schema.json",
                blobs["preflightSchema"],
            ),
            "preflightImplementation": (
                "app/r31-live-preflight.js",
                blobs["preflightImplementation"],
            ),
            "mediaOperator": ("app/r31-media-r21-operator.js", blobs["mediaOperator"]),
            "finalizer": ("app/r31-finalize-live-evidence.js", blobs["finalizer"]),
            "powershellOperator": ("app/RUN_R31_DYNAMIC_REVIEW.ps1", blobs["powershellOperator"]),
            "readiness": ("app/r31-readiness-report.js", blobs["readiness"]),
        },
    )
    result["profileDigest"] = _profile_digest(BRIDGE_R31_AUTHORITY)
    return result


def _validate_bridge_wrapper(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract",
        "producer_sha",
        "ci_run_id",
        "result_file_sha256",
        "state",
        "capture_digest",
        "response_digest",
        "operator_manifest_digest",
        "preflight_digest",
        "request_id",
        "operation_id",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise IndexDrift("Bridge R31 wrapper fields mismatch")
    if (
        value["contract"] != BRIDGE_R31_AUTHORITY["resultContract"]
        or value["producer_sha"] != BRIDGE_R31_AUTHORITY["producerSha"]
        or value["ci_run_id"] != BRIDGE_R31_AUTHORITY["ciRunId"]
        or value["state"] != "LIVE_REVIEW_PASS"
    ):
        raise AuthorityDrift("Bridge R31 wrapper authority/state drift")
    for key in (
        "result_file_sha256",
        "capture_digest",
        "response_digest",
        "operator_manifest_digest",
        "preflight_digest",
    ):
        _hex(value[key], 64, f"bridge_r31.{key}")
    _nonempty(value["request_id"], "bridge_r31.request_id")
    _nonempty(value["operation_id"], "bridge_r31.operation_id")
    return _clone(value)


def validate_growth_r27_index(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version",
        "index_id",
        "index_digest",
        "state",
        "live_capture_gate",
        "new_ingest_effect",
        "growth_r27",
        "media_r21",
        "bridge_r30",
        "capture",
        "pairwise",
        "selected_result",
        "candidates",
        "rejection_reason",
        "evidence_boundary",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise IndexDrift("Growth R27 index fields mismatch")
    if value["contract_version"] != GROWTH_R27_AUTHORITY["indexContract"]:
        raise AuthorityDrift("Growth R27 index contract drift")
    material = copy.deepcopy(value)
    digest = material["index_digest"]
    material["index_digest"] = ""
    _hex(digest, 64, "index.index_digest")
    if _sha(material) != digest:
        raise IndexDrift("Growth R27 index digest mismatch")
    if value["index_id"] != "gr27idx1:" + _sha({
        "growth_sha": value["growth_r27"]["producer_sha"],
        "authority_digest": value["growth_r27"]["authority_profile_digest"],
        "media_package_digest": value["media_r21"]["package_digest"],
        "capture_digest": (
            None if value["capture"] is None else value["capture"]["capture_digest"]
        ),
        "state": value["state"],
    }):
        raise IndexDrift("Growth R27 index identity mismatch")

    growth = value["growth_r27"]
    expected_growth = {
        "repository": GROWTH_R27_AUTHORITY["repository"],
        "producer_sha": GROWTH_R27_AUTHORITY["producerSha"],
        "ci_run_id": GROWTH_R27_AUTHORITY["ciRunId"],
        "starting_r26_sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
        "operator_contract": GROWTH_R27_AUTHORITY["operatorContract"],
        "authority_profile_digest": GROWTH_R27_AUTHORITY["authorityProfileDigest"],
        "canonical_creator_envelope_authority": {
            "producer_sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
            "ci_run_id": r29.GROWTH_R26_AUTHORITY["ciRunId"],
            "contract": r29.GROWTH_R26_AUTHORITY["creatorEnvelopeContract"],
        },
    }
    if growth != expected_growth:
        raise AuthorityDrift("Growth R27 runtime/authority digest drift")

    media = value["media_r21"]
    if not isinstance(media, Mapping):
        raise IndexDrift("Growth R27 Media R21 index binding missing")
    if (
        media.get("producer_sha") != r29.MEDIA_R21_AUTHORITY["producerSha"]
        or media.get("ci_run_id") != r29.MEDIA_R21_AUTHORITY["ciRunId"]
    ):
        raise AuthorityDrift("Growth R27 Media R21 authority drift")
    for key in (
        "package_digest",
        "bundle_file_sha256",
        "sealed_mapping_digest",
        "prompt_digest",
        "round_lineage_digest",
    ):
        _hex(media.get(key), 64, f"index.media_r21.{key}")
    round_index = media.get("review_round")
    if isinstance(round_index, bool) or not isinstance(round_index, int) or not 0 <= round_index < MAX_REVIEW_ROUNDS:
        raise RoundOverflow("Growth R27 review round must be 0..2")

    boundary = value["evidence_boundary"]
    if not isinstance(boundary, Mapping):
        raise IndexDrift("Growth R27 evidence boundary missing")
    for key in (
        "human_ground_truth",
        "human_rating_evidence",
        "human_parity_inferred",
        "fixture_promoted",
        "provider_mutation",
        "browser_mutation",
        "creator_mutation",
        "media_mutation",
    ):
        if boundary.get(key) is not False:
            raise IndexDrift(f"Growth R27 forbidden evidence boundary: {key}")

    state = value["state"]
    if state == "BLOCKED_WAITING_GENUINE_CAPTURE":
        if value["capture"] is not None:
            raise IndexDrift("waiting index cannot carry capture")
        return _clone(value)
    if state != "LIVE_REVIEW_INGESTED":
        raise IndexDrift(f"Growth R27 index not continuation-ready: {state}")
    if boundary.get("model_evidence") is not True:
        raise IndexDrift("live-ingested index requires model evidence")

    bridge = value["bridge_r30"]
    wrapper_summary = bridge.get("bridge_r31_wrapper") if isinstance(bridge, Mapping) else None
    if (
        not isinstance(bridge, Mapping)
        or bridge.get("producer_sha") != r29.BRIDGE_R30_AUTHORITY["producerSha"]
        or bridge.get("ci_run_id") != r29.BRIDGE_R30_AUTHORITY["ciRunId"]
        or bridge.get("capture_contract") != r29.BRIDGE_R30_AUTHORITY["captureContract"]
        or not isinstance(wrapper_summary, Mapping)
        or wrapper_summary.get("producer_sha") != BRIDGE_R31_AUTHORITY["producerSha"]
        or wrapper_summary.get("ci_run_id") != BRIDGE_R31_AUTHORITY["ciRunId"]
        or wrapper_summary.get("result_contract") != BRIDGE_R31_AUTHORITY["resultContract"]
    ):
        raise AuthorityDrift("Growth R27 Bridge R30/R31 authority drift")
    _hex(wrapper_summary.get("result_file_sha256"), 64, "bridge_r31_wrapper.result_file_sha256")

    capture = value["capture"]
    if not isinstance(capture, Mapping):
        raise IndexDrift("live-ingested index missing capture")
    wrapper = _validate_bridge_wrapper(capture.get("bridge_r31_result"))
    if (
        wrapper["result_file_sha256"] != wrapper_summary["result_file_sha256"]
        or wrapper["capture_digest"] != capture.get("capture_digest")
        or wrapper["response_digest"] != capture.get("assistant_response_digest")
    ):
        raise IndexDrift("Bridge R31 capture/result identity drift")
    _hex(capture.get("capture_digest"), 64, "index.capture.capture_digest")
    _hex(capture.get("assistant_response_digest"), 64, "index.capture.assistant_response_digest")
    return _clone(value)


def validate_selected_envelope(
    *,
    index: Mapping[str, Any],
    envelope: Mapping[str, Any],
    envelope_path: Path | None = None,
) -> dict[str, Any]:
    index = validate_growth_r27_index(index)
    if index["state"] != "LIVE_REVIEW_INGESTED":
        raise IndexDrift("selected envelope requires LIVE_REVIEW_INGESTED index")
    envelope = r29.validate_growth_r26_envelope(envelope)
    candidate = envelope["candidate"]
    candidate_id = candidate["candidate_id"]
    row = index["candidates"].get(candidate_id)
    if not isinstance(row, Mapping):
        raise LineageDrift("selected Creator envelope candidate absent from R27 index")
    expected = {
        "envelope_digest": envelope["envelope_digest"],
        "handoff_digest": candidate["handoff_digest"],
        "state": candidate["state"],
        "candidate_round": candidate["candidate_round"],
        "source_id": candidate["source_id"],
        "source_sha256": candidate["source_sha256"],
        "render_sha256": candidate["render_sha256"],
        "render_size": candidate["render_size"],
        "attachment_sha256": candidate["attachment_sha256"],
        "attachment_size": candidate["attachment_size"],
        "attachment_mime_type": candidate["attachment_mime_type"],
    }
    for key, expected_value in expected.items():
        if row.get(key) != expected_value:
            raise LineageDrift(f"Growth R27 candidate/envelope drift: {key}")
    if row.get("creator_r29_ready") is not True:
        raise LineageDrift("Growth R27 candidate is not Creator-ready")
    if envelope_path is not None and row.get("envelope_file") != Path(envelope_path).name:
        raise LineageDrift("selected Creator envelope filename drift")
    media = index["media_r21"]
    if (
        envelope["review"]["package_digest"] != media["package_digest"]
        or envelope["review"]["sealed_mapping_digest"] != media["sealed_mapping_digest"]
        or envelope["review"]["review_round"] != media["review_round"]
        or envelope["capture"]["capture_digest"] != index["capture"]["capture_digest"]
        or envelope["capture"]["assistant_response_digest"]
        != index["capture"]["assistant_response_digest"]
    ):
        raise LineageDrift("Growth R27 index/envelope package/capture drift")
    if (
        candidate["source_id"] != media["source"]["source_id"]
        or candidate["source_sha256"] != media["source"]["sha256"]
    ):
        raise LineageDrift("Growth R27 source lineage drift")
    state = candidate["state"]
    selected = index["selected_result"]
    if state == "winner":
        if not isinstance(selected, Mapping) or selected.get("candidate_id") != candidate_id:
            raise LineageDrift("winner envelope differs from Growth R27 selected candidate")
    if state == "targeted_reedit":
        selected_id = index["pairwise"].get("selected_candidate_id")
        if not selected_id or selected_id == candidate_id:
            raise LineageDrift("targeted re-edit must be the non-selected reviewed candidate")
    return envelope


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                event = json.loads(line)
                material = dict(event)
                digest = material.pop("eventDigest")
                if (
                    event.get("journalVersion") != JOURNAL_VERSION
                    or event.get("sequence") != len(self.events) + 1
                    or _sha(material) != digest
                    or event.get("eventKey") in self.by_key
                ):
                    raise ReplayConflict("R30 coordinator journal corruption")
                self.events.append(event)
                self.by_key[event["eventKey"]] = event

    def append_once(self, key: str, kind: str, payload: Mapping[str, Any]) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if prior["kind"] != kind or prior["payload"] != normalized:
                raise ReplayConflict(f"conflicting coordinator replay for {key}")
            return "duplicate"
        event = {
            "journalVersion": JOURNAL_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": key,
            "kind": kind,
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
        return _sha([x for x in self.events if x["eventKey"] != "terminal"])

    def seen_rounds(self) -> list[int]:
        out = []
        for key in self.by_key:
            if key.startswith("review:"):
                out.append(int(key.split(":", 1)[1]))
        return sorted(out)


def _r22_runtime_profile() -> dict[str, Any]:
    return _clone(MEDIA_R22_RUNTIME_PROFILE)


def execute_media_r22_reedit(
    *,
    media_r22_checkout: Path,
    candidate_root: Path,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    verify_media_r22_checkout(media_r22_checkout)
    envelope = r29.validate_review_against_context(
        envelope, context, candidate_root=candidate_root
    )
    if envelope["candidate"]["state"] != "targeted_reedit":
        raise R30Error("Media re-edit requires targeted_reedit")
    if envelope["review"]["review_round"] >= MAX_REEDIT_ROUNDS:
        raise RoundOverflow("third re-edit effect rejected")
    review, adapter = r29._normalized_review(envelope, context)
    result = r28.execute_media_reedit(
        media_checkout=media_r22_checkout,
        media_profile=_r22_runtime_profile(),
        candidate_root=candidate_root,
        context=context,
        review=review,
        out_dir=out_dir,
    )
    application = result["application"]
    if (
        application.get("contractVersion") != "media.editorial_reedit_application.v1"
        or application.get("producer") != {
            "repository": MEDIA_R22_AUTHORITY["repository"],
            "sha": MEDIA_R22_AUTHORITY["producerSha"],
        }
        or application.get("handoff", {}).get("digest")
        != adapter["mediaR19CompatibilityHandoffDigest"]
        or application.get("qa", {}).get("technicalPassed") is not True
    ):
        raise LineageDrift("Media R22 real re-edit application lineage drift")
    adapter_path = (
        Path(out_dir).resolve()
        / "creator.growth_r27_media_r22_adapter.r30.v1.json"
    )
    adapter_doc = {
        "contractVersion": "creator.growth_r27_media_r22_adapter.r30.v1",
        "sourceGrowthR27ProducerSha": GROWTH_R27_AUTHORITY["producerSha"],
        "sourceGrowthR26EnvelopeDigest": envelope["envelope_digest"],
        "sourceHandoffDigest": envelope["candidate"]["handoff_digest"],
        "mediaR22ProducerSha": MEDIA_R22_AUTHORITY["producerSha"],
        "mediaR19CompatibilityAdapter": adapter,
        "modelJudgmentSynthesized": False,
        "humanLevelQualityClaimed": False,
    }
    adapter_doc["adapterDigest"] = _sha(adapter_doc)
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(
        json.dumps(adapter_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result["r30Adapter"] = adapter_doc
    result["r30AdapterPath"] = str(adapter_path)
    return result


def build_next_context(
    *,
    prior: Mapping[str, Any],
    media_result: Mapping[str, Any],
    candidate_root: Path,
) -> dict[str, Any]:
    prior = r28.validate_candidate_context(prior)
    after = media_result["evidence"]["after"]
    root = Path(candidate_root).resolve()
    final_path = Path(media_result["finalPath"]).resolve()
    app_path = Path(media_result["applicationPath"]).resolve()
    export_path = Path(media_result["renderExportPath"]).resolve()
    for path in (final_path, app_path, export_path):
        path.relative_to(root)
    candidate = {
        "candidateId": after["candidateId"].replace(":r28:", ":r30:"),
        "roundIndex": after and media_result["evidence"]["nextRoundIndex"],
        "finalPath": final_path.relative_to(root).as_posix(),
        "renderSha256": after["sha256"],
        "renderSize": after["size"],
        "renderExportPath": export_path.relative_to(root).as_posix(),
        "renderExportSha256": after["renderExportSha256"],
        "renderExportDigest": after["renderExportDigest"],
        "renderProducerSha": MEDIA_R22_AUTHORITY["producerSha"],
        "editorialApplication": {
            "path": app_path.relative_to(root).as_posix(),
            "fileSha256": after["applicationSidecarSha256"],
            "digest": after["applicationDigest"],
        },
    }
    return r28.build_candidate_context(
        loop_id=prior["loopId"],
        brief_digest=prior["briefDigest"],
        semantic_analysis_digest=prior["semanticAnalysisDigest"],
        semantic_directives_digest=prior["semanticDirectivesDigest"],
        ledger_digest=prior["ledgerDigest"],
        source=prior["source"],
        candidate=candidate,
        timeline=_clone(media_result["plan"]["timeline"]),
        export_spec=_clone(media_result["plan"]["exportSpec"]),
    )


def materialize_next_review(
    *,
    media_r21_checkout: Path,
    media_r22_checkout: Path,
    candidate_root: Path,
    before_context: Mapping[str, Any],
    after_context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    r29.verify_media_checkout(media_r21_checkout)
    verify_media_r22_checkout(media_r22_checkout)
    work = Path(work_dir).resolve()
    r21_result = r29.build_r21_next_package(
        media_checkout=media_r21_checkout,
        candidate_root=candidate_root,
        before_context=before_context,
        after_context=after_context,
        envelope=envelope,
        out_dir=work / "r21",
    )
    operator_dir = work / "r22-operator"
    env = dict(os.environ)
    env["GITHUB_SHA"] = MEDIA_R22_AUTHORITY["producerSha"]
    env["GITHUB_RUN_ID"] = str(MEDIA_R22_AUTHORITY["ciRunId"])
    proc = subprocess.run(
        [
            "node",
            str(Path(media_r22_checkout).resolve() / "tools/materialize-r22-live-review.mjs"),
            "--r21-round-dir",
            r21_result["packageDir"],
            "--out-dir",
            str(operator_dir),
        ],
        cwd=Path(media_r22_checkout).resolve(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if proc.returncode != 0:
        raise MaterializationDrift(
            "Media R22 materializer failed: " + proc.stderr[-5000:]
        )
    lines = [x for x in proc.stdout.splitlines() if x.startswith("R22_MATERIALIZED ")]
    if not lines:
        raise MaterializationDrift("Media R22 materializer result missing")
    log = json.loads(lines[-1].split(" ", 1)[1])
    operator_path = operator_dir / "media.live_review_operator_manifest.r22.v1.json"
    package_manifest_path = (
        operator_dir / "payload" / "media.live_review_package_manifest.r22.v1.json"
    )
    archive_path = operator_dir / "media-r22-live-package.tar"
    if not all(p.is_file() for p in (operator_path, package_manifest_path, archive_path)):
        raise MaterializationDrift("Media R22 operator bundle incomplete")
    operator = json.loads(operator_path.read_text(encoding="utf-8"))
    materializer = (
        operator.get("bridgeR31Inputs")
        and json.loads(
            (operator_dir / "payload" / "media.live_review_authority_profile.r22.v1.json")
            .read_text(encoding="utf-8")
        ).get("materializerR22")
    )
    expected_blobs = {
        "implementation": MEDIA_R22_AUTHORITY["blobs"]["liveReviewImplementation"],
        "materializer": MEDIA_R22_AUTHORITY["blobs"]["materializer"],
        "verifier": MEDIA_R22_AUTHORITY["blobs"]["verifier"],
        "extractor": r28._git_blob_sha(
            Path(media_r22_checkout).resolve() / "tools/extract-r22-live-review.mjs"
        ),
        "contract": MEDIA_R22_AUTHORITY["blobs"]["liveReviewContract"],
        "operatorManifestSchema": MEDIA_R22_AUTHORITY["blobs"]["operatorManifestSchema"],
    }
    if (
        log.get("producerSha") != MEDIA_R22_AUTHORITY["producerSha"]
        or log.get("materializerCiRunId") != MEDIA_R22_AUTHORITY["ciRunId"]
        or log.get("verified") is not True
        or log.get("packageDigest") != r21_result["evidence"]["packageDigest"]
        or log.get("sealedMappingDigest") != r21_result["evidence"]["sealedMappingDigest"]
        or log.get("reviewRound") != after_context["candidate"]["roundIndex"]
        or not isinstance(materializer, Mapping)
        or materializer.get("producerSha") != MEDIA_R22_AUTHORITY["producerSha"]
        or materializer.get("ciRunId") != MEDIA_R22_AUTHORITY["ciRunId"]
        or materializer.get("blobs") != expected_blobs
    ):
        raise MaterializationDrift("Media R22 materialized package identity drift")
    if (
        _file_sha(operator_path) != log["operatorManifestSha256"]
        or _file_sha(package_manifest_path) != log["packageManifestSha256"]
        or _file_sha(archive_path) != log["archiveSha256"]
        or archive_path.stat().st_size != log["archiveSize"]
    ):
        raise MaterializationDrift("Media R22 artifact bytes/hash drift")
    result = {
        "contractVersion": "creator.media_r22_materialization.r30.v1",
        "mediaR22ProducerSha": MEDIA_R22_AUTHORITY["producerSha"],
        "mediaR22CiRunId": MEDIA_R22_AUTHORITY["ciRunId"],
        "sourceMediaR21ProducerSha": r29.MEDIA_R21_AUTHORITY["producerSha"],
        "reviewRound": after_context["candidate"]["roundIndex"],
        "sourceGrowthEnvelopeDigest": envelope["envelope_digest"],
        "sourceGrowthHandoffDigest": envelope["candidate"]["handoff_digest"],
        "r21PackageDigest": r21_result["evidence"]["packageDigest"],
        "r21SealedMappingDigest": r21_result["evidence"]["sealedMappingDigest"],
        "r21RoundLineageDigest": r21_result["evidence"]["roundLineageDigest"],
        "operatorManifestSha256": log["operatorManifestSha256"],
        "packageManifestSha256": log["packageManifestSha256"],
        "archiveSha256": log["archiveSha256"],
        "archiveSize": log["archiveSize"],
        "operatorDir": str(operator_dir),
        "providerMutation": False,
        "browserMutation": False,
        "humanLevelQualityClaimed": False,
    }
    result["resultDigest"] = _sha(result)
    path = work / "creator.media_r22_materialization.r30.v1.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "evidence": result,
        "operatorDir": str(operator_dir),
        "operatorManifestPath": str(operator_path),
        "resultPath": str(path),
        "r21": r21_result,
    }


def _build_final_bundle(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    index: Mapping[str, Any],
    journal: Journal,
) -> dict[str, Any]:
    render = r28._media_render_from_context(context)
    decision = r28._winner_decision(context=context, envelope=envelope)
    bundle = {
        "contractVersion": r28.r22.FINAL_BUNDLE_VERSION,
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
            "ledgerDigest": journal.preterminal_digest,
            "growthCriticPin": {
                "authorityProfileDigest": GROWTH_R27_AUTHORITY["authorityProfileDigest"],
                "producerSha": GROWTH_R27_AUTHORITY["producerSha"],
                "envelopeDigest": envelope["envelope_digest"],
                "captureDigest": index["capture"]["capture_digest"],
            },
            "mediaRenderExport": {
                "authorityProfileDigest": _profile_digest(MEDIA_R22_AUTHORITY),
                "producerSha": context["candidate"]["renderProducerSha"],
                "renderExportDigest": context["candidate"]["renderExportDigest"],
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def _terminal_growth_validator(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_render_sha256: str,
) -> dict[str, Any]:
    envelope = r29.validate_growth_r26_envelope(value)
    if envelope["candidate"]["state"] != "winner":
        raise r23.EditorOutcomeIneligible("only terminal winner may publish")
    if (
        envelope["candidate"]["source_id"] != expected_source_id
        or envelope["candidate"]["render_sha256"] != expected_render_sha256
    ):
        raise r23.EditorPublishHandoffError("R30 terminal review lineage mismatch")
    return envelope


def _write_result(out: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(report)
    result["resultDigest"] = _sha(result)
    (out / "creator.coordinator_continuation_result.r30.v1.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _clone(result)


def run_continuation(
    *,
    media_r22_checkout: Path,
    media_r21_checkout: Path,
    growth_r27_checkout: Path,
    bridge_r31_checkout: Path | None,
    candidate_root: Path,
    candidate_context_path: Path,
    growth_index_path: Path,
    growth_envelope_path: Path | None,
    out_dir: Path,
    release_authorization_path: Path | None = None,
    publish_target: Mapping[str, str] | None = None,
    inject_lost_ack_after_media: bool = False,
    inject_lost_ack_after_materialize: bool = False,
) -> dict[str, Any]:
    media_pin = verify_media_r22_checkout(media_r22_checkout)
    r21_pin = r29.verify_media_checkout(media_r21_checkout)
    growth_pin = verify_growth_r27_checkout(growth_r27_checkout)
    bridge_pin = (
        {
            "checkoutSha": BRIDGE_R31_AUTHORITY["producerSha"],
            "profileDigest": _profile_digest(BRIDGE_R31_AUTHORITY),
            "verificationMode": "pinned_capture_identity",
        }
        if bridge_r31_checkout is None
        else verify_bridge_r31_checkout(bridge_r31_checkout)
    )
    context = r28.validate_candidate_context(
        json.loads(Path(candidate_context_path).read_text(encoding="utf-8"))
    )
    index = validate_growth_r27_index(
        json.loads(Path(growth_index_path).read_text(encoding="utf-8"))
    )
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    journal = Journal(out / "coordinator-session-journal.r30.jsonl")
    journal.append_once(
        "session",
        "session_opened",
        {
            "sourceId": context["source"]["sourceId"],
            "sourceSha256": context["source"]["sha256"],
            "mediaR22AuthorityDigest": media_pin["profileDigest"],
            "mediaR21AuthorityDigest": r21_pin["profileDigest"],
            "growthR27AuthorityDigest": growth_pin["profileDigest"],
            "growthR27PublishedAuthorityProfileDigest": GROWTH_R27_AUTHORITY["authorityProfileDigest"],
            "bridgeR31AuthorityDigest": bridge_pin["profileDigest"],
        },
    )
    if index["state"] == "BLOCKED_WAITING_GENUINE_CAPTURE":
        return _write_result(out, {
            "contractVersion": RESULT_VERSION,
            "state": "WAITING_GENUINE_CAPTURE",
            "stateHistory": ["WAITING_GENUINE_CAPTURE"],
            "reviewRound": index["media_r21"]["review_round"],
            "indexDigest": index["index_digest"],
            "sourceId": context["source"]["sourceId"],
            "sourceSha256": context["source"]["sha256"],
            "journalDigest": journal.digest,
            "providerMutation": False,
            "browserMutation": False,
            "humanLevelQualityClaimed": False,
        })
    if growth_envelope_path is None:
        raise R30Error("LIVE_REVIEW_INGESTED index requires --growth-envelope")
    envelope = validate_selected_envelope(
        index=index,
        envelope=json.loads(Path(growth_envelope_path).read_text(encoding="utf-8")),
        envelope_path=growth_envelope_path,
    )
    envelope = r29.validate_review_against_context(
        envelope, context, candidate_root=candidate_root
    )
    round_index = envelope["review"]["review_round"]
    if round_index >= MAX_REVIEW_ROUNDS:
        raise RoundOverflow("review round exceeds initial + two re-edits")
    seen = journal.seen_rounds()
    if seen and round_index < max(seen):
        raise RoundOverflow("review round regressed across restart")
    wrapper = _validate_bridge_wrapper(index["capture"]["bridge_r31_result"])
    review_payload = {
        "indexDigest": index["index_digest"],
        "envelopeDigest": envelope["envelope_digest"],
        "captureDigest": index["capture"]["capture_digest"],
        "assistantResponseDigest": index["capture"]["assistant_response_digest"],
        "bridgeR31ResultFileSha256": wrapper["result_file_sha256"],
        "bridgeR31RequestId": wrapper["request_id"],
        "bridgeR31OperationId": wrapper["operation_id"],
        "packageDigest": index["media_r21"]["package_digest"],
        "selectedEnvelopeCandidateId": envelope["candidate"]["candidate_id"],
        "selectedEnvelopeRenderSha256": envelope["candidate"]["render_sha256"],
        "selectedEnvelopeState": envelope["candidate"]["state"],
    }
    review_status = journal.append_once(
        f"review:{round_index}",
        "growth_r27_review_accepted",
        review_payload,
    )
    state = envelope["candidate"]["state"]

    if state == "targeted_reedit":
        if round_index >= MAX_REEDIT_ROUNDS:
            raise RoundOverflow("third re-edit attempt rejected")
        edit_key = "edit:" + envelope["envelope_digest"]
        prior_edit = journal.by_key.get(edit_key)
        media_result = execute_media_r22_reedit(
            media_r22_checkout=media_r22_checkout,
            candidate_root=candidate_root,
            context=context,
            envelope=envelope,
            out_dir=Path(candidate_root).resolve(),
        )
        if (
            inject_lost_ack_after_media
            and prior_edit is None
            and media_result["evidence"]["logicalEffects"] == 1
        ):
            raise InjectedLostAck("injected lost ACK after Media R22 edit effect")
        journal.append_once(
            edit_key,
            "media_r22_real_reedit",
            {
                "sourceEnvelopeDigest": envelope["envelope_digest"],
                "sourceHandoffDigest": envelope["candidate"]["handoff_digest"],
                "adapterDigest": media_result["r30Adapter"]["adapterDigest"],
                "mediaResultDigest": media_result["evidence"]["resultDigest"],
                "beforeSha256": media_result["evidence"]["before"]["sha256"],
                "afterSha256": media_result["evidence"]["after"]["sha256"],
                "afterSize": media_result["evidence"]["after"]["size"],
                "applicationSidecarSha256": media_result["evidence"]["after"]["applicationSidecarSha256"],
            },
        )
        next_context = build_next_context(
            prior=context,
            media_result=media_result,
            candidate_root=candidate_root,
        )
        next_context_path = out / "next-candidate-context.json"
        next_context_path.write_text(
            json.dumps(next_context, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        next_round = next_context["candidate"]["roundIndex"]
        if next_round > MAX_REEDIT_ROUNDS:
            raise RoundOverflow("next candidate exceeds two re-edit rounds")
        package_key = f"package:{next_round}"
        prior_package = journal.by_key.get(package_key)
        materialized = materialize_next_review(
            media_r21_checkout=media_r21_checkout,
            media_r22_checkout=media_r22_checkout,
            candidate_root=candidate_root,
            before_context=context,
            after_context=next_context,
            envelope=envelope,
            work_dir=Path(candidate_root).resolve()
            / ".creator-r30-packages"
            / envelope["envelope_digest"][:24],
        )
        if inject_lost_ack_after_materialize and prior_package is None:
            raise InjectedLostAck("injected lost ACK after Media R22 materialization")
        evidence = materialized["evidence"]
        journal.append_once(
            package_key,
            "media_r22_next_review_materialized",
            {
                "resultDigest": evidence["resultDigest"],
                "r21PackageDigest": evidence["r21PackageDigest"],
                "r21SealedMappingDigest": evidence["r21SealedMappingDigest"],
                "r21RoundLineageDigest": evidence["r21RoundLineageDigest"],
                "operatorManifestSha256": evidence["operatorManifestSha256"],
                "packageManifestSha256": evidence["packageManifestSha256"],
                "archiveSha256": evidence["archiveSha256"],
                "reviewRound": evidence["reviewRound"],
            },
        )
        (out / "next-review-materialization.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return _write_result(out, {
            "contractVersion": RESULT_VERSION,
            "state": "NEXT_REVIEW_PACKAGE_READY",
            "stateHistory": [
                "REVIEW_ACCEPTED",
                "REAL_REEDIT_EXECUTED",
                "NEXT_REVIEW_PACKAGE_READY",
            ],
            "reviewRound": round_index,
            "nextReviewRound": next_round,
            "reviewReplay": review_status == "duplicate",
            "mediaReplay": media_result["evidence"]["replayed"],
            "materializationReplay": prior_package is not None,
            "growthR27IndexDigest": index["index_digest"],
            "growthR27AuthorityProfileDigest": GROWTH_R27_AUTHORITY["authorityProfileDigest"],
            "bridgeR31CaptureDigest": wrapper["capture_digest"],
            "bridgeR31ResponseDigest": wrapper["response_digest"],
            "beforeRenderSha256": media_result["evidence"]["before"]["sha256"],
            "afterRenderSha256": media_result["evidence"]["after"]["sha256"],
            "afterRenderSize": media_result["evidence"]["after"]["size"],
            "mediaApplicationSha256": media_result["evidence"]["after"]["applicationSidecarSha256"],
            "nextR21PackageDigest": evidence["r21PackageDigest"],
            "nextR22OperatorManifestSha256": evidence["operatorManifestSha256"],
            "nextR22ArchiveSha256": evidence["archiveSha256"],
            "nextOperatorDir": materialized["operatorDir"],
            "journalDigest": journal.digest,
            "providerMutation": False,
            "browserMutation": False,
            "humanLevelQualityClaimed": False,
        })

    if state != "winner":
        terminal_state = "human_review" if state in {"human_review", "reedit_limit_reached"} else state
        journal.append_once(
            "terminal",
            "non_publishable_review_result",
            {
                "state": terminal_state,
                "envelopeDigest": envelope["envelope_digest"],
                "renderSha256": context["candidate"]["renderSha256"],
            },
        )
        return _write_result(out, {
            "contractVersion": RESULT_VERSION,
            "state": "NON_PUBLISHABLE_REVIEW_RESULT",
            "stateHistory": ["REVIEW_ACCEPTED", "NON_PUBLISHABLE_REVIEW_RESULT"],
            "reviewOutcome": terminal_state,
            "reviewRound": round_index,
            "growthR27IndexDigest": index["index_digest"],
            "journalDigest": journal.digest,
            "providerMutation": False,
            "browserMutation": False,
            "humanLevelQualityClaimed": False,
        })

    if release_authorization_path is None or publish_target is None:
        raise R30Error("winner requires release authorization and publish target")
    root = Path(candidate_root).resolve()
    source = (root / context["candidate"]["finalPath"]).resolve()
    final_path = out / "final.mp4"
    shutil.copyfile(source, final_path)
    asset = r21.probe_media(final_path)
    if (
        asset.sha256 != context["candidate"]["renderSha256"]
        or asset.size_bytes != context["candidate"]["renderSize"]
    ):
        raise LineageDrift("winner final.mp4 bytes drift")
    bundle = _build_final_bundle(
        context=context, envelope=envelope, index=index, journal=journal
    )
    (out / "editor-final-bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    auth = json.loads(Path(release_authorization_path).read_text(encoding="utf-8"))
    handoff = r23.build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=asset,
        release_authorization=auth,
        platform=publish_target["platform"],
        account_id=publish_target["accountId"],
        destination=publish_target["destination"],
        credential_ref=publish_target["credentialRef"],
        authorization_ref=publish_target["authorizationRef"],
        caption=publish_target["caption"],
        cta=publish_target["cta"],
        allow_synthetic_editor=False,
        media_render_validator=r28._validate_terminal_media,
        growth_critic_validator=_terminal_growth_validator,
    )
    (out / "editor-publish-handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    journal.append_once(
        "terminal",
        "winner_handoff_ready",
        {
            "envelopeDigest": envelope["envelope_digest"],
            "winnerCandidateId": context["candidate"]["candidateId"],
            "finalRenderSha256": asset.sha256,
            "bundleDigest": bundle["bundleDigest"],
            "publishHandoffDigest": handoff["handoffDigest"],
        },
    )
    return _write_result(out, {
        "contractVersion": RESULT_VERSION,
        "state": "WINNER_HANDOFF_READY",
        "stateHistory": ["REVIEW_ACCEPTED", "WINNER_HANDOFF_READY"],
        "reviewRound": round_index,
        "winnerCandidateId": context["candidate"]["candidateId"],
        "finalRenderSha256": asset.sha256,
        "finalRenderSize": asset.size_bytes,
        "bundleDigest": bundle["bundleDigest"],
        "publishHandoffDigest": handoff["handoffDigest"],
        "growthR27IndexDigest": index["index_digest"],
        "journalDigest": journal.digest,
        "providerMutation": False,
        "browserMutation": False,
        "humanLevelQualityClaimed": False,
    })


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": READINESS_VERSION,
        "creatorBaseSha": CREATOR_BASE_SHA,
        "state": "WAITING_GENUINE_CAPTURE",
        "SOURCE_READY": True,
        "mediaR22Authority": _clone(MEDIA_R22_AUTHORITY),
        "transitiveMediaR21Authority": _clone(r29.MEDIA_R21_AUTHORITY),
        "growthR27Authority": _clone(GROWTH_R27_AUTHORITY),
        "bridgeR31Authority": _clone(BRIDGE_R31_AUTHORITY),
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "maxReviewRounds": MAX_REVIEW_ROUNDS,
        "continuationStates": [
            "WAITING_GENUINE_CAPTURE",
            "REVIEW_ACCEPTED",
            "REAL_REEDIT_EXECUTED",
            "NEXT_REVIEW_PACKAGE_READY",
            "WINNER_HANDOFF_READY",
            "NON_PUBLISHABLE_REVIEW_RESULT",
            "BLOCKED",
        ],
        "genuineCapturePresentInRepository": False,
        "modelEvidenceSynthesizedByCreator": False,
        "providerMutation": False,
        "browserMutation": False,
        "humanParityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    return report


def run_real_mp4_rehearsal(out_dir: Path) -> dict[str, Any]:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    video = out / "source-ready.mp4"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=360x640:r=30:d=15.2",
        "-threads",
        "1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-map_metadata",
        "-1",
        str(video),
    ]
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise R30Error("real-MP4 rehearsal ffmpeg failed: " + proc.stderr[-2000:])
    asset = r21.probe_media(video)
    report = {
        "contractVersion": "creator.coordinator_real_mp4_rehearsal.r30.v1",
        "state": "WAITING_GENUINE_CAPTURE",
        "sourceReadyMp4": {
            "path": str(video),
            "sha256": asset.sha256,
            "size": asset.size_bytes,
            "durationSeconds": asset.duration_seconds,
            "width": asset.width,
            "height": asset.height,
        },
        "externalReviewBoundaryReached": True,
        "growthLiveIndexConsumed": False,
        "modelEvidenceSynthesized": False,
        "providerMutation": False,
        "browserMutation": False,
        "humanLevelQualityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    (out / "real-mp4-rehearsal.r30.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _load_json_arg(value: str) -> dict[str, Any]:
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-coordinator-r30")
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("readiness")
    ready.add_argument("--out")
    rehearse = sub.add_parser("rehearsal")
    rehearse.add_argument("--out", required=True)
    run = sub.add_parser("continue")
    run.add_argument("--media-r22-checkout", required=True)
    run.add_argument("--media-r21-checkout", required=True)
    run.add_argument("--growth-r27-checkout", required=True)
    run.add_argument(
        "--bridge-r31-checkout",
        help=(
            "Optional materialized exact Bridge R31 checkout. If omitted, "
            "R30 validates the immutable R31 producer/blob profile plus the "
            "Growth R27 embedded R31 result/capture identity."
        ),
    )
    run.add_argument("--candidate-root", required=True)
    run.add_argument("--candidate-context", required=True)
    run.add_argument("--growth-index", required=True)
    run.add_argument("--growth-envelope")
    run.add_argument("--out", required=True)
    run.add_argument("--release-authorization")
    run.add_argument("--publish-target")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        report = readiness_report()
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, sort_keys=True))
        return 2
    if args.command == "rehearsal":
        try:
            report = run_real_mp4_rehearsal(Path(args.out))
        except Exception as exc:
            print(json.dumps({"state": "BLOCKED", "reason": type(exc).__name__, "detail": str(exc)}, sort_keys=True))
            return 2
        print(json.dumps(report, sort_keys=True))
        return 0
    try:
        report = run_continuation(
            media_r22_checkout=Path(args.media_r22_checkout),
            media_r21_checkout=Path(args.media_r21_checkout),
            growth_r27_checkout=Path(args.growth_r27_checkout),
            bridge_r31_checkout=(
                None
                if not args.bridge_r31_checkout
                else Path(args.bridge_r31_checkout)
            ),
            candidate_root=Path(args.candidate_root),
            candidate_context_path=Path(args.candidate_context),
            growth_index_path=Path(args.growth_index),
            growth_envelope_path=(None if not args.growth_envelope else Path(args.growth_envelope)),
            out_dir=Path(args.out),
            release_authorization_path=(None if not args.release_authorization else Path(args.release_authorization)),
            publish_target=(None if not args.publish_target else _load_json_arg(args.publish_target)),
        )
    except Exception as exc:
        blocked = {
            "contractVersion": RESULT_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "providerMutation": False,
            "browserMutation": False,
            "humanLevelQualityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
