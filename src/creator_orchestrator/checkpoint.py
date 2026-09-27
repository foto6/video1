from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lineage import LineageValidationError, validate_artifact_dag
from .models import Artifact, STAGE_ORDER
from .orchestrator import JsonJobStore
from .simulator import CampaignConfig, CampaignRunner

CAMPAIGN_CHECKPOINT_VERSION = "creator.campaign_checkpoint.v1"
REPRODUCIBILITY_REPORT_VERSION = "creator.reproducibility_report.v1"
_FIXED_RESTORE_TIME = "1970-01-01T00:00:00+00:00"

_TOP_LEVEL_FIELDS = {
    "checkpointVersion",
    "campaignIdentity",
    "cycleIndex",
    "campaignConfig",
    "campaignState",
    "jobs",
    "stageRecords",
    "growthSeedRecords",
    "growthSeedIdentities",
    "externalOperations",
    "acceptedMediaJobs",
    "artifactLineage",
    "analyticsHandoffs",
    "provenance",
    "integrity",
    "checkpointHash",
}
_SECRET_KEY_MARKERS = {
    "password",
    "passwd",
    "secret",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "cookie",
    "credential",
    "bearer",
}
_SECRET_EXACT_KEYS = {
    "authorization",
    "authorizationheader",
    "proxyauthorization",
}


class CampaignCheckpointError(ValueError):
    pass


class CampaignCheckpointVersionError(CampaignCheckpointError):
    pass


class CampaignCheckpointIntegrityError(CampaignCheckpointError):
    pass


class CampaignCheckpointConflictError(CampaignCheckpointError):
    pass


class CampaignCheckpointSecretError(CampaignCheckpointError):
    pass


@dataclass(frozen=True)
class CheckpointImportResult:
    status: str
    campaign_id: str
    checkpoint_hash: str


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignCheckpointError(
            "checkpoint content must be canonical JSON-compatible data"
        ) from exc


def canonical_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_canonical(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def compute_checkpoint_hash(bundle: Mapping[str, Any]) -> str:
    body = {key: value for key, value in bundle.items() if key != "checkpointHash"}
    return sha256_canonical(body)


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _assert_secret_free(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CampaignCheckpointSecretError(
                    f"non-string object key at {path}"
                )
            normalized = _normalized_key(key)
            if (
                normalized in _SECRET_EXACT_KEYS
                or any(marker in normalized for marker in _SECRET_KEY_MARKERS)
            ):
                raise CampaignCheckpointSecretError(
                    f"secret-like field {key!r} cannot be checkpointed at {path}"
                )
            _assert_secret_free(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_secret_free(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        lowered = value.lower()
        forbidden_fragments = (
            "authorization: bearer ",
            "?access_token=",
            "&access_token=",
            "?api_key=",
            "&api_key=",
            "?apikey=",
            "&apikey=",
        )
        if any(fragment in lowered for fragment in forbidden_fragments):
            raise CampaignCheckpointSecretError(
                f"secret-like string cannot be checkpointed at {path}"
            )


def _campaign_config_digest(config: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignCheckpointError(f"cannot read durable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CampaignCheckpointError(f"durable JSON must be an object: {path}")
    return value


def _artifact_from_dict(payload: Mapping[str, Any]) -> Artifact:
    return Artifact(
        **{
            **payload,
            "parents": tuple(payload.get("parents", ())),
        }
    )


def _normalize_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "id",
        "kind",
        "uri",
        "producer",
        "parents",
        "metadata",
        "created_at",
    }
    if set(payload) != expected:
        raise CampaignCheckpointError(
            "artifact fields must match the current immutable Artifact schema"
        )
    artifact = _artifact_from_dict(payload)
    if not isinstance(artifact.id, str) or not artifact.id:
        raise CampaignCheckpointError("artifact id must be non-empty")
    if not isinstance(artifact.kind, str) or not artifact.kind:
        raise CampaignCheckpointError("artifact kind must be non-empty")
    if not isinstance(artifact.producer, str) or not artifact.producer:
        raise CampaignCheckpointError("artifact producer must be non-empty")
    if len(set(artifact.parents)) != len(artifact.parents):
        raise CampaignCheckpointError(
            f"artifact {artifact.id} contains duplicate parents"
        )
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "uri": artifact.uri,
        "producer": artifact.producer,
        "parents": list(artifact.parents),
        "metadata": _clone(artifact.metadata),
        "created_at": artifact.created_at,
    }


def _normalize_job(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "id",
        "topic",
        "state",
        "stage_index",
        "attempts",
        "idempotency_attempts",
        "completed_idempotency_keys",
        "artifacts",
        "evaluations",
        "last_error",
        "created_at",
        "updated_at",
    }
    if set(raw) != required:
        raise CampaignCheckpointError(
            f"job fields do not match current durable schema: {raw.get('id')!r}"
        )
    job_id = raw["id"]
    if not isinstance(job_id, str) or not job_id:
        raise CampaignCheckpointError("job id must be non-empty")
    stage_index = raw["stage_index"]
    if (
        isinstance(stage_index, bool)
        or not isinstance(stage_index, int)
        or not 0 <= stage_index <= len(STAGE_ORDER)
    ):
        raise CampaignCheckpointError(f"invalid stage_index for {job_id}")
    artifacts = []
    for ordinal, item in enumerate(raw["artifacts"]):
        if not isinstance(item, Mapping):
            raise CampaignCheckpointError(f"artifact {ordinal} for {job_id} is invalid")
        artifacts.append(
            {
                "ordinal": ordinal,
                "artifact": _normalize_artifact(item),
            }
        )
    evaluations = _clone(raw["evaluations"])
    if not isinstance(evaluations, list):
        raise CampaignCheckpointError(f"evaluations for {job_id} must be an array")
    return {
        "jobId": job_id,
        "topic": raw["topic"],
        "state": raw["state"],
        "stageIndex": stage_index,
        "attempts": _clone(raw["attempts"]),
        "idempotencyAttempts": _clone(raw["idempotency_attempts"]),
        "completedIdempotencyKeys": _clone(raw["completed_idempotency_keys"]),
        "artifacts": artifacts,
        "evaluations": evaluations,
        "lastError": raw["last_error"],
    }


def _job_stage_records(job: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    stage_index = int(job["stageIndex"])
    attempts = job["attempts"]
    completed = job["completedIdempotencyKeys"]
    for index, stage in enumerate(STAGE_ORDER):
        if index < stage_index:
            status = "completed"
        elif index == stage_index and stage_index < len(STAGE_ORDER):
            status = "current"
        else:
            status = "pending"
        records.append(
            {
                "jobId": job["jobId"],
                "stage": stage.value,
                "stageIndex": index,
                "status": status,
                "attempts": int(attempts.get(stage.value, 0)),
                "completedIdempotencyKey": completed.get(stage.value),
            }
        )
    return records


def _normalize_operation(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "job_id",
        "stage",
        "idempotency_key",
        "adapter_name",
        "state",
        "request",
        "request_fingerprint",
        "external_operation_id",
        "acceptance_metadata",
        "poll_attempts",
        "poll_metadata",
        "result",
        "prepared_at",
        "accepted_at",
        "result_obtained_at",
        "committed_at",
        "updated_at",
    }
    if set(raw) != required:
        raise CampaignCheckpointError("operation receipt fields do not match v1")
    state = raw["state"]
    if state not in {"prepared", "accepted", "result_obtained", "committed"}:
        raise CampaignCheckpointError(f"invalid operation receipt state: {state!r}")
    external = raw["external_operation_id"]
    if state != "prepared" and (not isinstance(external, str) or not external):
        raise CampaignCheckpointError(
            "accepted/result/committed operation requires stable external handle"
        )
    request = _clone(raw["request"])
    expected_fingerprint = hashlib.sha256(
        canonical_json(request).encode("utf-8")
    ).hexdigest()
    if raw["request_fingerprint"] != expected_fingerprint:
        raise CampaignCheckpointIntegrityError(
            "operation request fingerprint mismatch"
        )
    poll_attempts = raw["poll_attempts"]
    if isinstance(poll_attempts, bool) or not isinstance(poll_attempts, int) or poll_attempts < 0:
        raise CampaignCheckpointError("operation poll_attempts must be non-negative")
    return {
        "jobId": raw["job_id"],
        "stage": raw["stage"],
        "idempotencyKey": raw["idempotency_key"],
        "adapterName": raw["adapter_name"],
        "state": state,
        "request": request,
        "requestFingerprint": raw["request_fingerprint"],
        "externalOperationId": external,
        "acceptanceMetadata": _clone(raw["acceptance_metadata"]),
        "pollAttempts": poll_attempts,
        "pollMetadata": _clone(raw["poll_metadata"]),
        "result": _clone(raw["result"]),
    }


def _normalize_growth_seed_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "ledger_version",
        "sequence",
        "idempotency_key",
        "seed_digest",
        "artifact",
        "status",
    }
    if set(raw) != required:
        raise CampaignCheckpointError("Growth seed ledger row fields are invalid")
    if raw["status"] != "committed":
        raise CampaignCheckpointError("only committed Growth seeds are checkpointable")
    return {
        "ledgerVersion": raw["ledger_version"],
        "sequence": raw["sequence"],
        "idempotencyKey": raw["idempotency_key"],
        "seedDigest": raw["seed_digest"],
        "artifact": _normalize_artifact(raw["artifact"]),
        "status": raw["status"],
    }


def _growth_seed_identities(
    rows: Sequence[Mapping[str, Any]],
    jobs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        artifact = row["artifact"]
        metadata = artifact["metadata"]
        batch_id = metadata.get("batch_id") if isinstance(metadata, Mapping) else None
        key = row["idempotencyKey"]
        if isinstance(batch_id, str) and batch_id != key:
            raise CampaignCheckpointIntegrityError(
                "Growth seed ledger key does not match artifact batch identity"
            )
        by_key[key] = {
            "idempotencyKey": key,
            "seedDigest": row["seedDigest"],
            "artifactId": artifact["id"],
            "batchId": batch_id,
            "source": "growth-seed-ledger",
        }

    for job in jobs:
        for record in job["artifacts"]:
            artifact = record["artifact"]
            if artifact["kind"] != "growth_feedback_batch":
                continue
            metadata = artifact["metadata"]
            if not isinstance(metadata, Mapping):
                raise CampaignCheckpointIntegrityError(
                    "growth_feedback_batch metadata must be an object"
                )
            key = metadata.get("idempotency_key")
            batch_id = metadata.get("batch_id")
            if not isinstance(key, str) or not key or batch_id != key:
                raise CampaignCheckpointIntegrityError(
                    "embedded Growth seed identity is invalid"
                )
            existing = by_key.get(key)
            if existing is not None and existing["artifactId"] != artifact["id"]:
                raise CampaignCheckpointIntegrityError(
                    "conflicting Growth seed identity between ledger and job"
                )
            if existing is None:
                by_key[key] = {
                    "idempotencyKey": key,
                    "seedDigest": sha256_canonical(metadata),
                    "artifactId": artifact["id"],
                    "batchId": batch_id,
                    "source": "job-artifact",
                }
    return [by_key[key] for key in sorted(by_key)]


def _accepted_media_jobs(
    operations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for operation in operations:
        if operation["adapterName"] != "media-job-v1":
            continue
        if operation["state"] == "prepared":
            continue
        handle = operation["externalOperationId"]
        request = operation["request"]
        if not isinstance(request, Mapping):
            raise CampaignCheckpointIntegrityError("Media operation request must be object")
        submit_request = request.get("request")
        if (
            request.get("contractVersion") != "media.job.v1"
            or request.get("action") != "submit"
            or not isinstance(submit_request, Mapping)
        ):
            raise CampaignCheckpointIntegrityError(
                "media-job-v1 receipt does not contain exact submit request"
            )
        media_job_id = submit_request.get("jobId")
        media_key = request.get("idempotencyKey")
        if handle != media_job_id:
            raise CampaignCheckpointIntegrityError(
                "accepted Media handle differs from submitted jobId"
            )
        records.append(
            {
                "creatorJobId": operation["jobId"],
                "stage": operation["stage"],
                "creatorIdempotencyKey": operation["idempotencyKey"],
                "mediaJobId": handle,
                "mediaIdempotencyKey": media_key,
                "receiptState": operation["state"],
                "requestFingerprint": operation["requestFingerprint"],
            }
        )
    return sorted(
        records,
        key=lambda item: (
            item["creatorJobId"],
            item["stage"],
            item["mediaJobId"],
        ),
    )


def _artifact_records(
    jobs: Sequence[Mapping[str, Any]],
    campaign_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for job in jobs:
        for record in job["artifacts"]:
            artifacts.append(record["artifact"])
    report = campaign_state.get("report_artifact")
    if report is not None:
        if not isinstance(report, Mapping):
            raise CampaignCheckpointError("campaign report_artifact is invalid")
        artifacts.append(_normalize_artifact(report))
    return artifacts


def _lineage_records(artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    instances: list[Artifact] = []
    for artifact in artifacts:
        artifact_id = artifact["id"]
        if artifact_id in by_id:
            raise CampaignCheckpointIntegrityError(
                f"duplicate campaign artifact id: {artifact_id}"
            )
        by_id[artifact_id] = artifact
        instances.append(_artifact_from_dict(artifact))
    try:
        validate_artifact_dag(instances)
    except LineageValidationError as exc:
        raise CampaignCheckpointIntegrityError(str(exc)) from exc
    return [
        {
            "artifactId": artifact_id,
            "kind": by_id[artifact_id]["kind"],
            "producer": by_id[artifact_id]["producer"],
            "parents": list(by_id[artifact_id]["parents"]),
            "artifactHash": sha256_canonical(by_id[artifact_id]),
        }
        for artifact_id in sorted(by_id)
    ]


def _analytics_handoffs(
    artifacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact["kind"] != "analytics_feedback":
            continue
        metadata = artifact["metadata"]
        event_ids: list[str] = []
        if isinstance(metadata, Mapping):
            events = metadata.get("events")
            if isinstance(events, list):
                for event in events:
                    if isinstance(event, Mapping) and isinstance(event.get("event_id"), str):
                        event_ids.append(event["event_id"])
        records.append(
            {
                "artifactId": artifact["id"],
                "eventIds": sorted(set(event_ids)),
                "artifactHash": sha256_canonical(artifact),
            }
        )
    return sorted(records, key=lambda item: item["artifactId"])


def _load_growth_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CampaignCheckpointError(
                    f"invalid Growth seed ledger JSON at line {line_number}"
                ) from exc
            if not isinstance(raw, Mapping):
                raise CampaignCheckpointError("Growth seed ledger row must be object")
            rows.append(_normalize_growth_seed_row(raw))
    rows.sort(key=lambda item: item["sequence"])
    for expected, row in enumerate(rows, 1):
        if row["sequence"] != expected:
            raise CampaignCheckpointIntegrityError(
                "Growth seed ledger sequence must be contiguous"
            )
    return rows


def _load_operations(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    records = [
        _normalize_operation(_read_json(path))
        for path in sorted(directory.glob("*.json"))
    ]
    records.sort(
        key=lambda item: (
            item["jobId"],
            item["stage"],
            item["idempotencyKey"],
        )
    )
    return records


def validate_producer_pins(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(repo_root)
    manifest_path = root / "fixtures" / "upstream" / "manifest.json"
    manifest = _read_json(manifest_path)
    if set(manifest) != {"manifestVersion", "fixtures"}:
        raise CampaignCheckpointIntegrityError("producer fixture manifest fields changed")
    fixtures = manifest["fixtures"]
    if not isinstance(fixtures, list):
        raise CampaignCheckpointIntegrityError("producer fixtures must be an array")
    normalized: list[dict[str, Any]] = []
    for item in fixtures:
        if not isinstance(item, Mapping):
            raise CampaignCheckpointIntegrityError("producer fixture pin must be object")
        expected = {
            "consumerPath",
            "sourceRepo",
            "sourceHead",
            "sourcePath",
            "gitBlobSha1",
            "sha256",
        }
        if set(item) != expected:
            raise CampaignCheckpointIntegrityError("producer fixture pin fields changed")
        consumer = item["consumerPath"]
        if not isinstance(consumer, str) or not consumer:
            raise CampaignCheckpointIntegrityError("consumerPath is invalid")
        data = (root / consumer).read_bytes()
        actual_sha256 = hashlib.sha256(data).hexdigest()
        actual_blob = git_blob_sha1(data)
        if actual_sha256 != item["sha256"] or actual_blob != item["gitBlobSha1"]:
            raise CampaignCheckpointIntegrityError(
                f"producer fixture provenance mismatch: {consumer}"
            )
        normalized.append(_clone(item))
    normalized.sort(key=lambda item: item["consumerPath"])
    if normalized != fixtures:
        raise CampaignCheckpointIntegrityError(
            "producer fixture pins must be in canonical consumerPath order"
        )
    return {
        "manifestVersion": manifest["manifestVersion"],
        "manifestHash": sha256_canonical(manifest),
        "fixtures": normalized,
    }


def _campaign_state_for_checkpoint(raw: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "campaign_id",
        "config_digest",
        "status",
        "current_cycle",
        "cycle_job_ids",
        "completed_cycles",
        "feedback_by_cycle",
        "handled_critic_ids",
        "event_digest_by_id",
        "duplicate_events_suppressed",
        "last_error",
        "report_artifact",
    }
    if set(raw) != expected:
        raise CampaignCheckpointError("campaign state fields do not match current schema")
    state = _clone(raw)
    if state["report_artifact"] is not None:
        state["report_artifact"] = _normalize_artifact(state["report_artifact"])
    return state


def export_campaign_checkpoint(
    state_root: str | os.PathLike[str],
    *,
    campaign_id: str,
    campaign_config: Mapping[str, Any],
    repo_root: str | os.PathLike[str],
    growth_seed_ledger_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    root = Path(state_root)
    config = _clone(campaign_config)
    config_digest = _campaign_config_digest(config)
    state_path = root / "campaigns" / f"{campaign_id}.json"
    campaign_state = _campaign_state_for_checkpoint(_read_json(state_path))
    if campaign_state["campaign_id"] != campaign_id:
        raise CampaignCheckpointConflictError("campaign state identity mismatch")
    if campaign_state["config_digest"] != config_digest:
        raise CampaignCheckpointConflictError(
            "campaign config digest does not match durable state"
        )

    cycle_job_ids = campaign_state["cycle_job_ids"]
    if not isinstance(cycle_job_ids, Mapping):
        raise CampaignCheckpointError("cycle_job_ids must be an object")
    job_ids = sorted(set(cycle_job_ids.values()))
    jobs = [
        _normalize_job(_read_json(root / "jobs" / f"{job_id}.json"))
        for job_id in job_ids
    ]
    if [job["jobId"] for job in jobs] != job_ids:
        raise CampaignCheckpointIntegrityError("job identity mismatch")

    stage_records = [
        record
        for job in jobs
        for record in _job_stage_records(job)
    ]
    growth_path = (
        Path(growth_seed_ledger_path)
        if growth_seed_ledger_path is not None
        else root / "growth-seeds.jsonl"
    )
    growth_rows = _load_growth_rows(growth_path)
    operations = _load_operations(root / "jobs" / "_operations")
    artifacts = _artifact_records(jobs, campaign_state)
    lineage = _lineage_records(artifacts)
    analytics = _analytics_handoffs(artifacts)
    growth_identities = _growth_seed_identities(growth_rows, jobs)
    accepted_media = _accepted_media_jobs(operations)
    provenance = validate_producer_pins(repo_root)

    job_hashes = [
        {
            "jobId": job["jobId"],
            "stateHash": sha256_canonical(job),
        }
        for job in jobs
    ]
    integrity = {
        "campaignConfigHash": "sha256:" + config_digest,
        "jobStateHashes": job_hashes,
        "stageRecordsHash": sha256_canonical(stage_records),
        "growthSeedRecordsHash": sha256_canonical(growth_rows),
        "externalOperationsHash": sha256_canonical(operations),
        "artifactLineageHash": sha256_canonical(lineage),
        "analyticsHandoffsHash": sha256_canonical(analytics),
        "producerPinsHash": sha256_canonical(provenance),
    }

    bundle: dict[str, Any] = {
        "checkpointVersion": CAMPAIGN_CHECKPOINT_VERSION,
        "campaignIdentity": {
            "campaignId": campaign_id,
            "configDigest": config_digest,
        },
        "cycleIndex": campaign_state["current_cycle"],
        "campaignConfig": config,
        "campaignState": campaign_state,
        "jobs": jobs,
        "stageRecords": stage_records,
        "growthSeedRecords": growth_rows,
        "growthSeedIdentities": growth_identities,
        "externalOperations": operations,
        "acceptedMediaJobs": accepted_media,
        "artifactLineage": lineage,
        "analyticsHandoffs": analytics,
        "provenance": provenance,
        "integrity": integrity,
    }
    _assert_secret_free(bundle)
    bundle["checkpointHash"] = compute_checkpoint_hash(bundle)
    validate_campaign_checkpoint(bundle, repo_root=repo_root)
    return bundle


def _require_canonical_order(bundle: Mapping[str, Any]) -> None:
    jobs = bundle["jobs"]
    if [item["jobId"] for item in jobs] != sorted(item["jobId"] for item in jobs):
        raise CampaignCheckpointIntegrityError("jobs are not in canonical order")
    for job in jobs:
        ordinals = [record["ordinal"] for record in job["artifacts"]]
        if ordinals != list(range(len(ordinals))):
            raise CampaignCheckpointIntegrityError(
                f"artifact records reordered for job {job['jobId']}"
            )
    stage_order = {stage.value: index for index, stage in enumerate(STAGE_ORDER)}
    expected_stage = sorted(
        bundle["stageRecords"],
        key=lambda item: (item["jobId"], stage_order[item["stage"]]),
    )
    if bundle["stageRecords"] != expected_stage:
        raise CampaignCheckpointIntegrityError("stage records are not canonical")
    expected_growth = sorted(
        bundle["growthSeedRecords"], key=lambda item: item["sequence"]
    )
    if bundle["growthSeedRecords"] != expected_growth:
        raise CampaignCheckpointIntegrityError("Growth seed records reordered")
    expected_growth_ids = sorted(
        bundle["growthSeedIdentities"], key=lambda item: item["idempotencyKey"]
    )
    if bundle["growthSeedIdentities"] != expected_growth_ids:
        raise CampaignCheckpointIntegrityError("Growth seed identities reordered")
    expected_ops = sorted(
        bundle["externalOperations"],
        key=lambda item: (
            item["jobId"],
            item["stage"],
            item["idempotencyKey"],
        ),
    )
    if bundle["externalOperations"] != expected_ops:
        raise CampaignCheckpointIntegrityError("operation receipts reordered")
    expected_media = sorted(
        bundle["acceptedMediaJobs"],
        key=lambda item: (
            item["creatorJobId"],
            item["stage"],
            item["mediaJobId"],
        ),
    )
    if bundle["acceptedMediaJobs"] != expected_media:
        raise CampaignCheckpointIntegrityError("accepted Media jobs reordered")
    expected_lineage = sorted(
        bundle["artifactLineage"], key=lambda item: item["artifactId"]
    )
    if bundle["artifactLineage"] != expected_lineage:
        raise CampaignCheckpointIntegrityError("artifact lineage records reordered")
    expected_analytics = sorted(
        bundle["analyticsHandoffs"], key=lambda item: item["artifactId"]
    )
    if bundle["analyticsHandoffs"] != expected_analytics:
        raise CampaignCheckpointIntegrityError("analytics handoffs reordered")
    fixtures = bundle["provenance"]["fixtures"]
    expected_fixtures = sorted(fixtures, key=lambda item: item["consumerPath"])
    if fixtures != expected_fixtures:
        raise CampaignCheckpointIntegrityError("producer fixture pins reordered")


def validate_campaign_checkpoint(
    bundle: Mapping[str, Any],
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> None:
    if not isinstance(bundle, Mapping):
        raise CampaignCheckpointError("checkpoint bundle must be an object")
    if set(bundle) != _TOP_LEVEL_FIELDS:
        raise CampaignCheckpointError("checkpoint top-level fields do not match v1")
    if bundle["checkpointVersion"] != CAMPAIGN_CHECKPOINT_VERSION:
        raise CampaignCheckpointVersionError(
            f"unsupported checkpointVersion: {bundle['checkpointVersion']!r}"
        )
    actual_hash = compute_checkpoint_hash(bundle)
    if bundle["checkpointHash"] != actual_hash:
        raise CampaignCheckpointIntegrityError("checkpointHash mismatch")
    _assert_secret_free(
        {key: value for key, value in bundle.items() if key != "checkpointHash"}
    )
    _require_canonical_order(bundle)

    identity = bundle["campaignIdentity"]
    if set(identity) != {"campaignId", "configDigest"}:
        raise CampaignCheckpointError("campaignIdentity fields are invalid")
    campaign_id = identity["campaignId"]
    if (
        campaign_id != bundle["campaignState"]["campaign_id"]
        or bundle["cycleIndex"] != bundle["campaignState"]["current_cycle"]
    ):
        raise CampaignCheckpointConflictError("campaign identity/cycle mismatch")
    config_digest = _campaign_config_digest(bundle["campaignConfig"])
    if (
        config_digest != identity["configDigest"]
        or config_digest != bundle["campaignState"]["config_digest"]
    ):
        raise CampaignCheckpointConflictError("campaign config identity mismatch")

    jobs = bundle["jobs"]
    expected_job_ids = sorted(set(bundle["campaignState"]["cycle_job_ids"].values()))
    actual_job_ids = [job["jobId"] for job in jobs]
    if actual_job_ids != expected_job_ids:
        raise CampaignCheckpointConflictError(
            "campaign cycle job identities do not match checkpoint jobs"
        )

    expected_stage_records = [
        record for job in jobs for record in _job_stage_records(job)
    ]
    if bundle["stageRecords"] != expected_stage_records:
        raise CampaignCheckpointIntegrityError("durable stage records mismatch")

    artifacts = _artifact_records(jobs, bundle["campaignState"])
    from .release_authorization import validate_release_lineage_artifacts

    validate_release_lineage_artifacts(
        [_artifact_from_dict(artifact) for artifact in artifacts]
    )
    expected_lineage = _lineage_records(artifacts)
    if bundle["artifactLineage"] != expected_lineage:
        raise CampaignCheckpointIntegrityError("artifact lineage mismatch")
    expected_analytics = _analytics_handoffs(artifacts)
    if bundle["analyticsHandoffs"] != expected_analytics:
        raise CampaignCheckpointIntegrityError("analytics handoff identities mismatch")

    expected_growth_ids = _growth_seed_identities(
        bundle["growthSeedRecords"],
        jobs,
    )
    if bundle["growthSeedIdentities"] != expected_growth_ids:
        raise CampaignCheckpointConflictError("Growth seed identities conflict")

    expected_media = _accepted_media_jobs(bundle["externalOperations"])
    if bundle["acceptedMediaJobs"] != expected_media:
        raise CampaignCheckpointConflictError("accepted Media identities conflict")

    integrity = bundle["integrity"]
    expected_integrity = {
        "campaignConfigHash": "sha256:" + config_digest,
        "jobStateHashes": [
            {"jobId": job["jobId"], "stateHash": sha256_canonical(job)}
            for job in jobs
        ],
        "stageRecordsHash": sha256_canonical(bundle["stageRecords"]),
        "growthSeedRecordsHash": sha256_canonical(bundle["growthSeedRecords"]),
        "externalOperationsHash": sha256_canonical(bundle["externalOperations"]),
        "artifactLineageHash": sha256_canonical(bundle["artifactLineage"]),
        "analyticsHandoffsHash": sha256_canonical(bundle["analyticsHandoffs"]),
        "producerPinsHash": sha256_canonical(bundle["provenance"]),
    }
    if integrity != expected_integrity:
        raise CampaignCheckpointIntegrityError("checkpoint integrity hashes mismatch")

    if repo_root is not None:
        expected_provenance = validate_producer_pins(repo_root)
        if bundle["provenance"] != expected_provenance:
            raise CampaignCheckpointIntegrityError(
                "checkpoint producer provenance does not match pinned local fixtures"
            )


def write_campaign_checkpoint(
    bundle: Mapping[str, Any],
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> None:
    validate_campaign_checkpoint(bundle, repo_root=repo_root)
    _atomic_write(Path(path), canonical_bytes(bundle))


def load_campaign_checkpoint(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    bundle = _read_json(Path(path))
    validate_campaign_checkpoint(bundle, repo_root=repo_root)
    return bundle


def _job_raw_from_record(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": job["jobId"],
        "topic": job["topic"],
        "state": job["state"],
        "stage_index": job["stageIndex"],
        "attempts": _clone(job["attempts"]),
        "idempotency_attempts": _clone(job["idempotencyAttempts"]),
        "completed_idempotency_keys": _clone(job["completedIdempotencyKeys"]),
        "artifacts": [
            _clone(record["artifact"])
            for record in job["artifacts"]
        ],
        "evaluations": _clone(job["evaluations"]),
        "last_error": job["lastError"],
        "created_at": _FIXED_RESTORE_TIME,
        "updated_at": _FIXED_RESTORE_TIME,
    }


def _operation_raw_from_record(operation: Mapping[str, Any]) -> dict[str, Any]:
    state = operation["state"]
    return {
        "job_id": operation["jobId"],
        "stage": operation["stage"],
        "idempotency_key": operation["idempotencyKey"],
        "adapter_name": operation["adapterName"],
        "state": state,
        "request": _clone(operation["request"]),
        "request_fingerprint": operation["requestFingerprint"],
        "external_operation_id": operation["externalOperationId"],
        "acceptance_metadata": _clone(operation["acceptanceMetadata"]),
        "poll_attempts": operation["pollAttempts"],
        "poll_metadata": _clone(operation["pollMetadata"]),
        "result": _clone(operation["result"]),
        "prepared_at": _FIXED_RESTORE_TIME,
        "accepted_at": None if state == "prepared" else _FIXED_RESTORE_TIME,
        "result_obtained_at": (
            _FIXED_RESTORE_TIME
            if state in {"result_obtained", "committed"}
            else None
        ),
        "committed_at": _FIXED_RESTORE_TIME if state == "committed" else None,
        "updated_at": _FIXED_RESTORE_TIME,
    }


def _growth_raw_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ledger_version": record["ledgerVersion"],
        "sequence": record["sequence"],
        "idempotency_key": record["idempotencyKey"],
        "seed_digest": record["seedDigest"],
        "artifact": _clone(record["artifact"]),
        "status": record["status"],
    }


def import_campaign_checkpoint(
    bundle: Mapping[str, Any],
    destination_root: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> CheckpointImportResult:
    validate_campaign_checkpoint(bundle, repo_root=repo_root)
    root = Path(destination_root)
    campaign_id = bundle["campaignIdentity"]["campaignId"]
    checkpoint_hash = bundle["checkpointHash"]
    marker = root / "checkpoint-imports" / f"{campaign_id}.json"

    if marker.exists():
        prior = _read_json(marker)
        if prior == {
            "campaignId": campaign_id,
            "checkpointHash": checkpoint_hash,
            "checkpointVersion": CAMPAIGN_CHECKPOINT_VERSION,
        }:
            from .release_authorization import ReleaseAuthorizationLedger

            ReleaseAuthorizationLedger.rebuild_from_job_artifacts(
                root / "release-authorizations",
                JsonJobStore(root / "jobs"),
            )
            return CheckpointImportResult(
                "duplicate",
                campaign_id,
                checkpoint_hash,
            )
        raise CampaignCheckpointConflictError(
            "destination already contains a different checkpoint for campaign"
        )

    campaign_path = root / "campaigns" / f"{campaign_id}.json"
    if campaign_path.exists():
        existing = _campaign_state_for_checkpoint(_read_json(campaign_path))
        if existing["campaign_id"] != campaign_id:
            raise CampaignCheckpointConflictError("existing campaign identity differs")
        if existing["config_digest"] != bundle["campaignIdentity"]["configDigest"]:
            raise CampaignCheckpointConflictError(
                "existing campaign config identity differs"
            )
        raise CampaignCheckpointConflictError(
            "destination campaign exists without matching checkpoint import marker"
        )

    for job in bundle["jobs"]:
        path = root / "jobs" / f"{job['jobId']}.json"
        if path.exists():
            raise CampaignCheckpointConflictError(
                f"destination job already exists: {job['jobId']}"
            )
    operations_dir = root / "jobs" / "_operations"
    if operations_dir.exists() and any(operations_dir.glob("*.json")):
        raise CampaignCheckpointConflictError(
            "destination already contains external operation receipts"
        )
    growth_path = root / "growth-seeds.jsonl"
    if growth_path.exists() and growth_path.read_text(encoding="utf-8").strip():
        raise CampaignCheckpointConflictError(
            "destination already contains Growth seed ledger data"
        )

    _atomic_write(
        campaign_path,
        (json.dumps(bundle["campaignState"], indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    for job in bundle["jobs"]:
        _atomic_write(
            root / "jobs" / f"{job['jobId']}.json",
            (
                json.dumps(_job_raw_from_record(job), indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
    for operation in bundle["externalOperations"]:
        name = (
            f"{operation['jobId']}.{operation['stage']}."
            f"{operation['idempotencyKey']}.json"
        )
        _atomic_write(
            operations_dir / name,
            (
                json.dumps(
                    _operation_raw_from_record(operation),
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
    if bundle["growthSeedRecords"]:
        growth_wire = "".join(
            canonical_json(_growth_raw_from_record(record)) + "\n"
            for record in bundle["growthSeedRecords"]
        )
        _atomic_write(growth_path, growth_wire.encode("utf-8"))

    from .release_authorization import ReleaseAuthorizationLedger

    ReleaseAuthorizationLedger.rebuild_from_job_artifacts(
        root / "release-authorizations",
        JsonJobStore(root / "jobs"),
    )

    marker_payload = {
        "campaignId": campaign_id,
        "checkpointHash": checkpoint_hash,
        "checkpointVersion": CAMPAIGN_CHECKPOINT_VERSION,
    }
    _atomic_write(marker, canonical_bytes(marker_payload))
    return CheckpointImportResult("imported", campaign_id, checkpoint_hash)


def resume_campaign_from_checkpoint(
    bundle: Mapping[str, Any],
    destination_root: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> tuple[CampaignRunner, CheckpointImportResult]:
    result = import_campaign_checkpoint(
        bundle,
        destination_root,
        repo_root=repo_root,
    )
    config = CampaignConfig.from_dict(bundle["campaignConfig"])
    if config.campaign_id != result.campaign_id:
        raise CampaignCheckpointConflictError(
            "checkpoint campaign config id differs from imported campaign identity"
        )
    return CampaignRunner(destination_root, config), result


def build_reproducibility_report(
    checkpoints: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    final_checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    ordered = sorted(checkpoints, key=lambda item: item[0])
    return {
        "reportVersion": REPRODUCIBILITY_REPORT_VERSION,
        "checkpointVersion": CAMPAIGN_CHECKPOINT_VERSION,
        "checkpoints": [
            {
                "path": path,
                "checkpointHash": bundle["checkpointHash"],
                "cycleIndex": bundle["cycleIndex"],
                "lineageHash": bundle["integrity"]["artifactLineageHash"],
                "jobStateHashes": bundle["integrity"]["jobStateHashes"],
            }
            for path, bundle in ordered
        ],
        "finalCheckpointHash": final_checkpoint["checkpointHash"],
        "finalLineageHash": final_checkpoint["integrity"]["artifactLineageHash"],
        "producerPinsHash": final_checkpoint["integrity"]["producerPinsHash"],
    }
