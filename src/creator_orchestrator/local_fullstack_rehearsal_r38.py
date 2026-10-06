from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

CONTRACT_VERSION = "creator.local_fullstack_rehearsal.r38.v1"
AUTHORITY_VERSION = "creator.local_fullstack_authority.r38.v1"
LEDGER_VERSION = "creator.local_fullstack_stage_ledger.r38.v1"
STATUS_VERSION = "creator.local_fullstack_status.r38.v1"
MANIFEST_VERSION = "creator.local_fullstack_rehearsal_manifest.r38.v1"
REVIEW_VERSION = "creator.local_review_package.r38.v1"
MEDIA_REQUEST_VERSION = "creator.media_local_request.r38.v1"
MEDIA_RESPONSE_VERSION = "creator.media_local_response.r38.v1"
RESOURCE_VERSION = "creator.local_resource_declaration.r38.v1"

WAITING_MEDIA_AUTHORITY = "WAITING_MEDIA_AUTHORITY"
READY_FOR_LOCAL_REHEARSAL = "READY_FOR_LOCAL_REHEARSAL"
LOCAL_REHEARSAL_COMPLETE = "LOCAL_REHEARSAL_COMPLETE"

CREATOR_R37 = {
    "repository": "foto6/video1",
    "producerSha": "1f7cb9ed8f1985cd4faca79ce55f1c5fda9e3a57",
    "ciRunId": 37398299900,
    "ciConclusion": "success",
    "contract": "creator.local_integration_driver.r37.v1",
}
GROWTH_R36 = {
    "repository": "foto6/video3",
    "producerSha": "a53f9deb180bb256d193f0422c6ffd7a5923d97a",
    "ciRunId": 37398558145,
    "ciConclusion": "success",
    "artifactId": 11383953328,
    "artifactName": "growth-r36-local-rehearsal-evidence",
    "artifactDigest": "sha256:89e719718b5480ad889190a09c837efdfff31a15ea899f1e836ddb9d033f0894",
    "contract": "growth.local_rehearsal_evidence.r36.v1",
    "offlineOnly": True,
    "liveAuthorization": False,
}
BRIDGE_R40 = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "9fca5e7e4cdc820a1a3aee6ada9102fc97649d16",
    "ciRunId": 37399009019,
    "ciConclusion": "success",
    "contract": "bridge.operator_lifecycle.r40.v1",
    "artifacts": [
        {
            "id": 11384052747,
            "name": "r40-operator-lifecycle-ubuntu-latest",
            "digest": "sha256:324183d5f94f2794f5391c472484e81952293555f0189544d7deb13db6402c0e",
        },
        {
            "id": 11384304238,
            "name": "r40-operator-lifecycle-windows-latest",
            "digest": "sha256:6c18e7220aecb59b4b249fdb34b0c644a9ff0e950f82973e6d844c0867fb9709",
        },
    ],
    "liveCutoverAllowed": False,
}
MEDIA_R26_REQUIRED = {
    "repository": "foto6/video2",
    "milestone": "R26",
    "status": "UNACCEPTED",
    "acceptedTupleRequired": True,
    "oldR25Forbidden": True,
    "requiredFields": [
        "repository",
        "milestone",
        "status",
        "producerSha",
        "ciRunId",
        "ciConclusion",
        "artifactId",
        "artifactName",
        "artifactDigest",
        "contract",
        "localRunner",
        "independentQa",
    ],
}


class R38Error(ValueError):
    pass


class AuthorityError(R38Error):
    pass


class MediaAuthorityRequired(AuthorityError):
    pass


class ReplayConflict(R38Error):
    pass


class WorkspaceError(R38Error):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _git_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise AuthorityError(f"{field} must be exact lowercase git SHA")
    return value


def _sha256_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise AuthorityError(f"{field} must be sha256:<64-hex>")
    if any(c not in "0123456789abcdef" for c in value[7:]):
        raise AuthorityError(f"{field} must be sha256:<64-hex>")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AuthorityError(f"{field} must be positive integer")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityError(f"{field} must be non-empty string")
    return value


def fixture_media_authority() -> dict[str, Any]:
    return {
        "repository": "foto6/video2",
        "milestone": "R26",
        "status": "ACCEPTED",
        "producerSha": "1" * 40,
        "ciRunId": 49999999001,
        "ciConclusion": "success",
        "artifactId": 12999999001,
        "artifactName": "media-r26-ci-fixture-only",
        "artifactDigest": "sha256:" + "2" * 64,
        "contract": "media.local_windows_render.r26.v1",
        "fixtureOnly": True,
        "localRunner": {
            "protocol": MEDIA_REQUEST_VERSION,
            "responseContract": MEDIA_RESPONSE_VERSION,
            "relativePath": "tools/media-local-r26.cmd",
            "networkAllowed": False,
            "credentialsRequired": False,
            "cudaRequired": False,
        },
        "independentQa": {
            "repository": "foto6/boss",
            "producerSha": "3" * 40,
            "ciRunId": 49999999002,
            "ciConclusion": "success",
            "artifactId": 12999999002,
            "artifactDigest": "sha256:" + "4" * 64,
            "disposition": "ACCEPTED",
            "acceptedMediaProducerSha": "1" * 40,
            "acceptedMediaCiRunId": 49999999001,
            "acceptedMediaArtifactId": 12999999001,
            "acceptedMediaArtifactDigest": "sha256:" + "2" * 64,
            "acceptedMediaContract": "media.local_windows_render.r26.v1",
        },
    }


def validate_media_authority(media: Mapping[str, Any] | None, *, allow_fixture: bool = False) -> dict[str, Any]:
    if media is None:
        raise MediaAuthorityRequired("exact independently accepted Media R26 authority tuple is required")
    required = set(MEDIA_R26_REQUIRED["requiredFields"])
    allowed = required | {"fixtureOnly"}
    if not isinstance(media, Mapping) or set(media) - allowed or not required.issubset(media):
        raise MediaAuthorityRequired("Media R26 authority fields mismatch")
    if media["repository"] != "foto6/video2" or media["milestone"] != "R26":
        raise MediaAuthorityRequired("Media authority must be foto6/video2 milestone R26")
    if media["status"] != "ACCEPTED" or media["ciConclusion"] != "success":
        raise MediaAuthorityRequired("Media R26 is not exact-green accepted")
    contract = _nonempty(media["contract"], "media.contract")
    if ".r26." not in contract or ".r25." in contract:
        raise MediaAuthorityRequired("old Media R25 output is forbidden")
    if media.get("fixtureOnly") is True and not allow_fixture:
        raise MediaAuthorityRequired("fixture-only Media tuple cannot authorize local rehearsal")
    _git_sha(media["producerSha"], "media.producerSha")
    _positive(media["ciRunId"], "media.ciRunId")
    _positive(media["artifactId"], "media.artifactId")
    _sha256_digest(media["artifactDigest"], "media.artifactDigest")
    _nonempty(media["artifactName"], "media.artifactName")

    runner = media["localRunner"]
    fields = {"protocol", "responseContract", "relativePath", "networkAllowed", "credentialsRequired", "cudaRequired"}
    if not isinstance(runner, Mapping) or set(runner) != fields:
        raise MediaAuthorityRequired("Media localRunner fields mismatch")
    if runner["protocol"] != MEDIA_REQUEST_VERSION or runner["responseContract"] != MEDIA_RESPONSE_VERSION:
        raise MediaAuthorityRequired("Media local runner protocol mismatch")
    rel = Path(_nonempty(runner["relativePath"], "media.localRunner.relativePath"))
    if rel.is_absolute() or ".." in rel.parts:
        raise MediaAuthorityRequired("Media local runner path must be safe relative path")
    if runner["networkAllowed"] is not False or runner["credentialsRequired"] is not False:
        raise MediaAuthorityRequired("Media local runner must be offline and credential-free")
    if runner["cudaRequired"] is not False:
        raise MediaAuthorityRequired("Media R26 authority cannot require CUDA")

    qa = media["independentQa"]
    qfields = {
        "repository", "producerSha", "ciRunId", "ciConclusion", "artifactId", "artifactDigest", "disposition",
        "acceptedMediaProducerSha", "acceptedMediaCiRunId", "acceptedMediaArtifactId",
        "acceptedMediaArtifactDigest", "acceptedMediaContract",
    }
    if not isinstance(qa, Mapping) or set(qa) != qfields:
        raise MediaAuthorityRequired("Media independent QA tuple fields mismatch")
    if qa["repository"] != "foto6/boss" or qa["ciConclusion"] != "success" or qa["disposition"] != "ACCEPTED":
        raise MediaAuthorityRequired("Media independent QA acceptance missing")
    _git_sha(qa["producerSha"], "media.independentQa.producerSha")
    _positive(qa["ciRunId"], "media.independentQa.ciRunId")
    _positive(qa["artifactId"], "media.independentQa.artifactId")
    _sha256_digest(qa["artifactDigest"], "media.independentQa.artifactDigest")
    if (
        qa["acceptedMediaProducerSha"] != media["producerSha"]
        or qa["acceptedMediaCiRunId"] != media["ciRunId"]
        or qa["acceptedMediaArtifactId"] != media["artifactId"]
        or qa["acceptedMediaArtifactDigest"] != media["artifactDigest"]
        or qa["acceptedMediaContract"] != media["contract"]
    ):
        raise MediaAuthorityRequired("Media QA tuple does not bind exact Media producer authority")
    return _clone(media)


def authority_envelope(media: Mapping[str, Any] | None = None, *, allow_fixture_media: bool = False) -> dict[str, Any]:
    parsed = validate_media_authority(media, allow_fixture=allow_fixture_media) if media is not None else _clone(MEDIA_R26_REQUIRED)
    value = {
        "contractVersion": AUTHORITY_VERSION,
        "creatorR37": _clone(CREATOR_R37),
        "growthR36": _clone(GROWTH_R36),
        "bridgeR40": _clone(BRIDGE_R40),
        "mediaR26": parsed,
    }
    value["authorityDigest"] = sha256_json(value)
    return value


def resource_declaration(*, cpu_workers: int = 2, gpu_mode: str = "none", disk_budget_mb: int = 4096, temp_root: str = "temp") -> dict[str, Any]:
    if isinstance(cpu_workers, bool) or not isinstance(cpu_workers, int) or not 1 <= cpu_workers <= 64:
        raise R38Error("cpu_workers must be 1..64")
    if gpu_mode not in {"none", "auto"}:
        raise R38Error("gpu_mode must be none or auto")
    if isinstance(disk_budget_mb, bool) or not isinstance(disk_budget_mb, int) or disk_budget_mb < 128:
        raise R38Error("disk_budget_mb must be >=128")
    root = Path(temp_root)
    if root.is_absolute() or ".." in root.parts:
        raise R38Error("temp_root must be a safe workspace-relative path")
    return {
        "contractVersion": RESOURCE_VERSION,
        "cpuWorkers": cpu_workers,
        "gpuMode": gpu_mode,
        "cudaAssumed": False,
        "cudaRequired": False,
        "diskBudgetMb": disk_budget_mb,
        "tempRoot": root.as_posix(),
        "candidateCount": 3,
        "heavyHostedCiRenderAllowed": False,
    }


def workspace_layout() -> dict[str, str]:
    return {
        "authority": "authorities/authority-envelope.r38.json",
        "ledger": "ledger/stage-ledger.r38.jsonl",
        "sourceMetadata": "inputs/source-package.r38.json",
        "reviewPackage": "review/review-package.r38.json",
        "growthDecision": "growth/growth-decision.r38.json",
        "candidateDir": "candidates",
        "targetedReedit": "reedit/targeted-reedit.mp4",
        "finalVideo": "final/final.mp4",
        "manifest": "evidence/final-rehearsal-manifest.r38.json",
        "status": "evidence/status.r38.json",
        "temp": "temp",
    }


def readiness(media: Mapping[str, Any] | None = None) -> dict[str, Any]:
    state, accepted, error = WAITING_MEDIA_AUTHORITY, False, "exact independently accepted Media R26 authority tuple is required"
    if media is not None:
        try:
            validate_media_authority(media)
            state, accepted, error = READY_FOR_LOCAL_REHEARSAL, True, None
        except MediaAuthorityRequired as exc:
            error = str(exc)
    value = {
        "reportVersion": "creator.local_fullstack_readiness.r38.v1",
        "contract": CONTRACT_VERSION,
        "state": state,
        "mediaRequired": True,
        "mediaAccepted": accepted,
        "mediaRequirement": _clone(MEDIA_R26_REQUIRED),
        "creatorR37": _clone(CREATOR_R37),
        "growthR36": _clone(GROWTH_R36),
        "bridgeR40": _clone(BRIDGE_R40),
        "workspaceLayout": workspace_layout(),
        "defaultResources": resource_declaration(),
        "offlineFakeReviewSupported": True,
        "liveReviewRequiresExactLocalInput": True,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
        "credentialsRequired": False,
        "liveBridgeCutover": False,
        "actualLocalPcE2EExecuted": False,
        "blocker": error,
    }
    value["reportDigest"] = sha256_json(value)
    return value


class StageLedger:
    def __init__(self, workspace: str | os.PathLike[str], *, identity: Mapping[str, Any] | None = None) -> None:
        self.workspace = Path(workspace)
        self.path = self.workspace / workspace_layout()["ledger"]
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.identity: dict[str, Any] | None = None
        if self.path.exists():
            self._load()
            if identity is not None and self.identity != _clone(identity):
                raise ReplayConflict("changed inputs under same rehearsal workspace identity")
        elif identity is not None:
            self._append_raw("identity", "IDENTITY", {"identity": _clone(identity)}, artifacts=[])

    def _load(self) -> None:
        prev = ""
        for index, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReplayConflict(f"invalid ledger JSON line {index}") from exc
            required = {"ledgerVersion", "sequence", "eventKey", "eventType", "requestDigest", "previousEventDigest", "artifacts", "eventDigest"}
            if set(event) != required or event["ledgerVersion"] != LEDGER_VERSION:
                raise ReplayConflict("ledger event shape/version mismatch")
            if event["sequence"] != len(self.events) + 1 or event["previousEventDigest"] != prev:
                raise ReplayConflict("ledger sequence/hash chain mismatch")
            material = {k: v for k, v in event.items() if k != "eventDigest"}
            if event["eventDigest"] != sha256_json(material):
                raise ReplayConflict("ledger event digest mismatch")
            if event["eventKey"] in self.by_key:
                raise ReplayConflict("duplicate ledger event key")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event
            prev = event["eventDigest"]
        first = self.events[0] if self.events else None
        if first is None or first["eventKey"] != "identity":
            raise ReplayConflict("ledger identity event missing")
        meta_path = self.workspace / "ledger" / "identity.r38.json"
        if not meta_path.is_file():
            raise ReplayConflict("ledger identity metadata missing")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if sha256_json({"identity": meta}) != first["requestDigest"]:
            raise ReplayConflict("ledger identity metadata digest mismatch")
        self.identity = meta

    def _append_raw(self, event_key: str, event_type: str, request: Mapping[str, Any], *, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        request_digest = sha256_json(request)
        existing = self.by_key.get(event_key)
        if existing is not None:
            if existing["eventType"] != event_type or existing["requestDigest"] != request_digest or existing["artifacts"] != artifacts:
                raise ReplayConflict(f"conflicting replay for {event_key}")
            return _clone(existing)
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "requestDigest": request_digest,
            "previousEventDigest": self.events[-1]["eventDigest"] if self.events else "",
            "artifacts": _clone(artifacts),
        }
        event["eventDigest"] = sha256_json(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if event_key == "identity":
            meta = request["identity"]
            (self.path.parent / "identity.r38.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.identity = _clone(meta)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self.by_key[event_key] = event
        return _clone(event)

    def start(self, stage: str, request: Mapping[str, Any]) -> None:
        self._append_raw(f"{stage}:STARTED", "STAGE_STARTED", request, artifacts=[])

    def complete(self, stage: str, request: Mapping[str, Any], artifacts: list[dict[str, Any]]) -> None:
        if f"{stage}:STARTED" not in self.by_key:
            raise ReplayConflict(f"{stage} completion missing STARTED event")
        self._append_raw(f"{stage}:COMPLETED", "STAGE_COMPLETED", request, artifacts=artifacts)

    @property
    def digest(self) -> str:
        return sha256_json(self.events)


def _artifact_record(workspace: Path, path: Path) -> dict[str, Any]:
    root, resolved = workspace.resolve(), path.resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("generated artifact escaped workspace") from exc
    if not resolved.is_file():
        raise WorkspaceError(f"expected artifact missing: {rel.as_posix()}")
    return {"path": rel.as_posix(), "sha256": file_sha256(resolved), "size": resolved.stat().st_size}


def _verify_artifacts(workspace: Path, records: Sequence[Mapping[str, Any]]) -> bool:
    for row in records:
        path = workspace / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or file_sha256(path) != row["sha256"]:
            return False
    return True


def _run_step(ledger: StageLedger, *, stage: str, request: Mapping[str, Any], work: Callable[[], Sequence[Path]]) -> tuple[list[dict[str, Any]], bool]:
    completed = ledger.by_key.get(f"{stage}:COMPLETED")
    request_digest = sha256_json(request)
    if completed is not None:
        if completed["requestDigest"] != request_digest:
            raise ReplayConflict(f"{stage} request changed on replay")
        if not _verify_artifacts(ledger.workspace, completed["artifacts"]):
            raise ReplayConflict(f"{stage} completed artifact hash drift")
        return _clone(completed["artifacts"]), True
    started = ledger.by_key.get(f"{stage}:STARTED")
    if started is not None and started["requestDigest"] != request_digest:
        raise ReplayConflict(f"{stage} started request changed on replay")
    if started is None:
        ledger.start(stage, request)
    records = [_artifact_record(ledger.workspace, path) for path in work()]
    ledger.complete(stage, request, records)
    return records, False


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _safe_relative_artifact(workspace: Path, value: str, *, allowed_parent: Path) -> Path:
    raw = Path(value)
    path = raw if raw.is_absolute() else workspace / raw
    resolved, parent = path.resolve(), allowed_parent.resolve()
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise WorkspaceError("Media response artifact escaped allowed workspace directory") from exc
    return resolved


def _invoke_media_subprocess(*, media_root: Path, media_authority: Mapping[str, Any], request: Mapping[str, Any], response_path: Path) -> dict[str, Any]:
    runner_rel = Path(media_authority["localRunner"]["relativePath"])
    runner, root = (media_root / runner_rel).resolve(), media_root.resolve()
    try:
        runner.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("Media runner escaped media root") from exc
    if not runner.is_file():
        raise WorkspaceError(f"Media local runner missing: {runner_rel.as_posix()}")
    request_path = response_path.with_suffix(".request.json")
    _write_json(request_path, request)
    suffix = runner.suffix.lower()
    if suffix == ".py":
        argv = [sys.executable, str(runner)]
    elif suffix == ".ps1":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise WorkspaceError("PowerShell not available for Media runner")
        argv = [shell, "-NoProfile", "-File", str(runner)]
    else:
        argv = [str(runner)]
    argv += ["--request", str(request_path), "--response", str(response_path)]
    env = dict(os.environ)
    env["CREATOR_R38_NO_NETWORK"] = "1"
    env["CREATOR_R38_LIVE_AUTHORIZATION"] = "0"
    completed = subprocess.run(argv, cwd=str(media_root), env=env, check=False)
    if completed.returncode != 0:
        raise WorkspaceError(f"Media local runner failed with exit code {completed.returncode}")
    if not response_path.is_file():
        raise WorkspaceError("Media local runner did not write response")
    result = json.loads(response_path.read_text(encoding="utf-8"))
    if result.get("contractVersion") != MEDIA_RESPONSE_VERSION:
        raise WorkspaceError("Media local response contract mismatch")
    if result.get("networkEffects") != 0 or result.get("providerEffects") != 0 or result.get("liveAuthorization") is not False:
        raise WorkspaceError("Media local response crossed no-side-effect boundary")
    return result


def _fake_media_executor(*, workspace: Path, request: Mapping[str, Any], source_bytes: bytes) -> dict[str, Any]:
    if request["phase"] == "CANDIDATES":
        out = workspace / "candidates"
        out.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for ordinal in range(1, 4):
            path = out / f"candidate-{ordinal:02d}.mp4"
            path.write_bytes(b"R38-TINY-MP4-CANDIDATE\n" + str(ordinal).encode("ascii") + b"\n" + source_bytes)
            artifacts.append({"path": path.relative_to(workspace).as_posix()})
        return {"contractVersion": MEDIA_RESPONSE_VERSION, "phase": "CANDIDATES", "artifacts": artifacts, "providerEffects": 0, "networkEffects": 0, "liveAuthorization": False}
    if request["phase"] == "TARGETED_REEDIT":
        candidate = workspace / request["inputCandidatePath"]
        if not candidate.is_file():
            raise WorkspaceError("targeted re-edit source candidate missing")
        out = workspace / "reedit" / "targeted-reedit.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(candidate.read_bytes() + b"\nR38-TARGETED-REEDIT\n" + canonical_json(request["directive"]).encode("utf-8"))
        return {"contractVersion": MEDIA_RESPONSE_VERSION, "phase": "TARGETED_REEDIT", "artifact": {"path": out.relative_to(workspace).as_posix()}, "providerEffects": 0, "networkEffects": 0, "liveAuthorization": False}
    raise WorkspaceError("unknown fake Media phase")


def _validate_review_input(value: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required = {"contractVersion", "source", "reviews", "providerEffects", "networkEffects", "liveAuthorization"}
    if not isinstance(value, Mapping) or set(value) != required or value["contractVersion"] != REVIEW_VERSION:
        raise WorkspaceError("review input fields/contract mismatch")
    if value["providerEffects"] != 0 or value["networkEffects"] != 0 or value["liveAuthorization"] is not False:
        raise WorkspaceError("review input crosses local no-side-effect boundary")
    known = {row["sha256"] for row in candidates}
    if not isinstance(value["reviews"], list) or not value["reviews"]:
        raise WorkspaceError("review input requires at least one review")
    for row in value["reviews"]:
        if row.get("candidateSha256") not in known or row.get("verdict") not in {"winner", "reedit", "reject"}:
            raise WorkspaceError("review input candidate/verdict invalid")
    return _clone(value)


def _offline_review_package(source: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(candidates, key=lambda row: row["path"])
    return {
        "contractVersion": REVIEW_VERSION,
        "source": {"mode": "OFFLINE_FAKE_REVIEW", "exactLiveReviewSupplied": False},
        "sourcePackage": _clone(source),
        "reviews": [
            {"reviewId": "offline-fixture-1", "candidateSha256": ordered[1]["sha256"], "verdict": "reedit", "score": 0.91, "directive": {"operation": "trim", "startMs": 0, "endMs": 1200}},
            {"reviewId": "offline-fixture-2", "candidateSha256": ordered[1]["sha256"], "verdict": "winner", "score": 0.89, "directive": None},
        ],
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
    }


def _growth_decision(review: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    known = {row["sha256"]: row for row in candidates}
    scores = {sha: 0.0 for sha in known}
    directive, directive_sha = None, None
    for row in review["reviews"]:
        scores[row["candidateSha256"]] += float(row.get("score", 0.0))
        if row.get("directive") is not None and directive is None:
            directive, directive_sha = row["directive"], row["candidateSha256"]
    selected_sha = max(sorted(scores), key=lambda sha: scores[sha])
    if directive is None:
        directive, directive_sha = {"operation": "trim", "startMs": 0, "endMs": 1000}, selected_sha
    allowed = {"trim", "cut", "crop_scale_reframe", "speed_change", "fade_transition", "text_overlay", "subtitles_captions", "audio_duck_mix", "intro_outro_cta"}
    if directive.get("operation") not in allowed or directive_sha not in known:
        raise WorkspaceError("Growth decision directive invalid")
    selected = known[directive_sha]
    value = {
        "contractVersion": "growth.local_offline_decision.r36.v1",
        "growthAuthoritySha": GROWTH_R36["producerSha"],
        "growthAuthorityCiRunId": GROWTH_R36["ciRunId"],
        "decisionMode": "LOCAL_ADVISORY_ONLY",
        "candidateSha256": directive_sha,
        "candidatePath": selected["path"],
        "directive": _clone(directive),
        "reviewPackageDigest": sha256_json(review),
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
    }
    value["decisionDigest"] = sha256_json(value)
    return value


def run_rehearsal(
    *,
    source_path: str | os.PathLike[str],
    brief: str,
    workspace: str | os.PathLike[str],
    media_authority: Mapping[str, Any],
    resources: Mapping[str, Any] | None = None,
    review_input: Mapping[str, Any] | None = None,
    media_root: str | os.PathLike[str] | None = None,
    media_executor: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    allow_fixture_media: bool = False,
    rehearsal_id: str | None = None,
) -> dict[str, Any]:
    source = Path(source_path)
    if not source.is_file():
        raise WorkspaceError("source file does not exist")
    if not isinstance(brief, str) or not brief.strip():
        raise WorkspaceError("brief must be non-empty")
    media = validate_media_authority(media_authority, allow_fixture=allow_fixture_media)
    auth = authority_envelope(media, allow_fixture_media=allow_fixture_media)
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    source_hash, source_size = file_sha256(source), source.stat().st_size
    brief_digest = hashlib.sha256(brief.encode("utf-8")).hexdigest()
    resource = _clone(resources or resource_declaration())
    review_digest = sha256_json(review_input) if review_input is not None else "OFFLINE_FAKE_REVIEW"
    identity_material = {
        "contractVersion": CONTRACT_VERSION,
        "sourceSha256": source_hash,
        "sourceSize": source_size,
        "briefDigest": brief_digest,
        "authorityDigest": auth["authorityDigest"],
        "reviewInputDigest": review_digest,
        "resources": resource,
    }
    rid = rehearsal_id or ("r38:" + sha256_json(identity_material))
    identity = {"rehearsalId": rid, **identity_material}
    ledger = StageLedger(root, identity=identity)
    _write_json(root / workspace_layout()["authority"], auth)
    source_meta = {"contractVersion": "creator.local_source_package.r38.v1", "sourceName": source.name, "sha256": source_hash, "size": source_size, "briefDigest": brief_digest, "sourceCopied": False}
    _write_json(root / workspace_layout()["sourceMetadata"], source_meta)

    def call_media(request: Mapping[str, Any], response_name: str) -> dict[str, Any]:
        if media_executor is not None:
            result = _clone(media_executor(request))
        elif media_root is not None:
            response_path = root / resource["tempRoot"] / response_name
            response_path.parent.mkdir(parents=True, exist_ok=True)
            result = _invoke_media_subprocess(media_root=Path(media_root), media_authority=media, request=request, response_path=response_path)
        else:
            raise WorkspaceError("accepted Media authority present but no explicit local Media runner root supplied")
        if result.get("contractVersion") != MEDIA_RESPONSE_VERSION or result.get("networkEffects") != 0 or result.get("providerEffects") != 0 or result.get("liveAuthorization") is not False:
            raise WorkspaceError("Media response violated R38 local contract")
        return result

    candidate_request = {"contractVersion": MEDIA_REQUEST_VERSION, "phase": "CANDIDATES", "rehearsalId": rid, "source": source_meta, "candidateCount": 3, "resources": resource, "networkAllowed": False, "liveAuthorization": False}

    def candidate_work() -> Sequence[Path]:
        result = call_media(candidate_request, "media-candidates.response.json")
        rows = result.get("artifacts")
        if not isinstance(rows, list) or len(rows) != 3:
            raise WorkspaceError("Media candidates response must contain exactly three artifacts")
        paths = [_safe_relative_artifact(root, row["path"], allowed_parent=root / "candidates") for row in rows]
        if len({file_sha256(path) for path in paths}) != 3:
            raise WorkspaceError("Media candidate bytes must be distinct")
        return paths

    candidate_records, reused_candidates = _run_step(ledger, stage="MEDIA_CANDIDATES", request=candidate_request, work=candidate_work)

    review_request = {"rehearsalId": rid, "candidateDigests": [row["sha256"] for row in candidate_records], "reviewInputDigest": review_digest}

    def review_work() -> Sequence[Path]:
        if review_input is None:
            package = _offline_review_package(source_meta, candidate_records)
        else:
            package = _validate_review_input(review_input, candidate_records)
            package["source"] = {"mode": "EXACT_LOCAL_REVIEW_INPUT", "exactLiveReviewSupplied": True}
            package["sourcePackage"] = _clone(source_meta)
        return [_write_json(root / workspace_layout()["reviewPackage"], package)]

    review_artifacts, reused_review = _run_step(ledger, stage="REVIEW_PACKAGE", request=review_request, work=review_work)
    review_package = json.loads((root / workspace_layout()["reviewPackage"]).read_text(encoding="utf-8"))

    decision_request = {"rehearsalId": rid, "reviewPackageSha256": review_artifacts[0]["sha256"], "growthProducerSha": GROWTH_R36["producerSha"], "growthCiRunId": GROWTH_R36["ciRunId"]}

    def decision_work() -> Sequence[Path]:
        return [_write_json(root / workspace_layout()["growthDecision"], _growth_decision(review_package, candidate_records))]

    decision_artifacts, reused_decision = _run_step(ledger, stage="GROWTH_DECISION", request=decision_request, work=decision_work)
    decision = json.loads((root / workspace_layout()["growthDecision"]).read_text(encoding="utf-8"))

    reedit_request = {"contractVersion": MEDIA_REQUEST_VERSION, "phase": "TARGETED_REEDIT", "rehearsalId": rid, "inputCandidatePath": decision["candidatePath"], "inputCandidateSha256": decision["candidateSha256"], "directive": decision["directive"], "resources": resource, "networkAllowed": False, "liveAuthorization": False}

    def reedit_work() -> Sequence[Path]:
        result = call_media(reedit_request, "media-reedit.response.json")
        if not isinstance(result.get("artifact"), Mapping):
            raise WorkspaceError("Media re-edit response artifact missing")
        return [_safe_relative_artifact(root, result["artifact"]["path"], allowed_parent=root / "reedit")]

    reedit_artifacts, reused_reedit = _run_step(ledger, stage="TARGETED_REEDIT", request=reedit_request, work=reedit_work)

    final_request = {"rehearsalId": rid, "reeditSha256": reedit_artifacts[0]["sha256"], "reeditSize": reedit_artifacts[0]["size"]}

    def final_work() -> Sequence[Path]:
        final_path = root / workspace_layout()["finalVideo"]
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / reedit_artifacts[0]["path"], final_path)
        return [final_path]

    final_artifacts, reused_final = _run_step(ledger, stage="FINALIZE", request=final_request, work=final_work)
    final_record = final_artifacts[0]
    manifest = {
        "contractVersion": MANIFEST_VERSION,
        "rehearsalContract": CONTRACT_VERSION,
        "rehearsalId": rid,
        "state": LOCAL_REHEARSAL_COMPLETE,
        "source": source_meta,
        "authorities": auth,
        "resources": resource,
        "candidates": candidate_records,
        "reviewPackage": {"path": review_artifacts[0]["path"], "sha256": review_artifacts[0]["sha256"], "mode": review_package["source"]["mode"]},
        "growthDecision": {"path": decision_artifacts[0]["path"], "sha256": decision_artifacts[0]["sha256"], "decisionDigest": decision["decisionDigest"]},
        "targetedReedit": reedit_artifacts[0],
        "selectedWinner": {"kind": "TARGETED_REEDIT", "sha256": reedit_artifacts[0]["sha256"], "size": reedit_artifacts[0]["size"]},
        "finalMp4": final_record,
        "ledgerDigest": ledger.digest,
        "stageReuse": {"mediaCandidates": reused_candidates, "reviewPackage": reused_review, "growthDecision": reused_decision, "targetedReedit": reused_reedit, "finalize": reused_final},
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
        "publishAllowed": False,
        "credentialsUsed": False,
        "liveBridgeCutover": False,
    }
    manifest["manifestDigest"] = sha256_json(manifest)
    manifest_path = _write_json(root / workspace_layout()["manifest"], manifest)
    status_value = {"contractVersion": STATUS_VERSION, "state": LOCAL_REHEARSAL_COMPLETE, "rehearsalId": rid, "manifestPath": manifest_path.relative_to(root).as_posix(), "manifestDigest": manifest["manifestDigest"], "finalMp4": final_record, "ledgerDigest": ledger.digest, "providerEffects": 0, "networkEffects": 0, "liveAuthorization": False, "publishAllowed": False}
    status_value["statusDigest"] = sha256_json(status_value)
    _write_json(root / workspace_layout()["status"], status_value)
    return status_value


def run_tiny_fixture(workspace: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(workspace)
    source = root / "fixture-source.mp4"
    root.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source.write_bytes(b"R38-TINY-SOURCE-MP4\n")
    media = fixture_media_authority()

    def executor(request: Mapping[str, Any]) -> Mapping[str, Any]:
        return _fake_media_executor(workspace=root, request=request, source_bytes=source.read_bytes())

    return run_rehearsal(source_path=source, brief="R38 tiny hosted-CI fixture", workspace=root, media_authority=media, media_executor=executor, allow_fixture_media=True, resources=resource_declaration(cpu_workers=1, gpu_mode="none", disk_budget_mb=128))


def status(workspace: str | os.PathLike[str], media: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = Path(workspace)
    status_path = root / workspace_layout()["status"]
    if status_path.is_file():
        value = json.loads(status_path.read_text(encoding="utf-8"))
        manifest_path = root / value["manifestPath"]
        if not manifest_path.is_file():
            raise ReplayConflict("status references missing final manifest")
        body = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = body.pop("manifestDigest")
        if digest != sha256_json(body):
            raise ReplayConflict("final manifest digest drift")
        return value
    return readiness(media)


def dry_run(*, source_path: str | os.PathLike[str] | None, workspace: str | os.PathLike[str], media: Mapping[str, Any] | None, resources: Mapping[str, Any]) -> dict[str, Any]:
    gate = readiness(media)
    source = None
    if source_path is not None:
        p = Path(source_path)
        source = {"exists": p.is_file(), "name": p.name, "sha256": file_sha256(p) if p.is_file() else None, "size": p.stat().st_size if p.is_file() else None}
    value = {
        "contractVersion": "creator.local_fullstack_dry_run.r38.v1",
        "state": gate["state"],
        "source": source,
        "workspace": Path(workspace).as_posix(),
        "layout": workspace_layout(),
        "resources": _clone(resources),
        "steps": ["VERIFY_EXACT_AUTHORITIES", "PACKAGE_SOURCE_REFERENCE", "MEDIA_CANDIDATES", "REVIEW_PACKAGE_OFFLINE_OR_EXACT_INPUT", "GROWTH_R36_LOCAL_DECISION", "MEDIA_TARGETED_REEDIT", "FINAL_MP4", "SEAL_FINAL_EVIDENCE_MANIFEST"],
        "networkRequired": False,
        "credentialsRequired": False,
        "cudaAssumed": False,
        "liveBridgeCutover": False,
        "publishAllowed": False,
    }
    value["dryRunDigest"] = sha256_json(value)
    return value


def cleanup(workspace: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(workspace)
    removed: list[str] = []
    for rel in {workspace_layout()["temp"], ".staging"}:
        target = (root / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceError("cleanup target escaped workspace") from exc
        if target.exists():
            shutil.rmtree(target)
            removed.append(rel)
    return {
        "contractVersion": "creator.local_fullstack_cleanup.r38.v1",
        "removed": sorted(removed),
        "preserved": ["authorities", "inputs", "ledger", "candidates", "review", "growth", "reedit", "final", "evidence"],
        "sourceMaterialDeleted": False,
        "acceptedEvidenceDeleted": False,
    }


def _load_json(path: str | os.PathLike[str] | None) -> Any:
    return None if path is None else json.loads(Path(path).read_text(encoding="utf-8"))


def _resources_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return resource_declaration(cpu_workers=args.cpu_workers, gpu_mode=args.gpu_mode, disk_budget_mb=args.disk_budget_mb, temp_root=args.temp_root)


def _add_resource_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cpu-workers", type=int, default=2)
    parser.add_argument("--gpu-mode", choices=["none", "auto"], default="none")
    parser.add_argument("--disk-budget-mb", type=int, default=4096)
    parser.add_argument("--temp-root", default="temp")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-local-fullstack-r38")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("readiness"); p.add_argument("--media-authority"); p.add_argument("--out")
    p = sub.add_parser("status"); p.add_argument("--workspace", required=True); p.add_argument("--media-authority"); p.add_argument("--out")
    p = sub.add_parser("dry-run"); p.add_argument("--source"); p.add_argument("--workspace", required=True); p.add_argument("--media-authority"); p.add_argument("--out"); _add_resource_args(p)
    p = sub.add_parser("run"); p.add_argument("--source", required=True); p.add_argument("--brief", required=True); p.add_argument("--workspace", required=True); p.add_argument("--media-authority", required=True); p.add_argument("--media-root", required=True); p.add_argument("--review-input"); p.add_argument("--rehearsal-id"); p.add_argument("--out"); _add_resource_args(p)
    p = sub.add_parser("cleanup"); p.add_argument("--workspace", required=True); p.add_argument("--out")
    p = sub.add_parser("fixture-rehearsal"); p.add_argument("--workspace", required=True); p.add_argument("--out")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    exit_code = 0
    if args.command == "readiness":
        media = _load_json(args.media_authority)
        value = readiness(media)
        if value["state"] == WAITING_MEDIA_AUTHORITY:
            exit_code = 3
    elif args.command == "status":
        value = status(args.workspace, _load_json(args.media_authority))
    elif args.command == "dry-run":
        value = dry_run(source_path=args.source, workspace=args.workspace, media=_load_json(args.media_authority), resources=_resources_from_args(args))
    elif args.command == "cleanup":
        value = cleanup(args.workspace)
    elif args.command == "fixture-rehearsal":
        value = run_tiny_fixture(args.workspace)
    else:
        media, review = _load_json(args.media_authority), _load_json(args.review_input)
        try:
            value = run_rehearsal(source_path=args.source, brief=args.brief, workspace=args.workspace, media_authority=media, resources=_resources_from_args(args), review_input=review, media_root=args.media_root, rehearsal_id=args.rehearsal_id)
        except MediaAuthorityRequired as exc:
            value = readiness(media)
            value["error"] = str(exc)
            exit_code = 3
    if getattr(args, "out", None):
        _write_json(Path(args.out), value)
    print(json.dumps(value, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
