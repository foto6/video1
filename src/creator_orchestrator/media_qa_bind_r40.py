from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import current_authority_binder_r39 as r39

CONTRACT_VERSION = "creator.media_qa_bind.r40.v1"
READINESS_VERSION = "creator.media_qa_bind_readiness.r40.v1"
MANIFEST_VERSION = "creator.media_qa_bind_manifest.r40.v1"
STATUS_VERSION = "creator.media_qa_bind_status.r40.v1"
EVIDENCE_VERSION = "creator.media_qa_bind_evidence.r40.v1"

SOURCE_READY = "SOURCE_READY"
LOCAL_REHEARSAL_COMPLETE = "LOCAL_REHEARSAL_COMPLETE"

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "conformance" / CONTRACT_VERSION
CERTIFICATE_PATH = CONF / "source" / "creator.media_r27_independent_qa.r39.v1.json"
MATRIX_PATH = CONF / "source" / "INTEGRATION_R8_FINAL_MATRIX.6ab529846e99e572d77006dee48d6c4b01caea12.json"
SOURCE_AUTHORITY_PATH = CONF / "source-authority.json"
BRIDGE_REFRESH_PATH = CONF / "bridge-authority-refresh.json"

QA_REFRESH_SOURCE_SHA = "06ade2b1e8d40c4ab6559f3ffe1d69b0ee36fd78"
QA_CERTIFICATE_BLOB = "93a0713048ad4a8fe04cea5a1c9dbbec154fcefb"
QA_CERTIFICATE_RAW_SHA256 = "1e0d788ff59814eac1482d03c8f1934d48c08358ae5835413793c961aa361f1d"
QA_MATRIX_BLOB = "fb029a755ce1361f8ef6c2454981da47d3b716aa"
QA_MATRIX_SHA256 = "831804bedce4652156ac052e1c50f1e6f3642cd36dadbc58a00907804e646a54"
QA_PRODUCER_SHA = "6ab529846e99e572d77006dee48d6c4b01caea12"
QA_CI_RUN_ID = 37452884976
QA_ARTIFACT_ID = 11407720740
QA_ARTIFACT_DIGEST = "sha256:910326676dd9371745cb70099ec3db76a21ad7f0d5e171bcd59bddfa091bd7d8"

MEDIA_SHA = "183838a24205c6885b2366ad6ffa394164283d91"
MEDIA_CI_RUN_ID = 37451069045
MEDIA_ARTIFACT_ID = 11406357346
MEDIA_ARTIFACT_DIGEST = "sha256:9cfa2ddd358f2b25a3066ee60792c44c460c62715590210bacf5c5430d14a4b5"
MEDIA_CONTRACT = "media.real_input_local_rehearsal.r27.v1"
MEDIA_GROWTH_BUNDLE_CONTRACT = "media.real_input_growth_bundle.r27.v1"

BRIDGE_ACCEPTED_SHA = "a6adf698764776856567239b07b0687e8ac89fa5"
BRIDGE_ACCEPTED_CI = 37416629592
BRIDGE_R43_OBSERVED_SHA = "46dc74dd65bae303ecda1236e52680f7532b0912"
BRIDGE_R43_OBSERVED_CI = 37644197933


class R40Error(ValueError):
    pass


class CertificateError(R40Error):
    pass


class SourceAuthorityError(R40Error):
    pass


class BridgeAuthorityError(R40Error):
    pass


def canonical_json(value: Any) -> str:
    return r39.canonical_json(value)


def sha256_json(value: Any) -> str:
    return r39.sha256_json(value)


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _reject_moving_refs(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            low = str(key).lower()
            if "branch" in low or low in {"ref", "refname", "movingref"}:
                raise R40Error(f"moving ref field forbidden: {path}{key}")
            _reject_moving_refs(child, f"{path}{key}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_moving_refs(child, f"{path}{index}.")


def expected_certificate() -> dict[str, Any]:
    return {
        "contractVersion": "creator.media_r27_independent_qa.r39.v1",
        "repository": "foto6/boss",
        "producerSha": QA_PRODUCER_SHA,
        "ciRunId": QA_CI_RUN_ID,
        "ciConclusion": "success",
        "artifactId": QA_ARTIFACT_ID,
        "artifactDigest": QA_ARTIFACT_DIGEST,
        "matrixDigest": QA_MATRIX_SHA256,
        "disposition": "ACCEPTED",
        "acceptedMediaProducerSha": MEDIA_SHA,
        "acceptedMediaCiRunId": MEDIA_CI_RUN_ID,
        "acceptedMediaArtifactId": MEDIA_ARTIFACT_ID,
        "acceptedMediaArtifactDigest": MEDIA_ARTIFACT_DIGEST,
        "acceptedMediaContract": MEDIA_CONTRACT,
        "acceptedMediaGrowthBundleContract": MEDIA_GROWTH_BUNDLE_CONTRACT,
        "fixtureOnly": False,
    }


def validate_certificate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CertificateError("Media R27 QA certificate must be an object")
    _reject_moving_refs(value)
    if value != expected_certificate():
        raise CertificateError("stale or mismatched Media R27 QA certificate")
    if value.get("fixtureOnly") is not False:
        raise CertificateError("fixture-only QA certificate cannot authorize real local rehearsal readiness")
    try:
        validated = r39.validate_media_qa(value, r39.MEDIA_EXPECTED, allow_fixture=False)
    except Exception as exc:
        raise CertificateError(str(exc)) from exc
    return validated


def expected_source_authority() -> dict[str, Any]:
    return {
        "contractVersion": "creator.media_qa_source_authority.r40.v1",
        "repository": "foto6/boss",
        "certificateRefreshSourceSha": QA_REFRESH_SOURCE_SHA,
        "certificatePath": "hardwave_qa/certificates/creator.media_r27_independent_qa.r39.v1.json",
        "certificateBlob": QA_CERTIFICATE_BLOB,
        "certificateRawSha256": QA_CERTIFICATE_RAW_SHA256,
        "sourceMatrixPath": "hardwave_qa/certificates/source/INTEGRATION_R8_FINAL_MATRIX.6ab529846e99e572d77006dee48d6c4b01caea12.json",
        "sourceMatrixBlob": QA_MATRIX_BLOB,
        "sourceMatrixSha256": QA_MATRIX_SHA256,
        "qaProducer": {
            "producerSha": QA_PRODUCER_SHA,
            "ciRunId": QA_CI_RUN_ID,
            "ciConclusion": "success",
            "artifactId": QA_ARTIFACT_ID,
            "artifactDigest": QA_ARTIFACT_DIGEST,
        },
        "acceptedMedia": {
            "producerSha": MEDIA_SHA,
            "ciRunId": MEDIA_CI_RUN_ID,
            "artifactId": MEDIA_ARTIFACT_ID,
            "artifactDigest": MEDIA_ARTIFACT_DIGEST,
            "contract": MEDIA_CONTRACT,
            "growthBundleContract": MEDIA_GROWTH_BUNDLE_CONTRACT,
        },
        "fixtureOnly": False,
        "movingRefsAccepted": False,
    }


def validate_source_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceAuthorityError("source authority must be object")
    _reject_moving_refs(value)
    if value != expected_source_authority():
        raise SourceAuthorityError("Media QA source authority drift")
    return _clone(value)


def validate_matrix_object(matrix: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(matrix, Mapping):
        raise SourceAuthorityError("source matrix must be object")
    if matrix.get("schema_version") != "boss.integration_r8_final_matrix.v1":
        raise SourceAuthorityError("source matrix schema mismatch")
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        raise SourceAuthorityError("source matrix rows missing")
    media_rows = [row for row in rows if isinstance(row, Mapping) and row.get("role") == "MediaR27"]
    if len(media_rows) != 1:
        raise SourceAuthorityError("source matrix must contain exactly one MediaR27 row")
    media = media_rows[0]
    artifacts = media.get("artifacts")
    if (
        media.get("status") != "ACCEPTED"
        or media.get("repo") != "foto6/video2"
        or media.get("exact_sha") != MEDIA_SHA
        or not isinstance(media.get("ci"), Mapping)
        or media["ci"].get("run_id") != MEDIA_CI_RUN_ID
        or media["ci"].get("head_sha") != MEDIA_SHA
        or str(media["ci"].get("conclusion", "")).lower() != "success"
        or not isinstance(artifacts, list)
        or len(artifacts) != 1
        or artifacts[0].get("id") != MEDIA_ARTIFACT_ID
        or artifacts[0].get("digest") != MEDIA_ARTIFACT_DIGEST
        or media.get("contract") != MEDIA_CONTRACT
        or media.get("growth_bundle_contract") != MEDIA_GROWTH_BUNDLE_CONTRACT
    ):
        raise SourceAuthorityError("source matrix Media R27 acceptance tuple mismatch")
    qa = matrix.get("media_independent_qa")
    if not isinstance(qa, Mapping):
        raise SourceAuthorityError("source matrix Media independent QA section missing")
    if (
        qa.get("status") != "ACCEPTED"
        or qa.get("producer_sha") != MEDIA_SHA
        or qa.get("ci_run_id") != MEDIA_CI_RUN_ID
        or qa.get("artifact_id") != MEDIA_ARTIFACT_ID
        or qa.get("artifact_digest") != MEDIA_ARTIFACT_DIGEST
        or qa.get("contract") != MEDIA_CONTRACT
        or qa.get("growth_bundle_contract") != MEDIA_GROWTH_BUNDLE_CONTRACT
        or qa.get("live_authorization") is not False
    ):
        raise SourceAuthorityError("source matrix independent QA summary mismatch")
    boundaries = matrix.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise SourceAuthorityError("source matrix boundaries missing")
    for key in ("product_repo_mutations", "merge", "live_publish", "live_bridge_cutover", "heavy_local_render", "spectratrack"):
        if boundaries.get(key) is not False:
            raise SourceAuthorityError(f"source matrix safety boundary invalid: {key}")
    return _clone(matrix)


def validate_pinned_source() -> dict[str, Any]:
    source_authority = validate_source_authority(_load_json(SOURCE_AUTHORITY_PATH))
    if _raw_sha256(CERTIFICATE_PATH) != QA_CERTIFICATE_RAW_SHA256:
        raise SourceAuthorityError("checked-in QA certificate raw bytes do not match pinned source")
    if _raw_sha256(MATRIX_PATH) != QA_MATRIX_SHA256:
        raise SourceAuthorityError("checked-in source matrix raw bytes do not match matrixDigest")
    certificate = validate_certificate(_load_json(CERTIFICATE_PATH))
    matrix = validate_matrix_object(_load_json(MATRIX_PATH))
    if certificate["matrixDigest"] != _raw_sha256(MATRIX_PATH):
        raise SourceAuthorityError("certificate matrixDigest does not bind checked-in source matrix")
    if source_authority["qaProducer"] != {
        "producerSha": certificate["producerSha"],
        "ciRunId": certificate["ciRunId"],
        "ciConclusion": certificate["ciConclusion"],
        "artifactId": certificate["artifactId"],
        "artifactDigest": certificate["artifactDigest"],
    }:
        raise SourceAuthorityError("source authority does not bind certificate QA producer tuple")
    return {
        "sourceAuthority": source_authority,
        "certificate": certificate,
        "matrix": matrix,
        "certificateRawSha256": QA_CERTIFICATE_RAW_SHA256,
        "matrixRawSha256": QA_MATRIX_SHA256,
    }


def expected_bridge_refresh() -> dict[str, Any]:
    return _load_json(BRIDGE_REFRESH_PATH)


def validate_bridge_refresh(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BridgeAuthorityError("Bridge refresh evidence must be object")
    _reject_moving_refs(value)
    expected = expected_bridge_refresh()
    if value != expected:
        raise BridgeAuthorityError("Bridge refresh evidence drift")
    current = value.get("currentAccepted")
    observed = value.get("observedSuccessor")
    if not isinstance(current, Mapping) or not isinstance(observed, Mapping):
        raise BridgeAuthorityError("Bridge authority evidence incomplete")
    try:
        r39.validate_bridge_authority(r39.BRIDGE_EXPECTED)
    except Exception as exc:
        raise BridgeAuthorityError(str(exc)) from exc
    if (
        current.get("sourceSha") != BRIDGE_ACCEPTED_SHA
        or current.get("ciRunId") != BRIDGE_ACCEPTED_CI
        or current.get("accepted") is not True
        or value.get("selectedAuthoritySha") != BRIDGE_ACCEPTED_SHA
    ):
        raise BridgeAuthorityError("accepted Bridge R42 authority mismatch")
    if (
        observed.get("sourceSha") != BRIDGE_R43_OBSERVED_SHA
        or observed.get("ciRunId") != BRIDGE_R43_OBSERVED_CI
        or str(observed.get("ciConclusion", "")).lower() != "success"
        or observed.get("readiness") != "EXACT_HEAD_READY_FOR_CONTROLLED_PREFLIGHT"
        or observed.get("acceptedForCurrentControlPlane") is not False
    ):
        raise BridgeAuthorityError("Bridge R43 observation mismatch")
    if value.get("authorityRefreshed") is not False:
        raise BridgeAuthorityError("Bridge successor cannot be promoted without accepted control-plane evidence")
    if value.get("liveCutoverAuthorized") is not False:
        raise BridgeAuthorityError("Creator R40 cannot authorize Bridge live cutover")
    return _clone(value)


def authority_binding() -> dict[str, Any]:
    source = validate_pinned_source()
    bridge = validate_bridge_refresh(_load_json(BRIDGE_REFRESH_PATH))
    r39_set = r39.authority_set(source["certificate"])
    if r39_set["mediaQaAccepted"] is not True:
        raise CertificateError("R39 binder did not accept pinned Media R27 QA")
    if r39_set["bridge"] != r39.BRIDGE_EXPECTED:
        raise BridgeAuthorityError("R39 accepted Bridge authority drifted unexpectedly")
    value = {
        "contractVersion": "creator.media_qa_authority_binding.r40.v1",
        "r39AuthoritySetDigest": r39_set["authoritySetDigest"],
        "r39AuthorityDigests": r39_set["authorityDigests"],
        "qaSourceAuthorityDigest": sha256_json(source["sourceAuthority"]),
        "qaCertificateDigest": sha256_json(source["certificate"]),
        "qaCertificateRawSha256": source["certificateRawSha256"],
        "sourceMatrixDigest": source["matrixRawSha256"],
        "bridgeRefreshDigest": sha256_json(bridge),
        "selectedBridgeAuthoritySha": bridge["selectedAuthoritySha"],
        "bridgeAuthorityRefreshed": bridge["authorityRefreshed"],
        "mediaQaAccepted": True,
        "mediaQaFixtureOnly": False,
        "movingRefsAccepted": False,
        "providerEffects": 0,
        "browserEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
    }
    value["authorityBindingDigest"] = sha256_json(value)
    return value


def readiness() -> dict[str, Any]:
    source = validate_pinned_source()
    bridge = validate_bridge_refresh(_load_json(BRIDGE_REFRESH_PATH))
    upstream = r39.readiness(source["certificate"])
    if upstream["state"] != r39.SOURCE_READY or upstream["mediaR27QaAccepted"] is not True:
        raise R40Error("R39 current-authority binder did not advance to SOURCE_READY")
    binding = authority_binding()
    value = {
        "contractVersion": READINESS_VERSION,
        "binderContract": CONTRACT_VERSION,
        "state": SOURCE_READY,
        "localRehearsalReady": True,
        "mediaR27ExactGreen": True,
        "mediaR27QaAccepted": True,
        "mediaR27QaFixtureOnly": False,
        "qaProducerSha": QA_PRODUCER_SHA,
        "qaCiRunId": QA_CI_RUN_ID,
        "qaArtifactId": QA_ARTIFACT_ID,
        "qaArtifactDigest": QA_ARTIFACT_DIGEST,
        "qaMatrixDigest": QA_MATRIX_SHA256,
        "qaCertificateSourceSha": QA_REFRESH_SOURCE_SHA,
        "qaCertificateSourceBlob": QA_CERTIFICATE_BLOB,
        "acceptedMediaSha": MEDIA_SHA,
        "acceptedMediaCiRunId": MEDIA_CI_RUN_ID,
        "acceptedMediaArtifactId": MEDIA_ARTIFACT_ID,
        "acceptedMediaArtifactDigest": MEDIA_ARTIFACT_DIGEST,
        "bridgeCurrentAcceptedSha": BRIDGE_ACCEPTED_SHA,
        "bridgeObservedSuccessorSha": BRIDGE_R43_OBSERVED_SHA,
        "bridgeObservedSuccessorSourceGreen": True,
        "bridgeObservedSuccessorAcceptedForCurrentControlPlane": False,
        "bridgeAuthorityRefreshed": False,
        "bridgeRefreshReason": "R43 exact source is green but only READY_FOR_CONTROLLED_PREFLIGHT; no exact accepted cutover/reconcile evidence exists",
        "authorityBindingDigest": binding["authorityBindingDigest"],
        "movingRefsAccepted": False,
        "actualLocalPcE2EExecuted": False,
        "overallStackGoClaimed": False,
        "providerEffects": 0,
        "networkEffects": 0,
        "browserEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
        "liveBridgeCutover": False,
    }
    value["readinessDigest"] = sha256_json(value)
    return value


def run_fixture(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace)
    source = validate_pinned_source()
    binding = authority_binding()
    ready = readiness()
    r39_root = root / "r39-bind"
    r39_status = r39.bind_bundle(
        bundle=r39.fixture_r27_bundle(),
        media_qa=source["certificate"],
        workspace=r39_root,
        operation_id="creator-r40-media-qa-bind-fixture",
    )
    if (
        r39_status["state"] != LOCAL_REHEARSAL_COMPLETE
        or r39_status["readinessState"] != SOURCE_READY
        or r39_status["mediaQaAccepted"] is not True
        or r39_status["liveAuthorization"] is not False
        or r39_status["publishAllowed"] is not False
    ):
        raise R40Error("R39 bound fixture safety/readiness mismatch")
    r39_manifest = _load_json(r39_root / r39_status["manifestPath"])
    manifest = {
        "contractVersion": MANIFEST_VERSION,
        "state": LOCAL_REHEARSAL_COMPLETE,
        "readinessState": SOURCE_READY,
        "finalDisposition": "LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE",
        "authorityBindingDigest": binding["authorityBindingDigest"],
        "qaCertificateDigest": binding["qaCertificateDigest"],
        "qaCertificateRawSha256": QA_CERTIFICATE_RAW_SHA256,
        "sourceMatrixDigest": QA_MATRIX_SHA256,
        "bridgeRefreshDigest": binding["bridgeRefreshDigest"],
        "selectedBridgeAuthoritySha": binding["selectedBridgeAuthoritySha"],
        "bridgeAuthorityRefreshed": False,
        "r39ManifestDigest": r39_manifest["manifestDigest"],
        "r39AuthoritySetDigest": r39_manifest["authoritySetDigest"],
        "mediaQaAccepted": True,
        "mediaQaFixtureOnly": False,
        "localRehearsalReady": True,
        "providerEffects": 0,
        "networkEffects": 0,
        "browserEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
        "liveBridgeCutover": False,
        "actualLocalPcE2EExecuted": False,
        "overallStackGoClaimed": False,
    }
    manifest["manifestDigest"] = sha256_json(manifest)
    manifest_path = _write(root / "evidence" / "final-media-qa-bind-manifest.r40.json", manifest)
    _write(root / "evidence" / "authority-binding.r40.json", binding)
    _write(root / "evidence" / "readiness.r40.json", ready)
    status_value = {
        "contractVersion": STATUS_VERSION,
        "state": LOCAL_REHEARSAL_COMPLETE,
        "readinessState": SOURCE_READY,
        "manifestPath": manifest_path.relative_to(root).as_posix(),
        "manifestDigest": manifest["manifestDigest"],
        "mediaQaAccepted": True,
        "bridgeAuthorityRefreshed": False,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
    }
    status_value["statusDigest"] = sha256_json(status_value)
    _write(root / "evidence" / "status.r40.json", status_value)
    return status_value


def status(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace)
    path = root / "evidence" / "status.r40.json"
    if not path.is_file():
        return readiness()
    value = _load_json(path)
    manifest = _load_json(root / value["manifestPath"])
    material = _clone(manifest)
    digest = material.pop("manifestDigest", None)
    if digest != sha256_json(material):
        raise R40Error("R40 final manifest digest drift")
    if manifest["liveAuthorization"] is not False or manifest["publishAllowed"] is not False:
        raise R40Error("R40 live/publish safety boundary drift")
    return value


CERT_MUTATIONS = {
    "certificate_wrong_repository": (["repository"], "other/repo"),
    "certificate_wrong_qa_sha": (["producerSha"], "0" * 40),
    "certificate_wrong_qa_ci": (["ciRunId"], 1),
    "certificate_wrong_qa_conclusion": (["ciConclusion"], "failure"),
    "certificate_wrong_qa_artifact": (["artifactId"], 1),
    "certificate_wrong_qa_artifact_digest": (["artifactDigest"], "sha256:" + "0" * 64),
    "certificate_wrong_matrix_digest": (["matrixDigest"], "0" * 64),
    "certificate_pending": (["disposition"], "PENDING"),
    "certificate_wrong_media_sha": (["acceptedMediaProducerSha"], "0" * 40),
    "certificate_wrong_media_ci": (["acceptedMediaCiRunId"], 1),
    "certificate_wrong_media_artifact": (["acceptedMediaArtifactId"], 1),
    "certificate_wrong_media_artifact_digest": (["acceptedMediaArtifactDigest"], "sha256:" + "0" * 64),
    "certificate_wrong_media_contract": (["acceptedMediaContract"], "media.other.r27.v1"),
    "certificate_wrong_growth_bundle_contract": (["acceptedMediaGrowthBundleContract"], "media.other.r27.v1"),
    "certificate_fixture_only": (["fixtureOnly"], True),
}

SOURCE_MUTATIONS = {
    "source_wrong_refresh_sha": (["certificateRefreshSourceSha"], "0" * 40),
    "source_wrong_certificate_blob": (["certificateBlob"], "0" * 40),
    "source_wrong_certificate_raw_sha": (["certificateRawSha256"], "0" * 64),
    "source_wrong_matrix_blob": (["sourceMatrixBlob"], "0" * 40),
    "source_wrong_matrix_sha": (["sourceMatrixSha256"], "0" * 64),
    "source_wrong_qa_sha": (["qaProducer", "producerSha"], "0" * 40),
    "source_wrong_qa_ci": (["qaProducer", "ciRunId"], 1),
    "source_wrong_qa_artifact": (["qaProducer", "artifactId"], 1),
    "source_wrong_qa_digest": (["qaProducer", "artifactDigest"], "sha256:" + "0" * 64),
    "source_wrong_media_sha": (["acceptedMedia", "producerSha"], "0" * 40),
    "source_wrong_media_ci": (["acceptedMedia", "ciRunId"], 1),
    "source_wrong_media_artifact": (["acceptedMedia", "artifactId"], 1),
    "source_wrong_media_digest": (["acceptedMedia", "artifactDigest"], "sha256:" + "0" * 64),
    "source_fixture_only": (["fixtureOnly"], True),
    "source_moving_refs_allowed": (["movingRefsAccepted"], True),
}

BRIDGE_MUTATIONS = {
    "bridge_wrong_current_sha": (["currentAccepted", "sourceSha"], "0" * 40),
    "bridge_wrong_current_ci": (["currentAccepted", "ciRunId"], 1),
    "bridge_current_not_accepted": (["currentAccepted", "accepted"], False),
    "bridge_wrong_successor_sha": (["observedSuccessor", "sourceSha"], "0" * 40),
    "bridge_wrong_successor_ci": (["observedSuccessor", "ciRunId"], 1),
    "bridge_successor_ci_failure": (["observedSuccessor", "ciConclusion"], "failure"),
    "bridge_successor_false_acceptance": (["observedSuccessor", "acceptedForCurrentControlPlane"], True),
    "bridge_successor_false_readiness": (["observedSuccessor", "readiness"], "CURRENT_CONTROL_PLANE_ACCEPTED"),
    "bridge_selects_unaccepted_successor": (["selectedAuthoritySha"], BRIDGE_R43_OBSERVED_SHA),
    "bridge_refresh_without_acceptance": (["authorityRefreshed"], True),
    "bridge_live_cutover_authorized": (["liveCutoverAuthorized"], True),
    "bridge_artifact_digest_drift": (["observedSuccessor", "artifacts", 0, "digest"], "sha256:" + "0" * 64),
    "bridge_blob_drift": (["observedSuccessor", "blobs", "parser"], "0" * 40),
}

MATRIX_MUTATIONS = {
    "matrix_wrong_schema": (["schema_version"], "boss.other.v1"),
    "matrix_media_not_accepted": (["rows", 2, "status"], "WAITING_EXACT_GREEN"),
    "matrix_media_wrong_sha": (["rows", 2, "exact_sha"], "0" * 40),
    "matrix_media_wrong_ci": (["rows", 2, "ci", "run_id"], 1),
    "matrix_media_wrong_artifact": (["rows", 2, "artifacts", 0, "id"], 1),
    "matrix_media_wrong_digest": (["rows", 2, "artifacts", 0, "digest"], "sha256:" + "0" * 64),
    "matrix_qa_live_authorization": (["media_independent_qa", "live_authorization"], True),
    "matrix_live_publish_boundary": (["boundaries", "live_publish"], True),
    "matrix_live_bridge_cutover_boundary": (["boundaries", "live_bridge_cutover"], True),
}


def _set_path(value: dict[str, Any], path: Sequence[str | int], replacement: Any) -> None:
    node: Any = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = replacement


ADVERSARIAL_CASE_NAMES = (
    tuple(CERT_MUTATIONS)
    + ("certificate_moving_branch_ref", "certificate_extra_field",)
    + tuple(SOURCE_MUTATIONS)
    + ("source_moving_branch_ref",)
    + tuple(BRIDGE_MUTATIONS)
    + ("bridge_moving_branch_ref",)
    + tuple(MATRIX_MUTATIONS)
)


def run_one_adversarial_case(name: str) -> bool:
    try:
        if name in CERT_MUTATIONS:
            path, replacement = CERT_MUTATIONS[name]
            value = expected_certificate()
            _set_path(value, path, replacement)
            validate_certificate(value)
        elif name == "certificate_moving_branch_ref":
            value = expected_certificate()
            value["branch"] = "agent/moving"
            validate_certificate(value)
        elif name == "certificate_extra_field":
            value = expected_certificate()
            value["unexpected"] = True
            validate_certificate(value)
        elif name in SOURCE_MUTATIONS:
            path, replacement = SOURCE_MUTATIONS[name]
            value = expected_source_authority()
            _set_path(value, path, replacement)
            validate_source_authority(value)
        elif name == "source_moving_branch_ref":
            value = expected_source_authority()
            value["branch"] = "agent/moving"
            validate_source_authority(value)
        elif name in BRIDGE_MUTATIONS:
            path, replacement = BRIDGE_MUTATIONS[name]
            value = _clone(expected_bridge_refresh())
            _set_path(value, path, replacement)
            validate_bridge_refresh(value)
        elif name == "bridge_moving_branch_ref":
            value = _clone(expected_bridge_refresh())
            value["observedSuccessor"]["branch"] = "agent/moving"
            validate_bridge_refresh(value)
        elif name in MATRIX_MUTATIONS:
            path, replacement = MATRIX_MUTATIONS[name]
            value = _load_json(MATRIX_PATH)
            _set_path(value, path, replacement)
            validate_matrix_object(value)
        else:
            raise R40Error(f"unknown adversarial case: {name}")
    except (R40Error, r39.R39Error):
        return True
    return False


def adversarial_evidence() -> dict[str, Any]:
    cases = {name: run_one_adversarial_case(name) for name in ADVERSARIAL_CASE_NAMES}
    value = {
        "contractVersion": "creator.media_qa_bind_adversarial.r40.v1",
        "caseCount": len(cases),
        "allCasesPassed": all(cases.values()),
        "cases": cases,
        "liveAuthorization": False,
        "publishAllowed": False,
    }
    value["evidenceDigest"] = sha256_json(value)
    return value


def run_evidence(out_dir: str | Path) -> dict[str, Any]:
    root = Path(out_dir)
    ready = readiness()
    fixture = run_fixture(root / "fixture")
    adversarial = adversarial_evidence()
    _write(root / "readiness.r40.json", ready)
    _write(root / "adversarial-cases.r40.json", adversarial)
    summary = {
        "contractVersion": EVIDENCE_VERSION,
        "state": ready["state"],
        "localRehearsalReady": ready["localRehearsalReady"],
        "fixtureState": fixture["state"],
        "fixtureReadinessState": fixture["readinessState"],
        "mediaR27QaAccepted": True,
        "bridgeAuthorityRefreshed": False,
        "adversarialCaseCount": adversarial["caseCount"],
        "allAdversarialCasesPassed": adversarial["allCasesPassed"],
        "actualLocalPcE2EExecuted": False,
        "overallStackGoClaimed": False,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
    }
    summary["evidenceDigest"] = sha256_json(summary)
    _write(root / "evidence-summary.r40.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-media-qa-bind-r40")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("readiness")
    p.add_argument("--out")
    p = sub.add_parser("validate-certificate")
    p.add_argument("--certificate", required=True)
    p.add_argument("--out")
    p = sub.add_parser("fixture")
    p.add_argument("--workspace", required=True)
    p.add_argument("--out")
    p = sub.add_parser("status")
    p.add_argument("--workspace", required=True)
    p.add_argument("--out")
    p = sub.add_parser("evidence")
    p.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        value = readiness()
    elif args.command == "validate-certificate":
        value = {
            "contractVersion": "creator.media_qa_certificate_validation.r40.v1",
            "valid": True,
            "certificate": validate_certificate(_load_json(Path(args.certificate))),
            "liveAuthorization": False,
            "publishAllowed": False,
        }
        value["validationDigest"] = sha256_json(value)
    elif args.command == "fixture":
        value = run_fixture(args.workspace)
    elif args.command == "status":
        value = status(args.workspace)
    else:
        value = run_evidence(args.out)
    if getattr(args, "out", None) and args.command != "evidence":
        _write(Path(args.out), value)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
