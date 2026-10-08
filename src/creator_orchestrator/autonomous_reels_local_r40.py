from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import media_qa_bind_r40 as mediaqa

CONTRACT_VERSION = "creator.autonomous_reels_local.r40.v1"
RECEIPT_VERSION = "creator.autonomous_reels_local_receipt.r40.v1"
REVIEW_VERSION = "creator.growth_quality_review_input.r40.v1"
GROWTH_AUTHORITY_VERSION = "creator.growth_r39_exact_authority.r40.v1"
BOSS_GO_VERSION = "creator.boss_r9_go.r40.v1"
ESCROW_VERSION = "creator.autonomous_reels_release_escrow.r40.v1"
PUBLISH_READINESS_VERSION = "creator.autonomous_reels_publish_readiness.r40.v1"
DIAGNOSIS_VERSION = "creator.autonomous_reels_diagnosis.r40.v1"
LEDGER_VERSION = "creator.autonomous_reels_stage_ledger.r40.v1"

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "conformance" / CONTRACT_VERSION

MEDIA_SHA = "183838a24205c6885b2366ad6ffa394164283d91"
MEDIA_CI = 37451069045
MEDIA_ARTIFACT_ID = 11406357346
MEDIA_ARTIFACT_DIGEST = "sha256:9cfa2ddd358f2b25a3066ee60792c44c460c62715590210bacf5c5430d14a4b5"
MEDIA_CONTRACT = "media.real_input_local_rehearsal.r27.v1"
MEDIA_BUNDLE_CONTRACT = "media.real_input_growth_bundle.r27.v1"
MEDIA_BRANCH = "agent/media-r27-real-input-local-rehearsal-20261006"

GROWTH_R39_TASK_SHA = "887567bb62a3df0879505d68ac6a2be725b57173"
GROWTH_R39_PARENT_SHA = "608ec634d9f38ecf054ccd63ba6e7f3a1cd79cae"
GROWTH_R39_OBSERVED_CI = 37645554562

BRIDGE_R44_SHA = "9a8898a70355bbae2d465ee49739030aa27e9f4e"
BRIDGE_R44_CI = 37726498161
BRIDGE_R44_UBUNTU_ARTIFACT_ID = 11527694819
BRIDGE_R44_UBUNTU_DIGEST = "sha256:330c144113d56132a9a9e856876c768e52e8cd82d42b18def55c4cf26092b6a6"
BRIDGE_R44_WINDOWS_ARTIFACT_ID = 11527109716
BRIDGE_R44_WINDOWS_DIGEST = "sha256:a095e50ada5f830dcee7f6d17f8befcdb452754bd8dc9068acce0bc41bacee4d"
BRIDGE_R44_CONTRACT = "bridge.hotfix_r43_integration.r44.v1"
BRIDGE_R44_READINESS = "EXACT_HEAD_READY_FOR_NEW_LOCAL_PREFLIGHT"

BOSS_R9_TASK_SHA = "9f439b41c2b11640451a803cee8b8d6198ddd04b"
BOSS_R9_PARENT_SHA = "06ade2b1e8d40c4ab6559f3ffe1d69b0ee36fd78"

MAX_REEDIT_ROUNDS = 2
PLATFORMS = {"instagram_reels", "tiktok", "youtube_shorts"}


class ReelsLocalError(ValueError):
    pass


class AuthorityBlocked(ReelsLocalError):
    pass


class ReplayConflict(ReelsLocalError):
    pass


class MediaEvidenceError(ReelsLocalError):
    pass


class ReviewError(ReelsLocalError):
    pass


class ReeditLimitReached(ReviewError):
    pass


class PublishGateError(ReelsLocalError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(path)
    return {"sha256": file_sha256(p), "size": p.stat().st_size}


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _load_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | os.PathLike[str], value: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if p.exists() and p.read_text(encoding="utf-8") != payload:
        raise ReplayConflict(f"stable JSON conflict: {p}")
    if not p.exists():
        p.write_text(payload, encoding="utf-8")
    return p


def _copy_stable(source: Path, target: Path) -> dict[str, Any]:
    expected = file_record(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        actual = file_record(target)
        if actual != expected:
            raise ReplayConflict(f"stable copy conflict: {target}")
    else:
        shutil.copyfile(source, target)
    return {"path": target.as_posix(), **expected}


def _hex(value: Any, size: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != size or any(c not in "0123456789abcdef" for c in value):
        raise ReelsLocalError(f"{field} must be lowercase {size}-hex")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReelsLocalError(f"{field} must be positive integer")
    return value


def _reject_moving_refs(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            low = str(key).lower()
            if low in {"branch", "ref", "refname", "movingref"} or "movingref" in low:
                raise ReelsLocalError(f"moving ref field forbidden: {path}{key}")
            _reject_moving_refs(child, f"{path}{key}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_moving_refs(child, f"{path}{index}.")


def authority_observation() -> dict[str, Any]:
    media = mediaqa.validate_pinned_source()["certificate"]
    value = {
        "contractVersion": "creator.autonomous_reels_authorities.r40.v1",
        "media": {
            "repository": "foto6/video2",
            "producerSha": MEDIA_SHA,
            "ciRunId": MEDIA_CI,
            "artifactId": MEDIA_ARTIFACT_ID,
            "artifactDigest": MEDIA_ARTIFACT_DIGEST,
            "contract": MEDIA_CONTRACT,
            "growthBundleContract": MEDIA_BUNDLE_CONTRACT,
            "independentQaAccepted": True,
            "qaProducerSha": media["producerSha"],
            "qaCiRunId": media["ciRunId"],
            "qaArtifactId": media["artifactId"],
            "qaArtifactDigest": media["artifactDigest"],
            "qaMatrixDigest": media["matrixDigest"],
            "fixtureOnly": False,
        },
        "growthR39": {
            "repository": "foto6/video3",
            "observedSha": GROWTH_R39_TASK_SHA,
            "parentSha": GROWTH_R39_PARENT_SHA,
            "observedCiRunId": GROWTH_R39_OBSERVED_CI,
            "observedCiConclusion": "success",
            "commitClass": "TASK_POINTER_ONLY",
            "changedFiles": ["TASKS/R39_MEDIA_QA_BIND.md"],
            "successorArtifactPresent": False,
            "acceptedForRealReview": False,
            "blocker": "R39_IMPLEMENTATION_AND_ARTIFACT_REQUIRED",
        },
        "bridgeR44": {
            "repository": "foto6/WebAIBridge",
            "producerSha": BRIDGE_R44_SHA,
            "ciRunId": BRIDGE_R44_CI,
            "ciConclusion": "success",
            "contract": BRIDGE_R44_CONTRACT,
            "readiness": BRIDGE_R44_READINESS,
            "ubuntuArtifact": {
                "id": BRIDGE_R44_UBUNTU_ARTIFACT_ID,
                "digest": BRIDGE_R44_UBUNTU_DIGEST,
            },
            "windowsArtifact": {
                "id": BRIDGE_R44_WINDOWS_ARTIFACT_ID,
                "digest": BRIDGE_R44_WINDOWS_DIGEST,
            },
            "sourceGreen": True,
            "localPreflightCutoverAccepted": False,
            "providerMutationAuthorized": False,
        },
        "bossR9": {
            "repository": "foto6/boss",
            "observedSha": BOSS_R9_TASK_SHA,
            "parentSha": BOSS_R9_PARENT_SHA,
            "commitClass": "TASK_POINTER_ONLY",
            "ciRunId": None,
            "goDisposition": None,
            "acceptedGo": False,
            "blocker": "BOSS_R9_LOCAL_PC_REHEARSAL_GO_REQUIRED",
        },
    }
    value["authorityObservationDigest"] = sha256_json(value)
    return value


def diagnosis() -> dict[str, Any]:
    auth = authority_observation()
    blockers = [
        {
            "code": "WAITING_GROWTH_R39_IMPLEMENTATION",
            "detail": "Growth R39 exact SHA is task-pointer-only; no R39 implementation/artifact can authorize real quality review.",
        },
        {
            "code": "WAITING_REAL_LOCAL_INPUT_OUTPUT_RECEIPT",
            "detail": "Creator/Media hosted CI contains no proof that a user-supplied local input produced four real rendered candidates and final export.",
        },
        {
            "code": "WAITING_BOSS_R9_GO",
            "detail": "Boss Integration R9 is task-pointer-only and has not emitted LOCAL_PC_REHEARSAL_GO.",
        },
        {
            "code": "HUMAN_REVIEW_REQUIRED_BEFORE_SEND",
            "detail": "No live Send/social publish is permitted without explicit human review even after Boss R9 GO.",
        },
    ]
    value = {
        "contractVersion": DIAGNOSIS_VERSION,
        "state": "BLOCKED_BEFORE_AUTONOMOUS_REAL_REVIEW",
        "ownerPriority": "AUTONOMOUS_SHORT_FORM_VIDEO_EDITING_AND_REELS",
        "mediaR27AuthorityReady": True,
        "growthR39AuthorityReady": False,
        "bridgeR44SourceGreen": True,
        "bridgeR44LocalCutoverAccepted": False,
        "bossR9GoAccepted": False,
        "actualLocalInputOutputReceiptPresent": False,
        "blockers": blockers,
        "nextSafeAction": "IMPLEMENTED_RUNNER_CAN_EXECUTE_AFTER_EXACT_GROWTH_R39_AUTHORITY_AND_LOCAL_DEVICE_ARE_AVAILABLE",
        "authorities": auth,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveSend": False,
        "livePublish": False,
        "liveAuthorization": False,
    }
    value["diagnosisDigest"] = sha256_json(value)
    return value


def validate_growth_authority(value: Mapping[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityBlocked("Growth authority must be object")
    _reject_moving_refs(value)
    required = {
        "contractVersion", "repository", "taskAnchorSha", "producerSha", "ciRunId",
        "ciConclusion", "artifactId", "artifactDigest", "growthContract",
        "mediaQaCertificateDigest", "sourceReadyForRealBundle", "fixtureOnly",
    }
    if set(value) != required:
        raise AuthorityBlocked("Growth R39 authority fields mismatch")
    if value["contractVersion"] != GROWTH_AUTHORITY_VERSION:
        raise AuthorityBlocked("Growth R39 authority contract mismatch")
    if value["repository"] != "foto6/video3" or value["taskAnchorSha"] != GROWTH_R39_TASK_SHA:
        raise AuthorityBlocked("Growth R39 task lineage mismatch")
    _hex(value["producerSha"], 40, "growth.producerSha")
    _positive(value["ciRunId"], "growth.ciRunId")
    _positive(value["artifactId"], "growth.artifactId")
    if value["ciConclusion"] != "success":
        raise AuthorityBlocked("Growth R39 CI is not success")
    if not isinstance(value["artifactDigest"], str) or not value["artifactDigest"].startswith("sha256:"):
        raise AuthorityBlocked("Growth R39 artifact digest invalid")
    if value["growthContract"] != "growth.media_qa_bind.r39.v1":
        raise AuthorityBlocked("Growth R39 contract mismatch")
    expected_qa_digest = sha256_json(mediaqa.validate_pinned_source()["certificate"])
    if value["mediaQaCertificateDigest"] != expected_qa_digest:
        raise AuthorityBlocked("Growth R39 does not bind accepted Media R27 QA certificate")
    if value["sourceReadyForRealBundle"] is not True:
        raise AuthorityBlocked("Growth R39 is not source-ready for a real Media bundle")
    if value["fixtureOnly"] is True and not allow_fixture:
        raise AuthorityBlocked("fixture Growth authority cannot authorize real review")
    return _clone(value)


def fixture_growth_authority() -> dict[str, Any]:
    return {
        "contractVersion": GROWTH_AUTHORITY_VERSION,
        "repository": "foto6/video3",
        "taskAnchorSha": GROWTH_R39_TASK_SHA,
        "producerSha": "7" * 40,
        "ciRunId": 49999999040,
        "ciConclusion": "success",
        "artifactId": 12999999040,
        "artifactDigest": "sha256:" + "6" * 64,
        "growthContract": "growth.media_qa_bind.r39.v1",
        "mediaQaCertificateDigest": sha256_json(mediaqa.validate_pinned_source()["certificate"]),
        "sourceReadyForRealBundle": True,
        "fixtureOnly": True,
    }


def validate_boss_go(value: Mapping[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PublishGateError("Boss R9 GO must be object")
    _reject_moving_refs(value)
    required = {
        "contractVersion", "repository", "taskAnchorSha", "producerSha", "ciRunId",
        "ciConclusion", "artifactId", "artifactDigest", "disposition",
        "creatorHeadSha", "growthProducerSha", "bridgeProducerSha", "mediaProducerSha",
        "fixtureOnly",
    }
    if set(value) != required:
        raise PublishGateError("Boss R9 GO fields mismatch")
    if value["contractVersion"] != BOSS_GO_VERSION or value["repository"] != "foto6/boss":
        raise PublishGateError("Boss R9 GO contract/repository mismatch")
    if value["taskAnchorSha"] != BOSS_R9_TASK_SHA:
        raise PublishGateError("Boss R9 GO task lineage mismatch")
    _hex(value["producerSha"], 40, "boss.producerSha")
    _positive(value["ciRunId"], "boss.ciRunId")
    _positive(value["artifactId"], "boss.artifactId")
    if value["ciConclusion"] != "success" or value["disposition"] != "LOCAL_PC_REHEARSAL_GO":
        raise PublishGateError("Boss R9 GO disposition missing")
    if value["mediaProducerSha"] != MEDIA_SHA or value["bridgeProducerSha"] != BRIDGE_R44_SHA:
        raise PublishGateError("Boss R9 GO authority tuple mismatch")
    if value["fixtureOnly"] is True and not allow_fixture:
        raise PublishGateError("fixture Boss GO cannot authorize real readiness")
    return _clone(value)


def fixture_boss_go(growth_sha: str) -> dict[str, Any]:
    return {
        "contractVersion": BOSS_GO_VERSION,
        "repository": "foto6/boss",
        "taskAnchorSha": BOSS_R9_TASK_SHA,
        "producerSha": "5" * 40,
        "ciRunId": 49999999041,
        "ciConclusion": "success",
        "artifactId": 12999999041,
        "artifactDigest": "sha256:" + "4" * 64,
        "disposition": "LOCAL_PC_REHEARSAL_GO",
        "creatorHeadSha": "fixture",
        "growthProducerSha": growth_sha,
        "bridgeProducerSha": BRIDGE_R44_SHA,
        "mediaProducerSha": MEDIA_SHA,
        "fixtureOnly": True,
    }


class StageLedger:
    def __init__(self, workspace: Path, *, identity: Mapping[str, Any]) -> None:
        self.root = workspace / "ledger"
        self.root.mkdir(parents=True, exist_ok=True)
        self.identity_path = self.root / "identity.autonomous-reels-r40.json"
        self.path = self.root / "stage-ledger.autonomous-reels-r40.jsonl"
        self.identity = _clone(identity)
        payload = json.dumps(self.identity, indent=2, sort_keys=True) + "\n"
        if self.identity_path.exists():
            if self.identity_path.read_text(encoding="utf-8") != payload:
                raise ReplayConflict("workspace identity conflict")
        else:
            self.identity_path.write_text(payload, encoding="utf-8")
        self.events: list[dict[str, Any]] = []
        if self.path.exists():
            previous = ""
            for index, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
                event = json.loads(line)
                if event["sequence"] != index or event["previousEventDigest"] != previous:
                    raise ReplayConflict("stage ledger chain corrupt")
                material = {k: v for k, v in event.items() if k != "eventDigest"}
                if sha256_json(material) != event["eventDigest"]:
                    raise ReplayConflict("stage ledger event digest corrupt")
                previous = event["eventDigest"]
                self.events.append(event)

    @property
    def digest(self) -> str:
        return self.events[-1]["eventDigest"] if self.events else sha256_json({"empty": True, "identity": self.identity})

    def append(self, *, key: str, event_type: str, request: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        request_digest = sha256_json(request)
        for event in self.events:
            if event["eventKey"] == key:
                if event["requestDigest"] != request_digest or event["evidence"] != evidence:
                    raise ReplayConflict(f"event replay conflict: {key}")
                return _clone(event), True
        event = {
            "contractVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": key,
            "eventType": event_type,
            "requestDigest": request_digest,
            "evidence": _clone(evidence),
            "previousEventDigest": self.events[-1]["eventDigest"] if self.events else "",
        }
        event["eventDigest"] = sha256_json(event)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(canonical_json(event) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self.events.append(event)
        return _clone(event), False


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="strict", stderr=subprocess.STDOUT
    ).strip()


def validate_media_checkout(media_root: Path) -> dict[str, Any]:
    root = media_root.resolve()
    if not root.is_dir():
        raise AuthorityBlocked("Media checkout missing")
    head = _git(root, "rev-parse", "HEAD")
    if head != MEDIA_SHA:
        raise AuthorityBlocked(f"Media checkout head mismatch: {head}")
    branch = _git(root, "branch", "--show-current")
    if branch != MEDIA_BRANCH:
        raise AuthorityBlocked(f"Media checkout branch mismatch: {branch}")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise AuthorityBlocked("Media checkout has tracked worktree changes")
    expected = {
        "RUN_LOCAL_R27.cmd": "1fd9e0fc19fac03e2be4e7777c029761bbe302f1",
        "STATUS_LOCAL_R27.cmd": "8f1ae729f2e15465eedabd7c8047107c133b0135",
        "VERIFY_LOCAL_R27.cmd": "fd48b765c8b7ac2c6519f9f20647a29830f75a31",
        "tools/run-r27-real-input-local.mjs": "770842129e6fd648728003e557bff2c611b6d95a",
        "src/real-input-local-rehearsal-r27.js": "87c03720860b4497bf9a2dff44501e81be22f873",
    }
    for path, blob in expected.items():
        observed = _git(root, "rev-parse", f"HEAD:{path}")
        if observed != blob:
            raise AuthorityBlocked(f"Media checkout blob drift: {path}")
    return {"root": str(root), "head": head, "branch": branch, "blobs": expected}


def _cmd(media_root: Path, name: str, *args: str) -> None:
    if os.name != "nt":
        raise AuthorityBlocked("real Media R27 rehearsal requires Windows")
    command = ["cmd.exe", "/d", "/s", "/c", str(media_root / name), *map(str, args)]
    subprocess.run(command, cwd=media_root, check=True)


def run_media_r27(*, source: Path, media_root: Path, output_root: Path, ledger: StageLedger) -> dict[str, Any]:
    validate_media_checkout(media_root)
    if not source.is_file():
        raise MediaEvidenceError("source file missing")
    source_id = file_record(source)
    request = {
        "mediaSha": MEDIA_SHA,
        "sourceSha256": source_id["sha256"],
        "sourceSize": source_id["size"],
        "outputRoot": str(output_root.resolve()),
    }
    ledger.append(key="MEDIA_R27:STARTED", event_type="STAGE_STARTED", request=request, evidence={"started": True})
    manifest_path = output_root / "growth" / "media.real_input_growth_bundle.r27.manifest.json"
    if manifest_path.is_file():
        manifest = verify_media_output(source=source, output_root=output_root)
        reused = True
    else:
        _cmd(media_root, "RUN_LOCAL_R27.cmd", str(source.resolve()), str(output_root.resolve()))
        _cmd(media_root, "VERIFY_LOCAL_R27.cmd", str(output_root.resolve()))
        manifest = verify_media_output(source=source, output_root=output_root)
        reused = False
    evidence = {
        "manifestDigest": manifest["manifestDigest"],
        "candidateHashes": [row["sha256"] for row in manifest["candidates"]],
        "finalArtifact": manifest["finalArtifact"],
        "reused": reused,
    }
    ledger.append(key="MEDIA_R27:COMPLETED", event_type="STAGE_COMPLETED", request=request, evidence=evidence)
    return {"manifest": manifest, "reused": reused}


def verify_media_output(*, source: Path, output_root: Path) -> dict[str, Any]:
    manifest_path = output_root / "growth" / "media.real_input_growth_bundle.r27.manifest.json"
    if not manifest_path.is_file():
        raise MediaEvidenceError("Media R27 Growth manifest missing")
    manifest = _load_json(manifest_path)
    if manifest.get("contractVersion") != MEDIA_BUNDLE_CONTRACT or manifest.get("mediaContractId") != MEDIA_CONTRACT:
        raise MediaEvidenceError("Media R27 bundle contract mismatch")
    producer = manifest.get("producer", {})
    if producer.get("repository") != "foto6/video2" or producer.get("sha") != MEDIA_SHA:
        raise MediaEvidenceError("Media R27 producer mismatch")
    if producer.get("authorityState") != "PENDING_INDEPENDENT_QA" or producer.get("acceptedByIndependentQa") is not False:
        raise MediaEvidenceError("Media R27 producer self-authority boundary drift")
    material = _clone(manifest)
    digest = material.pop("manifestDigest", None)
    if digest != sha256_json(material):
        raise MediaEvidenceError("Media R27 bundle manifest digest mismatch")
    source_id = file_record(source)
    if manifest.get("inputVideo", {}).get("sha256") != source_id["sha256"] or manifest["inputVideo"].get("size") != source_id["size"]:
        raise MediaEvidenceError("Media R27 source identity mismatch")
    boundary = manifest.get("evidenceBoundary", {})
    if boundary.get("realInputBytes") is not True or boundary.get("realEncodedMp4") is not True:
        raise MediaEvidenceError("Media R27 real-input/encoded evidence missing")
    for key in ("liveModelReview", "providerMutation", "browserMutation", "socialPublish", "liveAuthorization"):
        if boundary.get(key) is not False:
            raise MediaEvidenceError(f"Media R27 live boundary breach: {key}")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 4:
        raise MediaEvidenceError("exactly four Media R27 candidates required")
    ids, hashes = set(), set()
    for row in candidates:
        cid = row.get("candidateId")
        sha = row.get("sha256")
        if not cid or cid in ids or not isinstance(sha, str) or len(sha) != 64 or sha in hashes:
            raise MediaEvidenceError("candidate identities/hashes must be four distinct values")
        ids.add(cid)
        hashes.add(sha)
        candidate_path = output_root / "growth" / "payload" / "candidates" / cid / "final.mp4"
        if not candidate_path.is_file():
            raise MediaEvidenceError(f"candidate file missing: {cid}")
        actual = file_record(candidate_path)
        if actual["sha256"] != sha or actual["size"] != row.get("size"):
            raise MediaEvidenceError(f"candidate file drift: {cid}")
    final_path = output_root / "final" / "final.mp4"
    if not final_path.is_file() or file_record(final_path) != manifest.get("finalArtifact"):
        raise MediaEvidenceError("Media R27 final artifact mismatch")
    return manifest


def _candidate_map(manifest: Mapping[str, Any], output_root: Path) -> dict[str, dict[str, Any]]:
    return {
        row["candidateId"]: {
            "candidateId": row["candidateId"],
            "sha256": row["sha256"],
            "size": row["size"],
            "path": output_root / "growth" / "payload" / "candidates" / row["candidateId"] / "final.mp4",
        }
        for row in manifest["candidates"]
    }


def validate_review(
    value: Mapping[str, Any],
    *,
    growth_authority: Mapping[str, Any],
    media_bundle_digest: str,
    round_number: int,
    available: Mapping[str, Mapping[str, Any]],
    allow_fixture: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewError("review must be object")
    _reject_moving_refs(value)
    required = {
        "contractVersion", "evidenceClass", "fixtureOnly", "growthProducerSha",
        "growthArtifactDigest", "mediaBundleDigest", "reviewRound", "decision",
        "selectedCandidateId", "selectedSha256", "qualityScores", "directives",
        "reeditRequest", "providerMutation", "livePublish", "reviewDigest",
    }
    if set(value) != required:
        raise ReviewError("review fields mismatch")
    if value["contractVersion"] != REVIEW_VERSION:
        raise ReviewError("review contract mismatch")
    if value["evidenceClass"] != "REAL_LOCAL_REVIEW" and not allow_fixture:
        raise ReviewError("real local review evidence required")
    if value["fixtureOnly"] is True and not allow_fixture:
        raise ReviewError("fixture review cannot advance real local loop")
    if value["growthProducerSha"] != growth_authority["producerSha"] or value["growthArtifactDigest"] != growth_authority["artifactDigest"]:
        raise ReviewError("review Growth authority binding mismatch")
    if value["mediaBundleDigest"] != media_bundle_digest or value["reviewRound"] != round_number:
        raise ReviewError("review bundle/round binding mismatch")
    if value["providerMutation"] is not False or value["livePublish"] is not False:
        raise ReviewError("review cannot claim live/provider effects")
    cid = value["selectedCandidateId"]
    if cid not in available or value["selectedSha256"] != available[cid]["sha256"]:
        raise ReviewError("review selection does not bind available candidate bytes")
    decision = value["decision"]
    if decision not in {"WINNER", "REEDIT", "HUMAN_REVIEW_REQUIRED"}:
        raise ReviewError("unsupported review decision")
    if decision == "REEDIT":
        if round_number >= MAX_REEDIT_ROUNDS:
            raise ReeditLimitReached("third re-edit is forbidden")
        request = value["reeditRequest"]
        if not isinstance(request, Mapping) or request.get("contractVersion") != "media.editorial_reedit_request.r19.v1":
            raise ReviewError("REEDIT requires exact Media R19 request")
    elif value["reeditRequest"] is not None:
        raise ReviewError("non-REEDIT decision must not carry re-edit request")
    material = _clone(value)
    digest = material["reviewDigest"]
    material["reviewDigest"] = ""
    if sha256_json(material) != digest:
        raise ReviewError("review digest mismatch")
    return _clone(value)


def _execute_reedit(
    *,
    media_root: Path,
    workspace: Path,
    round_number: int,
    review: Mapping[str, Any],
    ledger: StageLedger,
) -> dict[str, Any]:
    validate_media_checkout(media_root)
    request = _clone(review["reeditRequest"])
    request_path = workspace / "reviews" / f"round-{round_number}-media-r19-request.json"
    request["requestId"] = request.get("requestId") or f"creator-r40-round-{round_number + 1}"
    _write_json(request_path, request)
    out = workspace / "reedits" / f"round-{round_number + 1}"
    evidence_request = {
        "round": round_number + 1,
        "requestDigest": sha256_json(request),
        "selectedSha256": review["selectedSha256"],
    }
    ledger.append(
        key=f"REEDIT_{round_number + 1}:STARTED",
        event_type="STAGE_STARTED",
        request=evidence_request,
        evidence={"started": True},
    )
    final_path = out / "final.mp4"
    if final_path.is_file():
        reused = True
    else:
        env = dict(os.environ)
        runtime_bin = workspace / "media-r27" / "runtime" / "ffmpeg" / "bin"
        if runtime_bin.is_dir():
            env["PATH"] = str(runtime_bin) + os.pathsep + env.get("PATH", "")
        subprocess.run(
            [
                "node",
                str(media_root / "tools" / "run-r19-editorial-reedit.mjs"),
                "--request",
                str(request_path),
                "--sandbox-root",
                str(workspace),
                "--output-dir",
                str(out),
            ],
            cwd=media_root,
            check=True,
            env=env,
        )
        reused = False
    if not final_path.is_file():
        raise MediaEvidenceError("Media R19 re-edit did not produce final.mp4")
    identity = file_record(final_path)
    app_path = out / "media.editorial_reedit_application.v1.json"
    render_path = out / "media.render_export.v1.json"
    evidence_path = out / "media.editorial_reedit_runtime.r19.evidence.json"
    for path in (app_path, render_path, evidence_path):
        if not path.is_file():
            raise MediaEvidenceError(f"Media R19 evidence missing: {path.name}")
    evidence = _load_json(evidence_path)
    if evidence.get("humanQuality") is not False or evidence.get("publishPerformed") is not False:
        raise MediaEvidenceError("Media R19 quality/publish boundary drift")
    ledger.append(
        key=f"REEDIT_{round_number + 1}:COMPLETED",
        event_type="STAGE_COMPLETED",
        request=evidence_request,
        evidence={"output": identity, "reused": reused, "r19EvidenceSha256": file_sha256(evidence_path)},
    )
    return {
        "candidateId": f"reedit-{round_number + 1}",
        "sha256": identity["sha256"],
        "size": identity["size"],
        "path": final_path,
        "r19EvidenceSha256": file_sha256(evidence_path),
        "reused": reused,
    }


def release_escrow(
    *,
    workspace: Path,
    source: Mapping[str, Any],
    final: Mapping[str, Any],
    media_bundle_digest: str,
    review_chain: Sequence[Mapping[str, Any]],
    authority_digest: str,
    ledger: StageLedger,
) -> dict[str, Any]:
    value = {
        "contractVersion": ESCROW_VERSION,
        "source": _clone(source),
        "final": {"sha256": final["sha256"], "size": final["size"]},
        "mediaBundleDigest": media_bundle_digest,
        "reviewChainDigest": sha256_json(list(review_chain)),
        "authorityDigest": authority_digest,
        "reviewRounds": len(review_chain),
        "reeditRounds": sum(1 for row in review_chain if row["decision"] == "REEDIT"),
        "humanReviewRequiredBeforeSend": True,
        "bossR9GoRequiredBeforeSend": True,
        "liveAuthorization": False,
        "publishAllowed": False,
        "providerMutation": False,
        "escrowDigest": "",
    }
    value["escrowDigest"] = sha256_json({**value, "escrowDigest": ""})
    _write_json(workspace / "evidence" / "release-escrow.r40.json", value)
    ledger.append(
        key="RELEASE_ESCROW:COMPLETED",
        event_type="RELEASE_ESCROWED",
        request={"finalSha256": final["sha256"], "authorityDigest": authority_digest},
        evidence={"escrowDigest": value["escrowDigest"]},
    )
    return value


def publish_readiness(
    *,
    final: Mapping[str, Any],
    escrow: Mapping[str, Any],
    platform: str,
    account_ref: str,
    destination: str,
    caption: str,
    title: str,
    human_review: Mapping[str, Any] | None = None,
    boss_go: Mapping[str, Any] | None = None,
    growth_authority: Mapping[str, Any] | None = None,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise PublishGateError("unsupported short-form platform")
    if not account_ref or not destination:
        raise PublishGateError("account_ref and destination are required")
    human_approved = False
    human_digest = None
    if human_review is not None:
        if set(human_review) != {"contractVersion", "approved", "finalSha256", "reviewerRef", "reviewDigest"}:
            raise PublishGateError("human review fields mismatch")
        if human_review["contractVersion"] != "creator.human_final_review.r40.v1":
            raise PublishGateError("human review contract mismatch")
        material = _clone(human_review)
        digest = material["reviewDigest"]
        material["reviewDigest"] = ""
        if digest != sha256_json(material) or human_review["finalSha256"] != final["sha256"]:
            raise PublishGateError("human review digest/final binding mismatch")
        human_approved = human_review["approved"] is True
        human_digest = digest
    boss_accepted = False
    boss_digest = None
    if boss_go is not None:
        if growth_authority is None:
            raise PublishGateError("Boss GO validation requires Growth authority")
        validated = validate_boss_go(boss_go, allow_fixture=allow_fixture)
        if validated["growthProducerSha"] != growth_authority["producerSha"]:
            raise PublishGateError("Boss GO Growth binding mismatch")
        boss_accepted = True
        boss_digest = sha256_json(validated)
    identity = {
        "platform": platform,
        "accountRef": account_ref,
        "destination": destination,
        "finalSha256": final["sha256"],
        "finalSize": final["size"],
        "escrowDigest": escrow["escrowDigest"],
        "captionSha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
        "titleSha256": hashlib.sha256(title.encode("utf-8")).hexdigest(),
    }
    transaction_id = "r40reels:" + sha256_json(identity)
    value = {
        "contractVersion": PUBLISH_READINESS_VERSION,
        "transactionId": transaction_id,
        "idempotencyKey": "r40idem:" + sha256_json({"transactionId": transaction_id, "platform": platform}),
        "state": "PREPARED_HUMAN_BOSS_GATE",
        "identity": identity,
        "humanReviewApproved": human_approved,
        "humanReviewDigest": human_digest,
        "bossR9GoAccepted": boss_accepted,
        "bossR9GoDigest": boss_digest,
        "allExternalGatesSatisfied": human_approved and boss_accepted,
        "sendCommandImplemented": False,
        "sendPermitted": False,
        "blindRetryPermitted": False,
        "readOnlyReconciliationOnlyAfterUnknownOutcome": True,
        "networkPermitted": False,
        "providerMutation": False,
        "liveSend": False,
        "livePublish": False,
        "liveAuthorization": False,
    }
    value["readinessDigest"] = sha256_json(value)
    return value


def run_local(
    *,
    source: Path,
    workspace: Path,
    media_root: Path,
    growth_authority: Mapping[str, Any],
    review_dir: Path,
    platform: str,
    account_ref: str,
    destination: str,
    caption: str,
    title: str,
    human_review: Mapping[str, Any] | None = None,
    boss_go: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    growth = validate_growth_authority(growth_authority)
    mediaqa.validate_pinned_source()
    validate_media_checkout(media_root)
    if not source.is_file():
        raise ReelsLocalError("source file missing")
    source_id = file_record(source)
    authority = authority_observation()
    authority_digest = sha256_json({"observation": authority, "growth": growth})
    identity = {
        "contractVersion": CONTRACT_VERSION,
        "source": source_id,
        "mediaSha": MEDIA_SHA,
        "growthProducerSha": growth["producerSha"],
        "bridgeR44Sha": BRIDGE_R44_SHA,
        "authorityDigest": authority_digest,
    }
    workspace.mkdir(parents=True, exist_ok=True)
    ledger = StageLedger(workspace, identity=identity)
    media_output = workspace / "media-r27"
    media_result = run_media_r27(source=source, media_root=media_root, output_root=media_output, ledger=ledger)
    manifest = media_result["manifest"]
    available = _candidate_map(manifest, media_output)
    review_chain: list[dict[str, Any]] = []
    current_round = 0
    while True:
        review_path = review_dir / f"round-{current_round}.json"
        if not review_path.is_file():
            raise ReviewError(f"quality review missing: {review_path}")
        review = validate_review(
            _load_json(review_path),
            growth_authority=growth,
            media_bundle_digest=manifest["manifestDigest"],
            round_number=current_round,
            available=available,
        )
        review_chain.append(review)
        ledger.append(
            key=f"REVIEW_{current_round}:COMPLETED",
            event_type="QUALITY_REVIEW_ACCEPTED",
            request={"round": current_round, "reviewDigest": review["reviewDigest"]},
            evidence={"decision": review["decision"], "selectedSha256": review["selectedSha256"]},
        )
        if review["decision"] == "HUMAN_REVIEW_REQUIRED":
            raise ReviewError("quality review requires human intervention before final export")
        if review["decision"] == "WINNER":
            final_source = Path(available[review["selectedCandidateId"]]["path"])
            break
        child = _execute_reedit(
            media_root=media_root,
            workspace=workspace,
            round_number=current_round,
            review=review,
            ledger=ledger,
        )
        current_round += 1
        available = {child["candidateId"]: child}
    final_path = workspace / "final" / "final.mp4"
    final_rec = _copy_stable(final_source, final_path)
    final = {"sha256": final_rec["sha256"], "size": final_rec["size"], "path": "final/final.mp4"}
    ledger.append(
        key="FINAL_EXPORT:COMPLETED",
        event_type="FINAL_EXPORTED",
        request={"selectedSha256": final["sha256"]},
        evidence=final,
    )
    escrow = release_escrow(
        workspace=workspace,
        source=source_id,
        final=final,
        media_bundle_digest=manifest["manifestDigest"],
        review_chain=review_chain,
        authority_digest=authority_digest,
        ledger=ledger,
    )
    publish = publish_readiness(
        final=final,
        escrow=escrow,
        platform=platform,
        account_ref=account_ref,
        destination=destination,
        caption=caption,
        title=title,
        human_review=human_review,
        boss_go=boss_go,
        growth_authority=growth,
    )
    _write_json(workspace / "evidence" / "publish-readiness.r40.json", publish)
    receipt = {
        "contractVersion": RECEIPT_VERSION,
        "state": "LOCAL_REAL_REELS_REHEARSAL_COMPLETE",
        "source": source_id,
        "mediaProducerSha": MEDIA_SHA,
        "mediaBundleDigest": manifest["manifestDigest"],
        "candidateCount": 4,
        "candidateHashes": [row["sha256"] for row in manifest["candidates"]],
        "growthProducerSha": growth["producerSha"],
        "reviewChain": review_chain,
        "reviewChainDigest": sha256_json(review_chain),
        "reeditRounds": sum(1 for row in review_chain if row["decision"] == "REEDIT"),
        "final": final,
        "releaseEscrowDigest": escrow["escrowDigest"],
        "publishTransactionId": publish["transactionId"],
        "publishIdempotencyKey": publish["idempotencyKey"],
        "actualLocalPcE2EExecuted": True,
        "realInputBytes": True,
        "realEncodedCandidates": True,
        "providerMutation": False,
        "networkEffects": 0,
        "liveSend": False,
        "livePublish": False,
        "liveAuthorization": False,
        "ledgerDigest": ledger.digest,
    }
    receipt["receiptDigest"] = sha256_json(receipt)
    _write_json(workspace / "evidence" / "real-input-output-receipt.r40.json", receipt)
    return receipt


def _fixture_review(
    *,
    growth: Mapping[str, Any],
    bundle_digest: str,
    round_number: int,
    selected_id: str,
    selected_sha: str,
    decision: str,
) -> dict[str, Any]:
    value = {
        "contractVersion": REVIEW_VERSION,
        "evidenceClass": "FIXTURE_REVIEW",
        "fixtureOnly": True,
        "growthProducerSha": growth["producerSha"],
        "growthArtifactDigest": growth["artifactDigest"],
        "mediaBundleDigest": bundle_digest,
        "reviewRound": round_number,
        "decision": decision,
        "selectedCandidateId": selected_id,
        "selectedSha256": selected_sha,
        "qualityScores": {"hook": 0.8, "pacing": 0.8, "clarity": 0.8, "cta": 0.7},
        "directives": [] if decision == "WINNER" else [{"operation": "trim", "reason": "fixture"}],
        "reeditRequest": None,
        "providerMutation": False,
        "livePublish": False,
        "reviewDigest": "",
    }
    if decision == "REEDIT":
        value["reeditRequest"] = {
            "contractVersion": "media.editorial_reedit_request.r19.v1",
            "requestId": f"fixture-round-{round_number + 1}",
        }
    value["reviewDigest"] = sha256_json({**value, "reviewDigest": ""})
    return value


def run_fixture(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    growth = fixture_growth_authority()
    validate_growth_authority(growth, allow_fixture=True)
    source = root / "fixture-source.mp4"
    if not source.exists():
        source.write_bytes(b"creator-r40-fixture-source")
    source_id = file_record(source)
    bundle_digest = hashlib.sha256(b"fixture-media-r27-bundle").hexdigest()
    candidates: dict[str, dict[str, Any]] = {}
    for index in range(1, 5):
        path = root / "fixture-media" / f"candidate-{index}.mp4"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"candidate-{index}-bytes".encode())
        rec = file_record(path)
        candidates[f"candidate-{index}"] = {"candidateId": f"candidate-{index}", **rec, "path": path}
    identity = {
        "contractVersion": CONTRACT_VERSION,
        "fixtureOnly": True,
        "source": source_id,
        "growthProducerSha": growth["producerSha"],
        "bundleDigest": bundle_digest,
    }
    ledger = StageLedger(root, identity=identity)
    ledger.append(
        key="FIXTURE_CANDIDATES:COMPLETED",
        event_type="FIXTURE_CANDIDATES_READY",
        request={"bundleDigest": bundle_digest},
        evidence={"hashes": [candidates[k]["sha256"] for k in sorted(candidates)]},
    )
    review0 = _fixture_review(
        growth=growth, bundle_digest=bundle_digest, round_number=0,
        selected_id="candidate-2", selected_sha=candidates["candidate-2"]["sha256"], decision="REEDIT",
    )
    validate_review(review0, growth_authority=growth, media_bundle_digest=bundle_digest, round_number=0, available=candidates, allow_fixture=True)
    reedit1_path = root / "fixture-media" / "reedit-1.mp4"
    if not reedit1_path.exists():
        reedit1_path.write_bytes(b"fixture-reedit-one")
    rec1 = file_record(reedit1_path)
    reedit1 = {"candidateId": "reedit-1", **rec1, "path": reedit1_path}
    review1 = _fixture_review(
        growth=growth, bundle_digest=bundle_digest, round_number=1,
        selected_id="reedit-1", selected_sha=reedit1["sha256"], decision="REEDIT",
    )
    validate_review(review1, growth_authority=growth, media_bundle_digest=bundle_digest, round_number=1, available={"reedit-1": reedit1}, allow_fixture=True)
    reedit2_path = root / "fixture-media" / "reedit-2.mp4"
    if not reedit2_path.exists():
        reedit2_path.write_bytes(b"fixture-reedit-two")
    rec2 = file_record(reedit2_path)
    reedit2 = {"candidateId": "reedit-2", **rec2, "path": reedit2_path}
    review2 = _fixture_review(
        growth=growth, bundle_digest=bundle_digest, round_number=2,
        selected_id="reedit-2", selected_sha=reedit2["sha256"], decision="WINNER",
    )
    validate_review(review2, growth_authority=growth, media_bundle_digest=bundle_digest, round_number=2, available={"reedit-2": reedit2}, allow_fixture=True)
    chain = [review0, review1, review2]
    final_path = root / "final" / "final.mp4"
    final_rec = _copy_stable(reedit2_path, final_path)
    final = {"sha256": final_rec["sha256"], "size": final_rec["size"], "path": "final/final.mp4"}
    escrow = release_escrow(
        workspace=root, source=source_id, final=final, media_bundle_digest=bundle_digest,
        review_chain=chain, authority_digest=sha256_json({"fixtureGrowth": growth}), ledger=ledger,
    )
    publish = publish_readiness(
        final=final, escrow=escrow, platform="instagram_reels", account_ref="fixture-account",
        destination="profile:fixture-account", caption="fixture", title="fixture",
        growth_authority=growth, allow_fixture=True,
    )
    _write_json(root / "evidence" / "publish-readiness.r40.json", publish)
    value = {
        "contractVersion": "creator.autonomous_reels_fixture.r40.v1",
        "state": "FIXTURE_LOOP_COMPLETE",
        "candidateCount": 4,
        "candidateHashes": [candidates[k]["sha256"] for k in sorted(candidates)],
        "reviewRounds": 3,
        "reeditRounds": 2,
        "final": final,
        "releaseEscrowDigest": escrow["escrowDigest"],
        "publishTransactionId": publish["transactionId"],
        "publishIdempotencyKey": publish["idempotencyKey"],
        "actualLocalPcE2EExecuted": False,
        "fixtureOnly": True,
        "sendPermitted": False,
        "providerMutation": False,
        "livePublish": False,
        "liveAuthorization": False,
        "ledgerDigest": ledger.digest,
    }
    value["fixtureDigest"] = sha256_json(value)
    _write_json(root / "evidence" / "fixture-autonomous-reels.r40.json", value)
    return value


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="creator-autonomous-reels-local-r40")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("diagnose")
    q.add_argument("--out")
    q = sub.add_parser("fixture")
    q.add_argument("--workspace", required=True)
    q.add_argument("--out")
    q = sub.add_parser("run")
    q.add_argument("--source", required=True)
    q.add_argument("--workspace", required=True)
    q.add_argument("--media-root", required=True)
    q.add_argument("--growth-authority", required=True)
    q.add_argument("--review-dir", required=True)
    q.add_argument("--platform", default="instagram_reels", choices=sorted(PLATFORMS))
    q.add_argument("--account-ref", required=True)
    q.add_argument("--destination", required=True)
    q.add_argument("--caption", default="")
    q.add_argument("--title", default="")
    q.add_argument("--human-review")
    q.add_argument("--boss-go")
    q.add_argument("--out")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "diagnose":
        value = diagnosis()
        code = 4
    elif args.command == "fixture":
        value = run_fixture(args.workspace)
        code = 0
    else:
        try:
            growth = validate_growth_authority(_load_json(args.growth_authority))
            human = _load_json(args.human_review) if args.human_review else None
            boss = _load_json(args.boss_go) if args.boss_go else None
            value = run_local(
                source=Path(args.source),
                workspace=Path(args.workspace),
                media_root=Path(args.media_root),
                growth_authority=growth,
                review_dir=Path(args.review_dir),
                platform=args.platform,
                account_ref=args.account_ref,
                destination=args.destination,
                caption=args.caption,
                title=args.title,
                human_review=human,
                boss_go=boss,
            )
            code = 0
        except AuthorityBlocked as exc:
            value = {
                "contractVersion": "creator.autonomous_reels_run_blocked.r40.v1",
                "state": "BLOCKED_AUTHORITY",
                "error": type(exc).__name__,
                "detail": str(exc),
                "providerMutation": False,
                "livePublish": False,
                "liveAuthorization": False,
            }
            code = 4
    if getattr(args, "out", None):
        _write_json(args.out, value)
    print(json.dumps(value, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
