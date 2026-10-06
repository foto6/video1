from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import local_fullstack_rehearsal_r38 as r38
from . import local_integration_driver_r37 as r37

CONTRACT_VERSION = "creator.current_authority_binder.r39.v1"
AUTHORITY_SET_VERSION = "creator.current_authority_set.r39.v1"
READINESS_VERSION = "creator.current_authority_readiness.r39.v1"
OPERATION_VERSION = "creator.current_authority_operation.r39.v1"
MANIFEST_VERSION = "creator.current_authority_manifest.r39.v1"
STATUS_VERSION = "creator.current_authority_status.r39.v1"

WAITING_MEDIA_R27_QA = "WAITING_MEDIA_R27_QA"
SOURCE_READY = "SOURCE_READY"
LOCAL_REHEARSAL_COMPLETE = "LOCAL_REHEARSAL_COMPLETE"

ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE = ROOT / "conformance" / CONTRACT_VERSION

CREATOR_EXPECTED = {
    "contractVersion": "creator.current_creator_authority.r39.v1",
    "repository": "foto6/video1",
    "r39AssignmentAnchor": {
        "sourceSha": "66efe791d816f07aca42d772e57eb53ad7ed331f",
        "taskBlob": "b37a8e28be305c43cd9d4f83ec6e3b1382374b2a",
        "parentR38Sha": "b4d0b3a940357eec333d5a1d9b9141bd61b89809",
    },
    "acceptedR38": {
        "producerSha": "b4d0b3a940357eec333d5a1d9b9141bd61b89809",
        "ciRunId": 37405132939,
        "ciConclusion": "success",
        "artifactId": 11387350709,
        "artifactName": "creator-r38-local-fullstack-rehearsal-b4d0b3a940357eec333d5a1d9b9141bd61b89809",
        "artifactDigest": "sha256:2b37c0a5747daf2baff343001f58d16de9b1e2ee0098ceba31e345c87e72e407",
        "contract": "creator.local_fullstack_rehearsal.r38.v1",
        "blobs": {
            "authority": "31bee01ede79db2a373a98ee47621f7928f67da6",
            "manifest": "5b0e079bb02996195a2bbf7293f783fa44ae392f",
            "schema": "6b48bb2239ecc6437bc8b273fecfccd8f89d1ebc",
            "runtime": "8a14b0787efa580d6a63195926327dbc67ecd4ce",
            "tests": "a453301a9f62c6e56dc4d04e38260668957f3bae",
            "docs": "bf47e1d008d32c221bc80b93e1a8502109e81f54",
            "readiness": "b1a078783f915c1f24a3df2dba40d60e830e16d0",
        },
    },
    "movingRefsAccepted": False,
}

GROWTH_EXPECTED = {
    "contractVersion": "creator.bound_growth_authority.r39.v1",
    "authorityClass": "CURRENT_ACCEPTED",
    "repository": "foto6/video3",
    "producerSha": "f3cb8ec0d8aa7155b6169d5f86828de3fbc9d3ba",
    "ciRunId": 37406299930,
    "ciConclusion": "success",
    "artifactId": 11387826461,
    "artifactName": "growth-r37-local-fullstack-verifier",
    "artifactDigest": "sha256:d53c063ffd68481fd88901111e1683a175e8c54fd8fc07574b6c798cd12ff463",
    "contract": "growth.local_fullstack_verifier.r37.v1",
    "blobs": {
        "authority": "6e98b021bf70359e1af2e25c6829671576ccb450",
        "contract": "cb8af8636d0991eb0a77ed59463ceeb6314592f4",
        "creatorR38Authority": "b7baa4a549bb34adbd76fcbddcec6acb4d12d1f3",
        "policy": "52a3c2f80882b8eb8d91550d3fa7950269a19425",
        "sealedBundleSchema": "210c57801733c1cc9a1523d59334a679693312b7",
        "verificationSchema": "e27c378013180324d596c1a8b360126dd5cd5b53",
        "runtime": "96c8c643a49513018f310a6db7cf1ca958c30040",
        "simulator": "f7c304310305e9c6116d08586862d2bf3d549770",
        "tests": "d39bfb3c1ea13b81befc9fb60bad0855a54bbe1f",
        "docs": "77a4fbbc927376f3a1a4b38c5a0c6215a9ebc616",
    },
    "movingRefsAccepted": False,
}

BRIDGE_EXPECTED = {
    "contractVersion": "creator.bound_bridge_authority.r39.v1",
    "authorityClass": "CURRENT_ACCEPTED_CONTROL_PLANE",
    "repository": "foto6/WebAIBridge",
    "producerSha": "a6adf698764776856567239b07b0687e8ac89fa5",
    "ciRunId": 37416629592,
    "ciConclusion": "success",
    "contract": "bridge.projects_live_control_plane_cutover.r42.v1",
    "rollbackContract": "bridge.projects_live_control_plane_rollback.r42.v1",
    "artifacts": [
        {
            "platform": "ubuntu-latest",
            "id": 11391281748,
            "name": "r42-live-control-plane-ubuntu-latest",
            "digest": "sha256:a6562035438c131650182b0e8230c2b75fb9a7f3315273874026840fe161a6af",
        },
        {
            "platform": "windows-latest",
            "id": 11391646754,
            "name": "r42-live-control-plane-windows-latest",
            "digest": "sha256:5d805a7a3354fe260f11369e0e5891cb4c792d73280092ca3df4225db7e9f03b",
        },
    ],
    "blobs": {
        "workflow": "2f5e6d08d55d98f3402d50cbcda430a62a752d11",
        "runtime": "a8516de66611848631abba2250f7bd7014f01155",
        "runtimeTests": "e0c5439d4022c7478625cf5f8ffb1a27260d8cf2",
        "contractTests": "e4978a229dab0272488f22671326941f97666451",
        "cutoverScript": "2417b6a8d1d93621ff80b6e3fe9c8f71d5d7d223",
        "rollbackScript": "a17e520c0025c759e45887848fcd92c7ebee314f",
        "readiness": "a4b880f8c6c3cc9193faac962c5008dedd9a65f6",
        "rehearsal": "f13e5a24a3e304edb18eebe08e6c3d6266778c09",
        "incidentTests": "0662281f07ac301fbb6b0be88af6944a710b0cd5",
        "powershellRegression": "bede7a58d2f77f4665f874a0672af20b2532f3a3",
    },
    "liveCutoverAuthorizedByCreator": False,
    "movingRefsAccepted": False,
}

MEDIA_EXPECTED = {
    "contractVersion": "creator.bound_media_authority.r39.v1",
    "authorityClass": "EXACT_GREEN_PENDING_INDEPENDENT_QA",
    "repository": "foto6/video2",
    "producerSha": "183838a24205c6885b2366ad6ffa394164283d91",
    "ciRunId": 37451069045,
    "ciConclusion": "success",
    "artifactId": 11406357346,
    "artifactName": "media-r27-real-input-local-rehearsal-control",
    "artifactDigest": "sha256:9cfa2ddd358f2b25a3066ee60792c44c460c62715590210bacf5c5430d14a4b5",
    "contract": "media.real_input_local_rehearsal.r27.v1",
    "growthBundleContract": "media.real_input_growth_bundle.r27.v1",
    "authorityState": "PENDING_INDEPENDENT_QA",
    "parentR26": {
        "producerSha": "dba0dce8d44c3b5786c37d2ce793172a058fb40f",
        "ciRunId": 37405928263,
        "contract": "media.local_windows_render_gate.r26.v1",
    },
    "blobs": {
        "workflow": "d22801623b4493fe9126d212d21ca143653e9fb8",
        "contract": "b86e97b0bdb9e066edd494723a58bc19cce4b714",
        "schema": "3bfbba26106400b83ccd4858a3a24ba890bb2559",
        "growthBundleContract": "256b4397bd197ddd4901bdbea119add36231c0bb",
        "runtime": "87c03720860b4497bf9a2dff44501e81be22f873",
        "runner": "770842129e6fd648728003e557bff2c611b6d95a",
        "tests": "f75a0d64142c13996acc203b26d6980813f30572",
        "ciEvidence": "e14de5437641457de744a04565006276b5218bf5",
        "runCmd": "1fd9e0fc19fac03e2be4e7777c029761bbe302f1",
        "statusCmd": "8f1ae729f2e15465eedabd7c8047107c133b0135",
        "verifyCmd": "fd48b765c8b7ac2c6519f9f20647a29830f75a31",
        "docs": "7aad17c247900da029cb341ec95f346fee5c0c26",
    },
    "independentQa": {
        "disposition": "PENDING",
        "repository": "foto6/boss",
        "producerSha": None,
        "ciRunId": None,
        "ciConclusion": None,
        "artifactId": None,
        "artifactDigest": None,
        "matrixDigest": None,
    },
    "movingRefsAccepted": False,
}


class R39Error(ValueError):
    pass


class AuthorityError(R39Error):
    pass


class MediaR27QARequired(AuthorityError):
    pass


class BundleError(R39Error):
    pass


def canonical_json(value: Any) -> str:
    return r38.canonical_json(value)


def sha256_json(value: Any) -> str:
    return r38.sha256_json(value)


def file_sha256(path: str | Path) -> str:
    return r38.file_sha256(path)


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _sha40(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise AuthorityError(f"{field} must be lowercase 40-hex")
    return value


def _sha256_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise AuthorityError(f"{field} must be sha256:<64-hex>")
    raw = value[7:]
    if any(c not in "0123456789abcdef" for c in raw):
        raise AuthorityError(f"{field} must be sha256:<64-hex>")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AuthorityError(f"{field} must be positive integer")
    return value


def _reject_moving_refs(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            low = str(key).lower()
            if "branch" in low or low in {"ref", "refname", "movingref"}:
                raise AuthorityError(f"moving ref field forbidden: {path}{key}")
            _reject_moving_refs(child, f"{path}{key}.")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _reject_moving_refs(child, f"{path}{i}.")


def _validate_blob_map(blobs: Mapping[str, Any], field: str) -> None:
    if not isinstance(blobs, Mapping) or not blobs:
        raise AuthorityError(f"{field} must be non-empty object")
    for key, value in blobs.items():
        _sha40(value, f"{field}.{key}")


def _validate_exact(value: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityError(f"{name} must be object")
    _reject_moving_refs(value)
    if value != expected:
        raise AuthorityError(f"{name} exact authority drift")
    return _clone(value)


def validate_creator_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    parsed = _validate_exact(value, CREATOR_EXPECTED, "creator")
    _sha40(parsed["r39AssignmentAnchor"]["sourceSha"], "creator.r39AssignmentAnchor.sourceSha")
    _sha40(parsed["r39AssignmentAnchor"]["taskBlob"], "creator.r39AssignmentAnchor.taskBlob")
    old = parsed["acceptedR38"]
    _sha40(old["producerSha"], "creator.acceptedR38.producerSha")
    _positive(old["ciRunId"], "creator.acceptedR38.ciRunId")
    _positive(old["artifactId"], "creator.acceptedR38.artifactId")
    _sha256_digest(old["artifactDigest"], "creator.acceptedR38.artifactDigest")
    _validate_blob_map(old["blobs"], "creator.acceptedR38.blobs")
    return parsed


def validate_growth_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    parsed = _validate_exact(value, GROWTH_EXPECTED, "growth")
    _sha40(parsed["producerSha"], "growth.producerSha")
    _positive(parsed["ciRunId"], "growth.ciRunId")
    _positive(parsed["artifactId"], "growth.artifactId")
    _sha256_digest(parsed["artifactDigest"], "growth.artifactDigest")
    _validate_blob_map(parsed["blobs"], "growth.blobs")
    return parsed


def validate_bridge_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    parsed = _validate_exact(value, BRIDGE_EXPECTED, "bridge")
    _sha40(parsed["producerSha"], "bridge.producerSha")
    _positive(parsed["ciRunId"], "bridge.ciRunId")
    for i, artifact in enumerate(parsed["artifacts"]):
        _positive(artifact["id"], f"bridge.artifacts.{i}.id")
        _sha256_digest(artifact["digest"], f"bridge.artifacts.{i}.digest")
    _validate_blob_map(parsed["blobs"], "bridge.blobs")
    return parsed


def validate_media_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    parsed = _validate_exact(value, MEDIA_EXPECTED, "media")
    _sha40(parsed["producerSha"], "media.producerSha")
    _positive(parsed["ciRunId"], "media.ciRunId")
    _positive(parsed["artifactId"], "media.artifactId")
    _sha256_digest(parsed["artifactDigest"], "media.artifactDigest")
    _sha40(parsed["parentR26"]["producerSha"], "media.parentR26.producerSha")
    _validate_blob_map(parsed["blobs"], "media.blobs")
    if parsed["authorityState"] != "PENDING_INDEPENDENT_QA":
        raise AuthorityError("Media R27 producer must not self-accept")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def checked_in_authorities() -> dict[str, dict[str, Any]]:
    values = {
        "creator": _load_json(CONFORMANCE / "creator-own-authority.json"),
        "growth": _load_json(CONFORMANCE / "growth-current-authority.json"),
        "bridge": _load_json(CONFORMANCE / "bridge-current-authority.json"),
        "media": _load_json(CONFORMANCE / "media-r27-authority.json"),
    }
    return {
        "creator": validate_creator_authority(values["creator"]),
        "growth": validate_growth_authority(values["growth"]),
        "bridge": validate_bridge_authority(values["bridge"]),
        "media": validate_media_authority(values["media"]),
    }


def fixture_media_qa() -> dict[str, Any]:
    media = MEDIA_EXPECTED
    return {
        "contractVersion": "creator.media_r27_independent_qa.r39.v1",
        "repository": "foto6/boss",
        "producerSha": "9" * 40,
        "ciRunId": 49999999039,
        "ciConclusion": "success",
        "artifactId": 12999999039,
        "artifactDigest": "sha256:" + "8" * 64,
        "matrixDigest": "7" * 64,
        "disposition": "ACCEPTED",
        "acceptedMediaProducerSha": media["producerSha"],
        "acceptedMediaCiRunId": media["ciRunId"],
        "acceptedMediaArtifactId": media["artifactId"],
        "acceptedMediaArtifactDigest": media["artifactDigest"],
        "acceptedMediaContract": media["contract"],
        "acceptedMediaGrowthBundleContract": media["growthBundleContract"],
        "fixtureOnly": True,
    }


def validate_media_qa(value: Mapping[str, Any] | None, media: Mapping[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    if value is None:
        raise MediaR27QARequired("independent QA has not accepted exact Media R27 tuple")
    _reject_moving_refs(value)
    required = {
        "contractVersion", "repository", "producerSha", "ciRunId", "ciConclusion",
        "artifactId", "artifactDigest", "matrixDigest", "disposition",
        "acceptedMediaProducerSha", "acceptedMediaCiRunId", "acceptedMediaArtifactId",
        "acceptedMediaArtifactDigest", "acceptedMediaContract", "acceptedMediaGrowthBundleContract",
    }
    allowed = required | {"fixtureOnly"}
    if set(value) - allowed or not required.issubset(value):
        raise MediaR27QARequired("Media R27 QA fields mismatch")
    if value["contractVersion"] != "creator.media_r27_independent_qa.r39.v1":
        raise MediaR27QARequired("Media R27 QA contract mismatch")
    if value["repository"] != "foto6/boss" or value["disposition"] != "ACCEPTED" or value["ciConclusion"] != "success":
        raise MediaR27QARequired("Media R27 QA acceptance missing")
    if value.get("fixtureOnly") is True and not allow_fixture:
        raise MediaR27QARequired("fixture QA cannot authorize real Media R27")
    _sha40(value["producerSha"], "mediaQa.producerSha")
    _positive(value["ciRunId"], "mediaQa.ciRunId")
    _positive(value["artifactId"], "mediaQa.artifactId")
    _sha256_digest(value["artifactDigest"], "mediaQa.artifactDigest")
    if not isinstance(value["matrixDigest"], str) or len(value["matrixDigest"]) != 64 or any(c not in "0123456789abcdef" for c in value["matrixDigest"]):
        raise MediaR27QARequired("Media R27 QA matrix digest invalid")
    if (
        value["acceptedMediaProducerSha"] != media["producerSha"]
        or value["acceptedMediaCiRunId"] != media["ciRunId"]
        or value["acceptedMediaArtifactId"] != media["artifactId"]
        or value["acceptedMediaArtifactDigest"] != media["artifactDigest"]
        or value["acceptedMediaContract"] != media["contract"]
        or value["acceptedMediaGrowthBundleContract"] != media["growthBundleContract"]
    ):
        raise MediaR27QARequired("Media R27 QA does not bind exact producer tuple")
    return _clone(value)


def authority_set(media_qa: Mapping[str, Any] | None = None, *, allow_pending_media: bool = False, allow_fixture_qa: bool = False) -> dict[str, Any]:
    values = checked_in_authorities()
    qa = None
    if media_qa is not None:
        qa = validate_media_qa(media_qa, values["media"], allow_fixture=allow_fixture_qa)
    elif not allow_pending_media:
        raise MediaR27QARequired("independent QA has not accepted exact Media R27 tuple")
    digests = {name: sha256_json(value) for name, value in values.items()}
    if qa is not None:
        digests["mediaQa"] = sha256_json(qa)
    result = {
        "contractVersion": AUTHORITY_SET_VERSION,
        "creator": values["creator"],
        "growth": values["growth"],
        "bridge": values["bridge"],
        "media": values["media"],
        "mediaQa": qa,
        "authorityDigests": digests,
        "mediaQaAccepted": qa is not None,
        "liveAuthorization": False,
        "providerMutation": False,
        "browserMutation": False,
        "socialPublish": False,
    }
    result["authoritySetDigest"] = sha256_json(result)
    return result


def verify_immutable_r38_history(workspace: Path) -> dict[str, Any]:
    legacy_media = r38.fixture_media_authority()
    r38.validate_media_authority(legacy_media, allow_fixture=True)
    root = workspace / "r38-history-control"
    status = r38.run_tiny_fixture(root)
    manifest = _load_json(root / status["manifestPath"])
    if manifest["contractVersion"] != r38.MANIFEST_VERSION:
        raise BundleError("R38 historical manifest version drift")
    if manifest["liveAuthorization"] is not False or manifest["providerEffects"] != 0:
        raise BundleError("R38 historical safety boundary drift")
    return {
        "contractVersion": "creator.r38_immutable_history_verification.r39.v1",
        "r38ManifestDigest": manifest["manifestDigest"],
        "r38LedgerDigest": manifest["ledgerDigest"],
        "r38FinalSha256": manifest["finalMp4"]["sha256"],
        "r38MediaValidatorReused": True,
        "liveAuthorization": False,
    }


def fixture_r27_bundle() -> dict[str, Any]:
    h = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    candidates = [
        {"candidateId": f"r39-fixture-candidate-{i}", "sha256": h(f"candidate-{i}"), "size": 1000 + i}
        for i in range(1, 5)
    ]
    final_hash = h("targeted-reedit")
    value = {
        "contractVersion": MEDIA_EXPECTED["growthBundleContract"],
        "mediaContractId": MEDIA_EXPECTED["contract"],
        "producer": {
            "repository": MEDIA_EXPECTED["repository"],
            "sha": MEDIA_EXPECTED["producerSha"],
            "authorityState": "PENDING_INDEPENDENT_QA",
            "acceptedByIndependentQa": False,
        },
        "operationBindingDigest": h("r39-fixture-operation-binding"),
        "inputVideo": {"pathIdentity": "fixture-input", "sha256": h("fixture-input"), "size": 2048},
        "normalizedSource": {"sha256": h("normalized-source"), "size": 1900, "normalizationSpecDigest": h("normalization-spec")},
        "candidates": candidates,
        "targetedReedit": {"candidateId": "r39-fixture-targeted-reedit", "sha256": final_hash, "size": 777, "decisionClass": "DETERMINISTIC_OFFLINE_FIXTURE"},
        "finalArtifact": {"sha256": final_hash, "size": 777},
        "files": [{"path": "final/final.mp4", "sha256": final_hash, "size": 777}],
        "evidenceBoundary": {
            "realInputBytes": False, "realEncodedMp4": False, "fixtureReviewDecision": True,
            "liveModelReview": False, "providerMutation": False, "browserMutation": False,
            "socialPublish": False, "liveAuthorization": False,
        },
    }
    value["manifestDigest"] = sha256_json(value)
    return value


def validate_r27_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BundleError("R27 bundle must be object")
    if value.get("contractVersion") != MEDIA_EXPECTED["growthBundleContract"]:
        raise BundleError("R27 bundle contract mismatch")
    if value.get("mediaContractId") != MEDIA_EXPECTED["contract"]:
        raise BundleError("R27 media contract mismatch")
    producer = value.get("producer")
    if not isinstance(producer, Mapping):
        raise BundleError("R27 producer missing")
    if (
        producer.get("repository") != MEDIA_EXPECTED["repository"]
        or producer.get("sha") != MEDIA_EXPECTED["producerSha"]
        or producer.get("authorityState") != "PENDING_INDEPENDENT_QA"
        or producer.get("acceptedByIndependentQa") is not False
    ):
        raise BundleError("R27 producer lineage mismatch")
    material = _clone(value)
    digest = material.pop("manifestDigest", None)
    if digest != sha256_json(material):
        raise BundleError("R27 bundle manifest digest mismatch")
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 4:
        raise BundleError("R27 bundle requires exactly four candidates")
    ids = [row.get("candidateId") for row in candidates]
    hashes = [row.get("sha256") for row in candidates]
    if any(not item for item in ids) or len(set(ids)) != 4 or len(set(hashes)) != 4:
        raise BundleError("R27 candidate identity/hash collision")
    for digest_value in hashes:
        if not isinstance(digest_value, str) or len(digest_value) != 64 or any(c not in "0123456789abcdef" for c in digest_value):
            raise BundleError("R27 candidate sha invalid")
    targeted = value.get("targetedReedit", {})
    final = value.get("finalArtifact", {})
    if targeted.get("sha256") != final.get("sha256"):
        raise BundleError("R27 targeted re-edit/final lineage mismatch")
    boundary = value.get("evidenceBoundary", {})
    for key in ("liveModelReview", "providerMutation", "browserMutation", "socialPublish", "liveAuthorization"):
        if boundary.get(key) is not False:
            raise BundleError(f"R27 live effect boundary breach: {key}")
    return _clone(value)


def operation_identity(operation_id: str, sealed_bundle: Mapping[str, Any], authorities: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise R39Error("operation_id is required")
    bundle = validate_r27_bundle(sealed_bundle)
    value = {
        "contractVersion": OPERATION_VERSION,
        "operationId": operation_id,
        "sealedBundleDigest": bundle["manifestDigest"],
        "authoritySetDigest": authorities["authoritySetDigest"],
        "authorityDigests": _clone(authorities["authorityDigests"]),
    }
    value["operationIdentityDigest"] = sha256_json(value)
    return value


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _growth_decision(bundle: Mapping[str, Any], authorities: Mapping[str, Any]) -> dict[str, Any]:
    value = {
        "contractVersion": "creator.growth_current_decision_binding.r39.v1",
        "growthContract": authorities["growth"]["contract"],
        "growthProducerSha": authorities["growth"]["producerSha"],
        "growthAuthorityDigest": authorities["authorityDigests"]["growth"],
        "decision": "READY_FOR_LOCAL_DEMO",
        "decisionClass": "LOCAL_AUTHORITY_BOUND_ONLY",
        "sealedBundleDigest": bundle["manifestDigest"],
        "selectedFinalSha256": bundle["finalArtifact"]["sha256"],
        "runtimeInvoked": False,
        "providerMutation": False,
        "liveAuthorization": False,
        "publishAllowed": False,
    }
    value["decisionDigest"] = sha256_json(value)
    return value


def _proof_graph(bundle: Mapping[str, Any], authorities: Mapping[str, Any], decision: Mapping[str, Any], history: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        ("SOURCE_BUNDLE_BOUND", {"sealedBundleDigest": bundle["manifestDigest"], "inputSha256": bundle["inputVideo"]["sha256"], "normalizedSourceSha256": bundle["normalizedSource"]["sha256"]}),
        ("AUTHORITIES_BOUND", {"authoritySetDigest": authorities["authoritySetDigest"], "creatorDigest": authorities["authorityDigests"]["creator"], "growthDigest": authorities["authorityDigests"]["growth"], "bridgeDigest": authorities["authorityDigests"]["bridge"], "mediaDigest": authorities["authorityDigests"]["media"]}),
        ("GROWTH_DECISION_BOUND", {"decisionDigest": decision["decisionDigest"], "selectedFinalSha256": decision["selectedFinalSha256"]}),
        ("R36_PROOF_VERIFIED", {"r36BundleDigest": history["r36BundleDigest"], "r36FinalProofDigest": history["r36FinalProofDigest"], "providerEffects": 0, "liveAuthorization": False}),
    ]
    nodes = []
    predecessor = ""
    for node_type, evidence in rows:
        node = {"nodeType": node_type, "predecessorDigest": predecessor, "evidence": evidence, "evidenceDigest": r37._sha(evidence), "nodeDigest": ""}
        node["nodeDigest"] = r37._sha({**node, "nodeDigest": ""})
        predecessor = node["nodeDigest"]
        nodes.append(node)
    proof = {"contractVersion": r37.PROOF_VERSION, "nodes": nodes, "rootDigest": nodes[0]["nodeDigest"], "finalDigest": nodes[-1]["nodeDigest"], "r36BundleDigest": history["r36BundleDigest"]}
    r37.verify_proof_graph(proof)
    return proof


def _control_proof_escrow(workspace: Path) -> dict[str, Any]:
    report = r37.run_fixture_rehearsal(workspace / "r37-proof-escrow-control")
    final = _load_json(workspace / "r37-proof-escrow-control" / "final-state.r37.json")
    escrow = final["releaseEscrow"]
    if escrow["liveAuthorization"] is not False or escrow["providerEffects"] != 0:
        raise R39Error("R37 control escrow safety drift")
    return {
        "r36BundleDigest": final["proof"]["r36BundleDigest"],
        "r36FinalProofDigest": final["proof"]["nodes"][-1]["evidence"]["r36FinalProofDigest"],
        "controlProofFinalDigest": report["proofFinalDigest"],
        "controlReleaseEscrowDigest": report["releaseEscrowDigest"],
    }


def _bind(*, bundle: Mapping[str, Any], authorities: Mapping[str, Any], workspace: Path, operation_id: str) -> dict[str, Any]:
    bundle = validate_r27_bundle(bundle)
    workspace.mkdir(parents=True, exist_ok=True)
    history = verify_immutable_r38_history(workspace)
    control = _control_proof_escrow(workspace)
    identity = operation_identity(operation_id, bundle, authorities)
    ledger = r38.StageLedger(workspace, identity=identity)

    def step(stage: str, request: Mapping[str, Any], filename: str, body: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        def work() -> Sequence[Path]:
            return [_write(workspace / filename, body)]
        records, reused = r38._run_step(ledger, stage=stage, request=request, work=work)
        return records[0], reused

    auth_record, auth_reused = step("AUTHORITY_BIND", {"authoritySetDigest": authorities["authoritySetDigest"]}, "evidence/authority-set.r39.json", authorities)
    bundle_record, bundle_reused = step("SEALED_BUNDLE_BIND", {"sealedBundleDigest": bundle["manifestDigest"]}, "evidence/sealed-media-bundle.r39.json", bundle)
    decision = _growth_decision(bundle, authorities)
    decision_record, decision_reused = step("GROWTH_DECISION_BIND", {"decisionDigest": decision["decisionDigest"]}, "evidence/growth-decision.r39.json", decision)
    proof = _proof_graph(bundle, authorities, decision, control)
    escrow = {
        "contractVersion": "creator.current_release_escrow_binding.r39.v1",
        "releaseEscrowContract": "creator.release_escrow_canary.r35.v1",
        "controlReleaseEscrowDigest": control["controlReleaseEscrowDigest"],
        "winnerRenderSha256": bundle["finalArtifact"]["sha256"],
        "proofFinalDigest": proof["finalDigest"],
        "growthDecisionDigest": decision["decisionDigest"],
        "sealedBundleDigest": bundle["manifestDigest"],
        "providerEffects": 0, "networkEffects": 0, "liveAuthorization": False, "publishAllowed": False, "escrowDigest": "",
    }
    escrow["escrowDigest"] = sha256_json({**escrow, "escrowDigest": ""})
    proof_escrow_body = {"contractVersion": "creator.current_proof_escrow_binding.r39.v1", "proof": proof, "escrow": escrow, "r38History": history, "control": control}
    proof_record, proof_reused = step(
        "PROOF_ESCROW_BIND",
        {"proofFinalDigest": proof["finalDigest"], "escrowDigest": escrow["escrowDigest"], "r38ManifestDigest": history["r38ManifestDigest"]},
        "evidence/proof-escrow.r39.json",
        proof_escrow_body,
    )

    manifest = {
        "contractVersion": MANIFEST_VERSION,
        "binderContract": CONTRACT_VERSION,
        "state": LOCAL_REHEARSAL_COMPLETE,
        "finalDisposition": "LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE",
        "readinessState": SOURCE_READY if authorities["mediaQaAccepted"] else WAITING_MEDIA_R27_QA,
        "operationIdentity": identity,
        "authoritySetDigest": authorities["authoritySetDigest"],
        "sealedBundleDigest": bundle["manifestDigest"],
        "authorityEvidence": auth_record,
        "bundleEvidence": bundle_record,
        "growthDecisionEvidence": decision_record,
        "proofEscrowEvidence": proof_record,
        "growthDecisionDigest": decision["decisionDigest"],
        "proofFinalDigest": proof["finalDigest"],
        "releaseEscrowDigest": escrow["escrowDigest"],
        "selectedWinnerSha256": bundle["finalArtifact"]["sha256"],
        "targetedReeditSha256": bundle["targetedReedit"]["sha256"],
        "ledgerDigest": ledger.digest,
        "stageReuse": {"policy": "VERIFY_COMPLETED_ARTIFACTS", "exactRerunSupported": True},
        "providerEffects": 0, "networkEffects": 0, "browserEffects": 0, "liveAuthorization": False,
        "publishAllowed": False, "liveBridgeCutover": False, "actualLocalPcE2EExecuted": False,
    }
    manifest["manifestDigest"] = sha256_json(manifest)
    manifest_path = _write(workspace / "evidence/final-current-authority-manifest.r39.json", manifest)
    status_value = {
        "contractVersion": STATUS_VERSION,
        "state": manifest["state"],
        "readinessState": manifest["readinessState"],
        "finalDisposition": manifest["finalDisposition"],
        "manifestPath": manifest_path.relative_to(workspace).as_posix(),
        "manifestDigest": manifest["manifestDigest"],
        "ledgerDigest": ledger.digest,
        "mediaQaAccepted": authorities["mediaQaAccepted"],
        "providerEffects": 0, "networkEffects": 0, "liveAuthorization": False, "publishAllowed": False,
    }
    status_value["statusDigest"] = sha256_json(status_value)
    _write(workspace / "evidence/status.r39.json", status_value)
    return status_value


def run_fixture(workspace: str | Path) -> dict[str, Any]:
    return _bind(bundle=fixture_r27_bundle(), authorities=authority_set(allow_pending_media=True), workspace=Path(workspace), operation_id="creator-r39-current-authority-fixture")


def bind_bundle(*, bundle: Mapping[str, Any], media_qa: Mapping[str, Any], workspace: str | Path, operation_id: str, allow_fixture_qa: bool = False) -> dict[str, Any]:
    return _bind(bundle=bundle, authorities=authority_set(media_qa, allow_fixture_qa=allow_fixture_qa), workspace=Path(workspace), operation_id=operation_id)


def readiness(media_qa: Mapping[str, Any] | None = None, *, allow_fixture_qa: bool = False) -> dict[str, Any]:
    checked = checked_in_authorities()
    qa = None
    state = WAITING_MEDIA_R27_QA
    blocker = "EXACT_MEDIA_R27_INDEPENDENT_QA_TUPLE_REQUIRED"
    if media_qa is not None:
        qa = validate_media_qa(media_qa, checked["media"], allow_fixture=allow_fixture_qa)
        state, blocker = SOURCE_READY, None
    digests = {name: sha256_json(value) for name, value in checked.items()}
    value = {
        "contractVersion": READINESS_VERSION, "binderContract": CONTRACT_VERSION, "state": state,
        "sourceReady": True, "mediaR27ExactGreen": True, "mediaR27QaAccepted": qa is not None, "blocker": blocker,
        "creatorAuthorityDigest": digests["creator"], "growthAuthorityDigest": digests["growth"],
        "bridgeAuthorityDigest": digests["bridge"], "mediaAuthorityDigest": digests["media"],
        "creatorR38Sha": checked["creator"]["acceptedR38"]["producerSha"], "growthCurrentSha": checked["growth"]["producerSha"],
        "bridgeCurrentSha": checked["bridge"]["producerSha"], "mediaR27Sha": checked["media"]["producerSha"],
        "mediaR27CiRunId": checked["media"]["ciRunId"], "mediaR27ArtifactId": checked["media"]["artifactId"],
        "mediaR27ArtifactDigest": checked["media"]["artifactDigest"], "movingRefsAccepted": False,
        "providerEffects": 0, "networkEffects": 0, "browserEffects": 0, "liveAuthorization": False,
        "publishAllowed": False, "liveBridgeCutover": False, "actualLocalPcE2EExecuted": False,
    }
    value["readinessDigest"] = sha256_json(value)
    return value


def status(workspace: str | Path, media_qa: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = Path(workspace)
    path = root / "evidence/status.r39.json"
    if not path.is_file():
        return readiness(media_qa)
    value = _load_json(path)
    manifest_path = root / value["manifestPath"]
    manifest = _load_json(manifest_path)
    material = _clone(manifest)
    digest = material.pop("manifestDigest")
    if digest != sha256_json(material):
        raise R39Error("R39 final manifest digest drift")
    return value


def _set_path(value: dict[str, Any], path: Sequence[str | int], replacement: Any) -> None:
    node: Any = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = replacement


MANIFEST_MUTATIONS = {
    "creator_wrong_repository": ("creator", ["repository"], "other/repo"),
    "creator_wrong_r38_sha": ("creator", ["acceptedR38", "producerSha"], "0" * 40),
    "creator_wrong_ci": ("creator", ["acceptedR38", "ciRunId"], 1),
    "creator_wrong_artifact": ("creator", ["acceptedR38", "artifactId"], 1),
    "creator_wrong_digest": ("creator", ["acceptedR38", "artifactDigest"], "sha256:" + "0" * 64),
    "creator_wrong_contract": ("creator", ["acceptedR38", "contract"], "creator.other.r38.v1"),
    "creator_blob_drift": ("creator", ["acceptedR38", "blobs", "runtime"], "0" * 40),
    "growth_wrong_repository": ("growth", ["repository"], "other/repo"),
    "growth_wrong_sha": ("growth", ["producerSha"], "0" * 40),
    "growth_wrong_ci": ("growth", ["ciRunId"], 1),
    "growth_wrong_artifact": ("growth", ["artifactId"], 1),
    "growth_wrong_digest": ("growth", ["artifactDigest"], "sha256:" + "0" * 64),
    "growth_wrong_contract": ("growth", ["contract"], "growth.other.r37.v1"),
    "growth_blob_drift": ("growth", ["blobs", "runtime"], "0" * 40),
    "bridge_wrong_repository": ("bridge", ["repository"], "other/repo"),
    "bridge_wrong_sha": ("bridge", ["producerSha"], "0" * 40),
    "bridge_wrong_ci": ("bridge", ["ciRunId"], 1),
    "bridge_wrong_artifact": ("bridge", ["artifacts", 0, "id"], 1),
    "bridge_wrong_digest": ("bridge", ["artifacts", 1, "digest"], "sha256:" + "0" * 64),
    "bridge_wrong_contract": ("bridge", ["contract"], "bridge.other.r42.v1"),
    "bridge_blob_drift": ("bridge", ["blobs", "runtime"], "0" * 40),
    "media_wrong_repository": ("media", ["repository"], "other/repo"),
    "media_wrong_sha": ("media", ["producerSha"], "0" * 40),
    "media_wrong_ci": ("media", ["ciRunId"], 1),
    "media_wrong_artifact": ("media", ["artifactId"], 1),
    "media_wrong_digest": ("media", ["artifactDigest"], "sha256:" + "0" * 64),
    "media_wrong_contract": ("media", ["contract"], "media.other.r27.v1"),
    "media_wrong_growth_contract": ("media", ["growthBundleContract"], "media.other_bundle.r27.v1"),
    "media_authority_self_accept": ("media", ["authorityState"], "ACCEPTED"),
    "media_blob_drift": ("media", ["blobs", "runtime"], "0" * 40),
}

QA_MUTATIONS = {
    "qa_wrong_repo": (["repository"], "other/repo"),
    "qa_wrong_disposition": (["disposition"], "PENDING"),
    "qa_wrong_sha_binding": (["acceptedMediaProducerSha"], "0" * 40),
    "qa_wrong_ci_binding": (["acceptedMediaCiRunId"], 1),
    "qa_wrong_artifact_binding": (["acceptedMediaArtifactId"], 1),
    "qa_wrong_digest_binding": (["acceptedMediaArtifactDigest"], "sha256:" + "0" * 64),
    "qa_wrong_contract_binding": (["acceptedMediaContract"], "media.other.r27.v1"),
    "qa_wrong_bundle_contract_binding": (["acceptedMediaGrowthBundleContract"], "media.other_bundle.r27.v1"),
}

BUNDLE_MUTATIONS = {
    "bundle_wrong_contract": (["contractVersion"], "media.other.r27.v1"),
    "bundle_wrong_media_contract": (["mediaContractId"], "media.other.r27.v1"),
    "bundle_wrong_producer_repo": (["producer", "repository"], "other/repo"),
    "bundle_wrong_producer_sha": (["producer", "sha"], "0" * 40),
    "bundle_self_accept": (["producer", "acceptedByIndependentQa"], True),
    "bundle_candidate_collision": (["candidates", 1, "sha256"], hashlib.sha256(b"candidate-1").hexdigest()),
    "bundle_final_lineage_drift": (["finalArtifact", "sha256"], hashlib.sha256(b"other-final").hexdigest()),
    "bundle_live_authorization": (["evidenceBoundary", "liveAuthorization"], True),
    "bundle_provider_mutation": (["evidenceBoundary", "providerMutation"], True),
    "bundle_browser_mutation": (["evidenceBoundary", "browserMutation"], True),
    "bundle_social_publish": (["evidenceBoundary", "socialPublish"], True),
    "bundle_manifest_digest_tamper": (["manifestDigest"], "0" * 64),
}

ADVERSARIAL_CASE_NAMES = tuple(MANIFEST_MUTATIONS) + (
    "creator_moving_branch_ref", "growth_moving_ref", "bridge_moving_branch_ref", "media_moving_branch_ref",
) + tuple(QA_MUTATIONS) + ("qa_moving_branch_ref", "qa_fixture_rejected_real") + tuple(BUNDLE_MUTATIONS)


def run_one_adversarial_case(name: str) -> bool:
    try:
        if name in MANIFEST_MUTATIONS:
            kind, path, replacement = MANIFEST_MUTATIONS[name]
            base = {"creator": CREATOR_EXPECTED, "growth": GROWTH_EXPECTED, "bridge": BRIDGE_EXPECTED, "media": MEDIA_EXPECTED}[kind]
            value = _clone(base)
            _set_path(value, path, replacement)
            {"creator": validate_creator_authority, "growth": validate_growth_authority, "bridge": validate_bridge_authority, "media": validate_media_authority}[kind](value)
        elif name in {"creator_moving_branch_ref", "growth_moving_ref", "bridge_moving_branch_ref", "media_moving_branch_ref"}:
            if name.startswith("creator"):
                value, validator = _clone(CREATOR_EXPECTED), validate_creator_authority
            elif name.startswith("growth"):
                value, validator = _clone(GROWTH_EXPECTED), validate_growth_authority
            elif name.startswith("bridge"):
                value, validator = _clone(BRIDGE_EXPECTED), validate_bridge_authority
            else:
                value, validator = _clone(MEDIA_EXPECTED), validate_media_authority
            value["branch"] = "agent/moving-ref"
            validator(value)
        elif name in QA_MUTATIONS:
            path, replacement = QA_MUTATIONS[name]
            qa = fixture_media_qa()
            _set_path(qa, path, replacement)
            validate_media_qa(qa, MEDIA_EXPECTED, allow_fixture=True)
        elif name == "qa_moving_branch_ref":
            qa = fixture_media_qa()
            qa["branch"] = "agent/moving-ref"
            validate_media_qa(qa, MEDIA_EXPECTED, allow_fixture=True)
        elif name == "qa_fixture_rejected_real":
            validate_media_qa(fixture_media_qa(), MEDIA_EXPECTED, allow_fixture=False)
        elif name in BUNDLE_MUTATIONS:
            path, replacement = BUNDLE_MUTATIONS[name]
            bundle = fixture_r27_bundle()
            _set_path(bundle, path, replacement)
            validate_r27_bundle(bundle)
        else:
            raise R39Error(f"unknown adversarial case {name}")
    except (AuthorityError, MediaR27QARequired, BundleError):
        return True
    return False


def adversarial_evidence() -> dict[str, Any]:
    cases = {name: run_one_adversarial_case(name) for name in ADVERSARIAL_CASE_NAMES}
    value = {"contractVersion": "creator.current_authority_adversarial.r39.v1", "caseCount": len(cases), "allCasesPassed": all(cases.values()), "cases": cases}
    value["evidenceDigest"] = sha256_json(value)
    return value


def run_evidence(out_dir: str | Path) -> dict[str, Any]:
    root = Path(out_dir)
    fixture_status = run_fixture(root / "fixture")
    adversarial = adversarial_evidence()
    readiness_value = readiness()
    _write(root / "adversarial-cases.r39.json", adversarial)
    _write(root / "readiness.r39.json", readiness_value)
    summary = {
        "contractVersion": "creator.current_authority_evidence.r39.v1",
        "state": readiness_value["state"],
        "fixtureState": fixture_status["state"],
        "fixtureDisposition": fixture_status["finalDisposition"],
        "mediaR27QaAccepted": False,
        "adversarialCaseCount": adversarial["caseCount"],
        "allAdversarialCasesPassed": adversarial["allCasesPassed"],
        "providerEffects": 0, "networkEffects": 0, "liveAuthorization": False, "publishAllowed": False,
        "actualLocalPcE2EExecuted": False,
    }
    summary["evidenceDigest"] = sha256_json(summary)
    _write(root / "evidence-summary.r39.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-current-authority-r39")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("readiness"); p.add_argument("--media-qa"); p.add_argument("--out")
    p = sub.add_parser("status"); p.add_argument("--workspace", required=True); p.add_argument("--media-qa"); p.add_argument("--out")
    p = sub.add_parser("fixture"); p.add_argument("--workspace", required=True); p.add_argument("--out")
    p = sub.add_parser("bind"); p.add_argument("--bundle", required=True); p.add_argument("--media-qa", required=True); p.add_argument("--workspace", required=True); p.add_argument("--operation-id", required=True); p.add_argument("--out")
    p = sub.add_parser("evidence"); p.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    exit_code = 0
    if args.command == "readiness":
        qa = _load_json(Path(args.media_qa)) if args.media_qa else None
        value = readiness(qa)
        if value["state"] == WAITING_MEDIA_R27_QA:
            exit_code = 3
    elif args.command == "status":
        qa = _load_json(Path(args.media_qa)) if args.media_qa else None
        value = status(args.workspace, qa)
    elif args.command == "fixture":
        value = run_fixture(args.workspace)
    elif args.command == "evidence":
        value = run_evidence(args.out)
    else:
        value = bind_bundle(bundle=_load_json(Path(args.bundle)), media_qa=_load_json(Path(args.media_qa)), workspace=args.workspace, operation_id=args.operation_id)
    if getattr(args, "out", None) and args.command != "evidence":
        _write(Path(args.out), value)
    print(json.dumps(value, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
