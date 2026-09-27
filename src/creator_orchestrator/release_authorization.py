from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .lineage import validate_artifact_dag
from .models import Artifact, JobState
from .orchestrator import JsonJobStore

RELEASE_CANDIDATE_VERSION = "release.candidate.v1"
RELEASE_APPROVAL_REQUEST_VERSION = "release.approval_request.v1"
RELEASE_AUTHORIZATION_VERSION = "release.authorization.v1"
RELEASE_DRY_RUN_PLAN_VERSION = "release.dry_run_plan.v1"
RELEASE_DRY_RUN_RESULT_VERSION = "release.dry_run_result.v1"
RELEASE_EXECUTION_PREPARED_VERSION = "release.execution_prepared.v1"
RELEASE_SIDE_EFFECT_RECEIPT_VERSION = "release.side_effect_receipt.v1"
RELEASE_LEDGER_VERSION = "release.authorization_ledger.v1"

_RELEASE_KINDS = frozenset(
    {
        "release_candidate",
        "release_approval_request",
        "release_authorization_decision",
        "release_execution_prepared",
        "release_side_effect_receipt",
        "release_dry_run_plan",
        "release_dry_run_result",
    }
)


class ReleaseAuthorizationError(ValueError):
    pass


class ReleaseAuthorizationConflictError(ReleaseAuthorizationError):
    pass


class ReleaseAuthorizationDenied(ReleaseAuthorizationError):
    pass


class ReleaseAuthorizationExpired(ReleaseAuthorizationError):
    pass


class ReleaseAuthorizationRevoked(ReleaseAuthorizationError):
    pass


class ReleaseArtifactMutationError(ReleaseAuthorizationError):
    pass


class ReleaseDestinationScopeError(ReleaseAuthorizationError):
    pass


class ReleaseExternalInputRequired(ReleaseAuthorizationError):
    pass


class LiveReleaseDisabled(ReleaseAuthorizationError):
    pass


class ReleaseBoundaryCrash(RuntimeError):
    """Test/simulation signal for a crash after a durable release boundary."""


class LocalReleaseAdapter(Protocol):
    execution_mode: str
    provider: str

    def release(
        self,
        plan: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ReleaseRequestReceipt:
    status: str
    request_id: str
    candidate: dict[str, Any]
    request: dict[str, Any]


@dataclass(frozen=True)
class ReleaseDecisionReceipt:
    status: str
    request_id: str
    state: str
    decision: dict[str, Any]


@dataclass(frozen=True)
class ReleaseExecutionReceipt:
    status: str
    request_id: str
    receipt: dict[str, Any]


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseAuthorizationError(
            "release authorization content must be canonical JSON-compatible data"
        ) from exc


def _clone(value: Any) -> Any:
    return json.loads(_canonical(value))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_component(value: str, label: str) -> str:
    safe = "".join(character for character in value if character.isalnum() or character in "-_.")
    if not safe or safe != value:
        raise ReleaseAuthorizationError(f"unsafe {label}")
    return safe


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReleaseAuthorizationError(f"{field} must be a non-empty ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReleaseAuthorizationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReleaseAuthorizationError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _scope(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ReleaseDestinationScopeError("destinationScope must be an object")
    if set(value) != {"provider", "destination", "action"}:
        raise ReleaseDestinationScopeError(
            "destinationScope fields must be provider/destination/action exactly"
        )
    provider = value["provider"]
    destination = value["destination"]
    action = value["action"]
    if not isinstance(provider, str) or not provider:
        raise ReleaseDestinationScopeError("destinationScope.provider is required")
    if not isinstance(destination, str) or not destination:
        raise ReleaseDestinationScopeError("destinationScope.destination is required")
    if action != "release":
        raise ReleaseDestinationScopeError(
            "destinationScope.action must be 'release'"
        )
    return {
        "provider": provider,
        "destination": destination,
        "action": "release",
    }


def artifact_hash(artifact: Artifact) -> str:
    return _digest(asdict(artifact))


def campaign_lineage_hash(artifacts: Sequence[Artifact]) -> str:
    base = [artifact for artifact in artifacts if artifact.kind not in _RELEASE_KINDS]
    validate_artifact_dag(base)
    records = [
        {
            "artifactId": artifact.id,
            "artifactHash": artifact_hash(artifact),
            "kind": artifact.kind,
            "parents": list(artifact.parents),
            "producer": artifact.producer,
        }
        for artifact in sorted(base, key=lambda item: item.id)
    ]
    return _digest(records)


def _candidate_id(body: Mapping[str, Any]) -> str:
    return "release-candidate-" + hashlib.sha256(
        _canonical(body).encode("utf-8")
    ).hexdigest()[:24]


def _request_id(candidate_id: str) -> str:
    return "release-request-" + hashlib.sha256(
        candidate_id.encode("utf-8")
    ).hexdigest()[:24]


def _execution_idempotency_key(request_id: str, authorization_id: str) -> str:
    return "release-exec:" + hashlib.sha256(
        f"{request_id}|{authorization_id}".encode("utf-8")
    ).hexdigest()


def _event_digest(event_type: str, payload: Mapping[str, Any]) -> str:
    return _digest({"eventType": event_type, "payload": payload})


def _event(event_type: str, payload: Mapping[str, Any], sequence: int) -> dict[str, Any]:
    normalized = _clone(payload)
    return {
        "sequence": sequence,
        "eventType": event_type,
        "payload": normalized,
        "eventDigest": _event_digest(event_type, normalized),
    }


def _event_artifact_kind(event_type: str) -> str:
    mapping = {
        "candidate_prepared": "release_candidate",
        "approval_requested": "release_approval_request",
        "decision_recorded": "release_authorization_decision",
        "execution_prepared": "release_execution_prepared",
        "receipt_committed": "release_side_effect_receipt",
        "dry_run_planned": "release_dry_run_plan",
        "dry_run_completed": "release_dry_run_result",
    }
    try:
        return mapping[event_type]
    except KeyError as exc:
        raise ReleaseAuthorizationError(
            f"unsupported release ledger event type: {event_type}"
        ) from exc


def _event_created_at(event: Mapping[str, Any]) -> str:
    payload = event["payload"]
    for key in (
        "createdAt",
        "decidedAt",
        "checkedAt",
        "committedAt",
        "plannedAt",
        "completedAt",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return "1970-01-01T00:00:00+00:00"


def _event_artifact_id(event: Mapping[str, Any]) -> str:
    return "release-event-" + event["eventDigest"].split(":", 1)[1][:24]


def _event_parent_ids(events: Sequence[Mapping[str, Any]], index: int) -> tuple[str, ...]:
    event = events[index]
    event_type = event["eventType"]
    payload = event["payload"]
    if event_type == "candidate_prepared":
        return (payload["artifactId"],)
    if index == 0:
        return ()
    prior = events[index - 1]
    if event_type == "approval_requested":
        candidate = next(
            item
            for item in events[:index]
            if item["eventType"] == "candidate_prepared"
        )
        return (_event_artifact_id(candidate),)
    if event_type == "decision_recorded":
        if payload.get("decision") == "revoked":
            approvals = [
                item
                for item in events[:index]
                if item["eventType"] == "decision_recorded"
                and item["payload"].get("decision") == "approved"
                and item["payload"].get("authorizationId")
                == payload.get("authorizationId")
            ]
            if not approvals:
                raise ReleaseAuthorizationConflictError(
                    "revocation lineage requires the approved authorization event"
                )
            return (_event_artifact_id(approvals[-1]),)
        request = next(
            item
            for item in events[:index]
            if item["eventType"] == "approval_requested"
        )
        return (_event_artifact_id(request),)
    if event_type == "execution_prepared":
        approvals = [
            item
            for item in events[:index]
            if item["eventType"] == "decision_recorded"
            and item["payload"]["decision"] == "approved"
        ]
        if not approvals:
            raise ReleaseAuthorizationError(
                "execution preparation requires prior approval event"
            )
        return (_event_artifact_id(approvals[-1]),)
    return (_event_artifact_id(prior),)


def _ledger_state(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(events) < 2:
        raise ReleaseAuthorizationError("release ledger requires candidate and request events")
    if events[0]["eventType"] != "candidate_prepared":
        raise ReleaseAuthorizationError("release ledger first event must prepare candidate")
    if events[1]["eventType"] != "approval_requested":
        raise ReleaseAuthorizationError("release ledger second event must request approval")
    state = "pending"
    active: dict[str, Any] | None = None
    execution = "none"
    receipt: dict[str, Any] | None = None
    seen_decision_keys: dict[str, str] = {}
    seen_decision_ids: dict[str, str] = {}

    for expected_sequence, event in enumerate(events, 1):
        if event.get("sequence") != expected_sequence:
            raise ReleaseAuthorizationError("release ledger event sequence is not contiguous")
        event_type = event.get("eventType")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ReleaseAuthorizationError("release ledger event payload must be object")
        if event.get("eventDigest") != _event_digest(event_type, payload):
            raise ReleaseAuthorizationError("release ledger event digest mismatch")
        if event_type == "decision_recorded":
            decision = validate_release_authorization(payload)
            key = decision["idempotencyKey"]
            decision_id = decision["decisionId"]
            wire = _canonical(decision)
            previous = seen_decision_keys.get(key)
            if previous is not None and previous != wire:
                raise ReleaseAuthorizationConflictError(
                    "conflicting release decision idempotency reuse"
                )
            previous_id = seen_decision_ids.get(decision_id)
            if previous_id is not None and previous_id != wire:
                raise ReleaseAuthorizationConflictError(
                    "conflicting release decisionId reuse"
                )
            seen_decision_keys[key] = wire
            seen_decision_ids[decision_id] = wire

            if decision["decision"] == "approved":
                if state == "pending":
                    state = "approved"
                    active = decision
                elif active is None or _canonical(active) != wire:
                    raise ReleaseAuthorizationConflictError(
                        "approval conflicts with existing release decision state"
                    )
            elif decision["decision"] == "denied":
                if state != "pending":
                    raise ReleaseAuthorizationConflictError(
                        "denial conflicts with existing release decision state"
                    )
                state = "denied"
            elif decision["decision"] == "revoked":
                if state != "approved" or active is None:
                    raise ReleaseAuthorizationConflictError(
                        "revocation requires an active approval"
                    )
                if decision["authorizationId"] != active["authorizationId"]:
                    raise ReleaseAuthorizationConflictError(
                        "revocation authorizationId does not match active approval"
                    )
                if decision["expiresAt"] != active["expiresAt"]:
                    raise ReleaseAuthorizationConflictError(
                        "revocation expiry must preserve approved authorization binding"
                    )
                state = "revoked"
        elif event_type == "execution_prepared":
            if state != "approved" or active is None:
                raise ReleaseAuthorizationDenied(
                    "execution cannot be prepared without active approval"
                )
            if execution == "none":
                execution = "prepared"
            elif execution != "prepared":
                raise ReleaseAuthorizationConflictError(
                    "execution preparation conflicts with committed receipt"
                )
        elif event_type == "receipt_committed":
            if execution != "prepared":
                raise ReleaseAuthorizationConflictError(
                    "release receipt requires prepared execution"
                )
            execution = "committed"
            receipt = _clone(payload)

    return {
        "state": state,
        "activeAuthorization": _clone(active) if active is not None else None,
        "executionState": execution,
        "receipt": receipt,
    }




def _validate_candidate(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "contractVersion",
        "campaignId",
        "jobId",
        "artifactId",
        "artifactHash",
        "lineageHash",
        "destinationScope",
        "createdAt",
        "candidateId",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ReleaseAuthorizationError("release.candidate.v1 fields must match exactly")
    if payload["contractVersion"] != RELEASE_CANDIDATE_VERSION:
        raise ReleaseAuthorizationError(
            f"candidate contractVersion must be {RELEASE_CANDIDATE_VERSION}"
        )
    for field in (
        "campaignId",
        "jobId",
        "artifactId",
        "artifactHash",
        "lineageHash",
        "candidateId",
        "createdAt",
    ):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ReleaseAuthorizationError(f"candidate {field} must be non-empty")
    _scope(payload["destinationScope"])
    _parse_time(payload["createdAt"], "candidate.createdAt")
    body = {key: value for key, value in payload.items() if key != "candidateId"}
    if payload["candidateId"] != _candidate_id(body):
        raise ReleaseAuthorizationConflictError("release candidateId digest mismatch")
    return _clone(payload)


def _validate_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "contractVersion",
        "requestId",
        "campaignId",
        "jobId",
        "candidateId",
        "artifactId",
        "artifactHash",
        "lineageHash",
        "destinationScope",
        "createdAt",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ReleaseAuthorizationError(
            "release.approval_request.v1 fields must match exactly"
        )
    if payload["contractVersion"] != RELEASE_APPROVAL_REQUEST_VERSION:
        raise ReleaseAuthorizationError(
            f"request contractVersion must be {RELEASE_APPROVAL_REQUEST_VERSION}"
        )
    for field in (
        "requestId",
        "campaignId",
        "jobId",
        "candidateId",
        "artifactId",
        "artifactHash",
        "lineageHash",
        "createdAt",
    ):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ReleaseAuthorizationError(f"request {field} must be non-empty")
    _scope(payload["destinationScope"])
    _parse_time(payload["createdAt"], "request.createdAt")
    if payload["requestId"] != _request_id(payload["candidateId"]):
        raise ReleaseAuthorizationConflictError("release requestId digest mismatch")
    return _clone(payload)


def validate_release_authorization(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ReleaseAuthorizationError("release authorization must be an object")
    expected = {
        "contractVersion",
        "decisionId",
        "idempotencyKey",
        "requestId",
        "campaignId",
        "candidateId",
        "artifactId",
        "artifactHash",
        "lineageHash",
        "destinationScope",
        "decision",
        "authorizationId",
        "expiresAt",
        "decidedAt",
        "decisionSource",
        "approverRef",
    }
    if set(payload) != expected:
        raise ReleaseAuthorizationError(
            "release.authorization.v1 fields must match exactly"
        )
    if payload["contractVersion"] != RELEASE_AUTHORIZATION_VERSION:
        raise ReleaseAuthorizationError(
            f"contractVersion must be {RELEASE_AUTHORIZATION_VERSION}"
        )
    for field in (
        "decisionId",
        "idempotencyKey",
        "requestId",
        "campaignId",
        "candidateId",
        "artifactId",
        "artifactHash",
        "lineageHash",
        "decidedAt",
        "approverRef",
    ):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ReleaseAuthorizationError(f"{field} must be non-empty")
    if payload["decisionSource"] != "external":
        raise ReleaseExternalInputRequired(
            "approval decisions must come from explicit external input"
        )
    decision = payload["decision"]
    if decision not in {"approved", "denied", "revoked"}:
        raise ReleaseAuthorizationError(
            "decision must be approved, denied, or revoked"
        )
    authorization_id = payload["authorizationId"]
    expires_at = payload["expiresAt"]
    if decision == "denied":
        if authorization_id is not None or expires_at is not None:
            raise ReleaseAuthorizationError(
                "denied decision must have null authorizationId/expiresAt"
            )
    else:
        if not isinstance(authorization_id, str) or not authorization_id:
            raise ReleaseAuthorizationError(
                "approved/revoked decision requires authorizationId"
            )
        if not isinstance(expires_at, str) or not expires_at:
            raise ReleaseAuthorizationError(
                "approved/revoked decision requires expiresAt"
            )
        decided = _parse_time(payload["decidedAt"], "decidedAt")
        expires = _parse_time(expires_at, "expiresAt")
        if decision == "approved" and expires <= decided:
            raise ReleaseAuthorizationError(
                "approved authorization must expire after decidedAt"
            )
    _scope(payload["destinationScope"])
    return _clone(payload)


class ReleaseAuthorizationLedger:
    def __init__(
        self,
        directory: str | os.PathLike[str],
        job_store: JsonJobStore,
        *,
        boundary_hook: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.job_store = job_store
        self.boundary_hook = boundary_hook

    def _path(self, request_id: str) -> Path:
        return self.directory / f"{_safe_component(request_id, 'request id')}.json"

    def _save(self, record: Mapping[str, Any]) -> None:
        request_id = record["requestId"]
        path = self._path(request_id)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(record, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _load(self, request_id: str) -> dict[str, Any]:
        try:
            record = json.loads(self._path(request_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseAuthorizationError(
                f"cannot load release authorization ledger {request_id}"
            ) from exc
        self._validate_record(record)
        return record

    def _validate_record(self, record: Mapping[str, Any]) -> None:
        expected = {
            "ledgerVersion",
            "campaignId",
            "jobId",
            "requestId",
            "events",
        }
        if not isinstance(record, Mapping) or set(record) != expected:
            raise ReleaseAuthorizationError("release ledger record fields are invalid")
        if record["ledgerVersion"] != RELEASE_LEDGER_VERSION:
            raise ReleaseAuthorizationError("unsupported release ledger version")
        if not isinstance(record["events"], list):
            raise ReleaseAuthorizationError("release ledger events must be an array")
        state = _ledger_state(record["events"])
        candidate = _validate_candidate(record["events"][0]["payload"])
        request = _validate_request(record["events"][1]["payload"])
        if (
            record["campaignId"] != candidate["campaignId"]
            or record["campaignId"] != request["campaignId"]
            or record["jobId"] != candidate["jobId"]
            or record["jobId"] != request["jobId"]
            or record["requestId"] != request["requestId"]
        ):
            raise ReleaseAuthorizationConflictError(
                "release ledger identity does not match candidate/request"
            )
        for event in record["events"]:
            if event["eventType"] == "decision_recorded":
                decision = event["payload"]
                if (
                    decision["requestId"] != record["requestId"]
                    or decision["campaignId"] != record["campaignId"]
                    or decision["candidateId"] != candidate["candidateId"]
                    or decision["artifactId"] != candidate["artifactId"]
                    or decision["artifactHash"] != candidate["artifactHash"]
                    or decision["lineageHash"] != candidate["lineageHash"]
                    or _scope(decision["destinationScope"])
                    != _scope(candidate["destinationScope"])
                ):
                    raise ReleaseAuthorizationConflictError(
                        "release decision does not match immutable request binding"
                    )
        if state["executionState"] != "none":
            prepared = [
                event["payload"]
                for event in record["events"]
                if event["eventType"] == "execution_prepared"
            ]
            if len(prepared) != 1:
                raise ReleaseAuthorizationConflictError(
                    "release ledger must contain exactly one execution preparation"
                )

    def exists(self, request_id: str) -> bool:
        return self._path(request_id).exists()

    def list_records(self) -> list[dict[str, Any]]:
        records = [self._load(path.stem) for path in sorted(self.directory.glob("*.json"))]
        return records

    def _append_event(
        self,
        record: dict[str, Any],
        event_type: str,
        payload: Mapping[str, Any],
        *,
        boundary: str | None = None,
    ) -> dict[str, Any]:
        event = _event(event_type, payload, len(record["events"]) + 1)
        record = _clone(record)
        record["events"].append(event)
        self._validate_record(record)
        self._save(record)
        self._sync_record_artifacts(record)
        if boundary is not None and self.boundary_hook is not None:
            self.boundary_hook(boundary, event)
        return record

    def _sync_record_artifacts(self, record: Mapping[str, Any]) -> None:
        job = self.job_store.load(record["jobId"])
        existing = {artifact.id for artifact in job.artifacts}
        changed = False
        for index, event in enumerate(record["events"]):
            artifact_id = _event_artifact_id(event)
            if artifact_id in existing:
                continue
            parents = _event_parent_ids(record["events"], index)
            artifact = Artifact(
                id=artifact_id,
                kind=_event_artifact_kind(event["eventType"]),
                uri=(
                    f"release://{record['campaignId']}/"
                    f"{record['requestId']}/{event['sequence']}"
                ),
                producer="creator-release-authorization",
                parents=parents,
                metadata={
                    "ledgerVersion": RELEASE_LEDGER_VERSION,
                    "requestId": record["requestId"],
                    "sequence": event["sequence"],
                    "eventType": event["eventType"],
                    "eventDigest": event["eventDigest"],
                    "payload": _clone(event["payload"]),
                },
                created_at=_event_created_at(event),
            )
            job.artifacts.append(artifact)
            existing.add(artifact_id)
            changed = True
        if changed:
            job.touch()
            self.job_store.save(job)

    def _find_decision_by_idempotency(
        self,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for record in self.list_records():
            for event in record["events"]:
                if (
                    event["eventType"] == "decision_recorded"
                    and event["payload"]["idempotencyKey"] == idempotency_key
                ):
                    return record, event["payload"]
        return None


    def _campaign_artifacts(
        self,
        campaign_id: str,
        *,
        expected_job_id: str,
    ) -> list[Artifact]:
        campaign_path = (
            self.directory.parent
            / "campaigns"
            / f"{_safe_component(campaign_id, 'campaign id')}.json"
        )
        try:
            raw = json.loads(campaign_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseAuthorizationError(
                f"cannot load durable campaign state for {campaign_id}"
            ) from exc
        if not isinstance(raw, Mapping) or raw.get("campaign_id") != campaign_id:
            raise ReleaseAuthorizationConflictError(
                "release campaign identity does not match durable campaign state"
            )
        if raw.get("status") != "complete":
            raise ReleaseAuthorizationError(
                "release authorization requires a completed campaign"
            )
        cycle_job_ids = raw.get("cycle_job_ids")
        if not isinstance(cycle_job_ids, Mapping):
            raise ReleaseAuthorizationError("durable campaign cycle_job_ids is invalid")
        job_ids = [cycle_job_ids[key] for key in sorted(cycle_job_ids, key=lambda item: int(item))]
        if expected_job_id not in job_ids:
            raise ReleaseAuthorizationConflictError(
                "release Creator job does not belong to campaign"
            )
        artifacts: list[Artifact] = []
        for job_id in job_ids:
            artifacts.extend(self.job_store.load(job_id).artifacts)
        report = raw.get("report_artifact")
        if report is not None:
            if not isinstance(report, Mapping):
                raise ReleaseAuthorizationError("campaign report artifact is invalid")
            artifacts.append(
                Artifact(
                    **{
                        **report,
                        "parents": tuple(report.get("parents", ())),
                    }
                )
            )
        return artifacts

    def prepare_request(
        self,
        *,
        campaign_id: str,
        job_id: str,
        queued_artifact_id: str,
        destination_scope: Mapping[str, Any],
        created_at: str,
    ) -> ReleaseRequestReceipt:
        _parse_time(created_at, "createdAt")
        scope = _scope(destination_scope)
        job = self.job_store.load(job_id)
        if job.state != JobState.COMPLETE:
            raise ReleaseAuthorizationError(
                "release candidate may only be prepared from a completed Creator job"
            )
        target = next(
            (artifact for artifact in job.artifacts if artifact.id == queued_artifact_id),
            None,
        )
        if target is None:
            raise ReleaseAuthorizationError("queued release artifact not found")
        if target.kind not in {"publish_queue_item", "publish_manifest"}:
            raise ReleaseAuthorizationError(
                "release candidate must bind a queued release artifact"
            )
        target_hash = artifact_hash(target)
        campaign_artifacts = self._campaign_artifacts(
            campaign_id,
            expected_job_id=job_id,
        )
        lineage_hash = campaign_lineage_hash(campaign_artifacts)
        candidate_body = {
            "contractVersion": RELEASE_CANDIDATE_VERSION,
            "campaignId": campaign_id,
            "jobId": job_id,
            "artifactId": target.id,
            "artifactHash": target_hash,
            "lineageHash": lineage_hash,
            "destinationScope": scope,
            "createdAt": created_at,
        }
        candidate = {
            **candidate_body,
            "candidateId": _candidate_id(candidate_body),
        }
        request = {
            "contractVersion": RELEASE_APPROVAL_REQUEST_VERSION,
            "requestId": _request_id(candidate["candidateId"]),
            "campaignId": campaign_id,
            "jobId": job_id,
            "candidateId": candidate["candidateId"],
            "artifactId": target.id,
            "artifactHash": target_hash,
            "lineageHash": lineage_hash,
            "destinationScope": scope,
            "createdAt": created_at,
        }
        request_id = request["requestId"]

        if self.exists(request_id):
            record = self._load(request_id)
            if (
                record["events"][0]["payload"] != candidate
                or record["events"][1]["payload"] != request
            ):
                raise ReleaseAuthorizationConflictError(
                    "release request identity reused for different immutable binding"
                )
            self._sync_record_artifacts(record)
            return ReleaseRequestReceipt("duplicate", request_id, candidate, request)

        record = {
            "ledgerVersion": RELEASE_LEDGER_VERSION,
            "campaignId": campaign_id,
            "jobId": job_id,
            "requestId": request_id,
            "events": [
                _event("candidate_prepared", candidate, 1),
                _event("approval_requested", request, 2),
            ],
        }
        self._validate_record(record)
        self._save(record)
        self._sync_record_artifacts(record)
        if self.boundary_hook is not None:
            self.boundary_hook("after_request_commit", record["events"][-1])
        return ReleaseRequestReceipt("committed", request_id, candidate, request)

    def record_external_decision(
        self,
        payload: Mapping[str, Any],
    ) -> ReleaseDecisionReceipt:
        decision = validate_release_authorization(payload)
        existing = self._find_decision_by_idempotency(decision["idempotencyKey"])
        if existing is not None:
            record, previous = existing
            if _canonical(previous) != _canonical(decision):
                raise ReleaseAuthorizationConflictError(
                    "conflicting release decision idempotency reuse"
                )
            self._sync_record_artifacts(record)
            state = _ledger_state(record["events"])["state"]
            return ReleaseDecisionReceipt(
                "duplicate",
                record["requestId"],
                state,
                decision,
            )

        if not self.exists(decision["requestId"]):
            raise ReleaseAuthorizationError("unknown release approval request")
        record = self._load(decision["requestId"])
        candidate = record["events"][0]["payload"]
        request = record["events"][1]["payload"]
        for field in (
            "campaignId",
            "candidateId",
            "artifactId",
            "artifactHash",
            "lineageHash",
        ):
            if decision[field] != request[field]:
                raise ReleaseAuthorizationConflictError(
                    f"release decision {field} does not match approval request"
                )
        if _scope(decision["destinationScope"]) != _scope(request["destinationScope"]):
            raise ReleaseDestinationScopeError(
                "release decision destination scope does not match request"
            )

        current = _ledger_state(record["events"])
        if decision["decision"] == "approved" and current["state"] != "pending":
            raise ReleaseAuthorizationConflictError(
                "approval conflicts with existing release state"
            )
        if decision["decision"] == "denied" and current["state"] != "pending":
            raise ReleaseAuthorizationConflictError(
                "denial conflicts with existing release state"
            )
        if decision["decision"] == "revoked":
            active = current["activeAuthorization"]
            if current["state"] != "approved" or active is None:
                raise ReleaseAuthorizationConflictError(
                    "revocation requires an active approval"
                )
            if decision["authorizationId"] != active["authorizationId"]:
                raise ReleaseAuthorizationConflictError(
                    "revocation authorizationId does not match active approval"
                )
            if decision["expiresAt"] != active["expiresAt"]:
                raise ReleaseAuthorizationConflictError(
                    "revocation expiry does not match active approval"
                )

        record = self._append_event(
            record,
            "decision_recorded",
            decision,
            boundary="after_approval_commit",
        )
        state = _ledger_state(record["events"])["state"]
        return ReleaseDecisionReceipt(
            "committed",
            record["requestId"],
            state,
            decision,
        )

    def snapshot(self, request_id: str) -> dict[str, Any]:
        record = self._load(request_id)
        state = _ledger_state(record["events"])
        return {
            "ledgerVersion": RELEASE_LEDGER_VERSION,
            "campaignId": record["campaignId"],
            "jobId": record["jobId"],
            "requestId": record["requestId"],
            "candidate": _clone(record["events"][0]["payload"]),
            "request": _clone(record["events"][1]["payload"]),
            **state,
            "events": _clone(record["events"]),
        }

    def _validate_current_binding(
        self,
        snapshot: Mapping[str, Any],
        *,
        destination_scope: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        scope = _scope(destination_scope)
        request = snapshot["request"]
        candidate = snapshot["candidate"]
        if scope != _scope(request["destinationScope"]):
            raise ReleaseDestinationScopeError(
                "execution destination scope does not match approved request"
            )
        state = snapshot["state"]
        if state == "pending":
            raise ReleaseAuthorizationDenied("release approval is still pending")
        if state == "denied":
            raise ReleaseAuthorizationDenied("release approval was denied")
        if state == "revoked":
            raise ReleaseAuthorizationRevoked("release authorization was revoked")
        if state != "approved":
            raise ReleaseAuthorizationDenied("release is not approved")

        authorization = snapshot["activeAuthorization"]
        if authorization is None:
            raise ReleaseAuthorizationDenied("approved state is missing authorization")
        now_value = _parse_time(now, "now")
        expires = _parse_time(authorization["expiresAt"], "expiresAt")
        if now_value >= expires:
            raise ReleaseAuthorizationExpired("release authorization has expired")
        if _scope(authorization["destinationScope"]) != scope:
            raise ReleaseDestinationScopeError(
                "authorization destination scope does not match execution"
            )

        job = self.job_store.load(snapshot["jobId"])
        target = next(
            (artifact for artifact in job.artifacts if artifact.id == candidate["artifactId"]),
            None,
        )
        if target is None:
            raise ReleaseArtifactMutationError("authorized release artifact is missing")
        current_artifact_hash = artifact_hash(target)
        if current_artifact_hash != candidate["artifactHash"]:
            raise ReleaseArtifactMutationError(
                "authorized release artifact hash changed"
            )
        campaign_artifacts = self._campaign_artifacts(
            candidate["campaignId"],
            expected_job_id=snapshot["jobId"],
        )
        current_lineage_hash = campaign_lineage_hash(campaign_artifacts)
        if current_lineage_hash != candidate["lineageHash"]:
            raise ReleaseArtifactMutationError(
                "authorized campaign lineage changed"
            )
        for field in (
            "campaignId",
            "candidateId",
            "artifactId",
            "artifactHash",
            "lineageHash",
        ):
            if authorization[field] != request[field]:
                raise ReleaseAuthorizationConflictError(
                    f"active authorization {field} differs from request"
                )
        return authorization

    def build_dry_run(
        self,
        request_id: str,
        *,
        destination_scope: Mapping[str, Any],
        planned_at: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _parse_time(planned_at, "plannedAt")
        snapshot = self.snapshot(request_id)
        scope = _scope(destination_scope)
        if scope != _scope(snapshot["request"]["destinationScope"]):
            raise ReleaseDestinationScopeError(
                "dry-run destination scope does not match approval request"
            )
        plan_body = {
            "contractVersion": RELEASE_DRY_RUN_PLAN_VERSION,
            "requestId": request_id,
            "candidateId": snapshot["candidate"]["candidateId"],
            "artifactId": snapshot["candidate"]["artifactId"],
            "artifactHash": snapshot["candidate"]["artifactHash"],
            "lineageHash": snapshot["candidate"]["lineageHash"],
            "destinationScope": scope,
            "plannedAt": planned_at,
            "externalSideEffects": False,
        }
        plan = {
            **plan_body,
            "planHash": _digest(plan_body),
        }
        result_body = {
            "contractVersion": RELEASE_DRY_RUN_RESULT_VERSION,
            "requestId": request_id,
            "planHash": plan["planHash"],
            "candidateId": snapshot["candidate"]["candidateId"],
            "destinationScope": scope,
            "authorizationState": snapshot["state"],
            "externalSideEffects": 0,
            "completedAt": planned_at,
        }
        result = {
            **result_body,
            "resultHash": _digest(result_body),
        }

        record = self._load(request_id)
        existing_plan = [
            event
            for event in record["events"]
            if event["eventType"] == "dry_run_planned"
            and event["payload"]["planHash"] == plan["planHash"]
        ]
        if not existing_plan:
            record = self._append_event(record, "dry_run_planned", plan)
        existing_result = [
            event
            for event in record["events"]
            if event["eventType"] == "dry_run_completed"
            and event["payload"]["resultHash"] == result["resultHash"]
        ]
        if not existing_result:
            self._append_event(record, "dry_run_completed", result)
        return plan, result

    def execute_authorized(
        self,
        request_id: str,
        *,
        destination_scope: Mapping[str, Any],
        now: str,
        adapter: LocalReleaseAdapter,
    ) -> ReleaseExecutionReceipt:
        if getattr(adapter, "execution_mode", None) != "local-simulated":
            raise LiveReleaseDisabled(
                "only local-simulated release adapters are permitted"
            )
        snapshot = self.snapshot(request_id)
        if snapshot["executionState"] == "committed":
            return ReleaseExecutionReceipt(
                "duplicate",
                request_id,
                _clone(snapshot["receipt"]),
            )

        authorization = self._validate_current_binding(
            snapshot,
            destination_scope=destination_scope,
            now=now,
        )
        scope = _scope(destination_scope)
        if adapter.provider != scope["provider"]:
            raise ReleaseDestinationScopeError(
                "release adapter provider does not match approved scope"
            )
        operation_key = _execution_idempotency_key(
            request_id,
            authorization["authorizationId"],
        )

        record = self._load(request_id)
        execution_events = [
            event
            for event in record["events"]
            if event["eventType"] == "execution_prepared"
        ]
        if not execution_events:
            prepared = {
                "contractVersion": RELEASE_EXECUTION_PREPARED_VERSION,
                "requestId": request_id,
                "authorizationId": authorization["authorizationId"],
                "idempotencyKey": operation_key,
                "candidateId": snapshot["candidate"]["candidateId"],
                "artifactId": snapshot["candidate"]["artifactId"],
                "artifactHash": snapshot["candidate"]["artifactHash"],
                "lineageHash": snapshot["candidate"]["lineageHash"],
                "destinationScope": scope,
                "checkedAt": now,
            }
            record = self._append_event(record, "execution_prepared", prepared)
        else:
            prepared = execution_events[0]["payload"]
            if (
                prepared["idempotencyKey"] != operation_key
                or prepared["authorizationId"] != authorization["authorizationId"]
                or prepared["destinationScope"] != scope
            ):
                raise ReleaseAuthorizationConflictError(
                    "prepared release execution identity conflicts with active authorization"
                )

        if self.boundary_hook is not None:
            self.boundary_hook(
                "after_final_authorization_check",
                {
                    "requestId": request_id,
                    "idempotencyKey": operation_key,
                },
            )

        plan = {
            "contractVersion": "release.local_execution_plan.v1",
            "requestId": request_id,
            "authorizationId": authorization["authorizationId"],
            "candidateId": snapshot["candidate"]["candidateId"],
            "artifactId": snapshot["candidate"]["artifactId"],
            "artifactHash": snapshot["candidate"]["artifactHash"],
            "lineageHash": snapshot["candidate"]["lineageHash"],
            "destinationScope": scope,
        }
        adapter_result = adapter.release(
            plan,
            idempotency_key=operation_key,
        )
        if self.boundary_hook is not None:
            self.boundary_hook(
                "after_side_effect_before_receipt_commit",
                {
                    "requestId": request_id,
                    "idempotencyKey": operation_key,
                },
            )

        receipt_body = {
            "contractVersion": RELEASE_SIDE_EFFECT_RECEIPT_VERSION,
            "requestId": request_id,
            "authorizationId": authorization["authorizationId"],
            "idempotencyKey": operation_key,
            "candidateId": snapshot["candidate"]["candidateId"],
            "artifactId": snapshot["candidate"]["artifactId"],
            "artifactHash": snapshot["candidate"]["artifactHash"],
            "lineageHash": snapshot["candidate"]["lineageHash"],
            "destinationScope": scope,
            "adapterMode": adapter.execution_mode,
            "adapterResult": _clone(adapter_result),
            "committedAt": now,
        }
        receipt = {
            **receipt_body,
            "receiptHash": _digest(receipt_body),
        }
        record = self._load(request_id)
        current_state = _ledger_state(record["events"])
        if current_state["executionState"] == "committed":
            committed = current_state["receipt"]
            if committed != receipt:
                raise ReleaseAuthorizationConflictError(
                    "release receipt conflicts with existing committed receipt"
                )
            return ReleaseExecutionReceipt("duplicate", request_id, _clone(receipt))
        record = self._append_event(
            record,
            "receipt_committed",
            receipt,
            boundary="after_receipt_commit",
        )
        return ReleaseExecutionReceipt("committed", request_id, receipt)

    @classmethod
    def rebuild_from_job_artifacts(
        cls,
        directory: str | os.PathLike[str],
        job_store: JsonJobStore,
    ) -> "ReleaseAuthorizationLedger":
        ledger = cls(directory, job_store)
        grouped: dict[str, dict[str, Any]] = {}
        for path in sorted(job_store.directory.glob("*.json")):
            job = job_store.load(path.stem)
            for artifact in job.artifacts:
                if artifact.kind not in _RELEASE_KINDS:
                    continue
                metadata = artifact.metadata
                if (
                    not isinstance(metadata, Mapping)
                    or metadata.get("ledgerVersion") != RELEASE_LEDGER_VERSION
                ):
                    raise ReleaseAuthorizationError(
                        f"invalid release lineage artifact: {artifact.id}"
                    )
                request_id = metadata.get("requestId")
                if not isinstance(request_id, str) or not request_id:
                    raise ReleaseAuthorizationError(
                        "release lineage artifact missing requestId"
                    )
                event = {
                    "sequence": metadata.get("sequence"),
                    "eventType": metadata.get("eventType"),
                    "eventDigest": metadata.get("eventDigest"),
                    "payload": _clone(metadata.get("payload")),
                }
                if artifact.id != _event_artifact_id(event):
                    raise ReleaseAuthorizationConflictError(
                        "release lineage artifact id does not match event digest"
                    )
                entry = grouped.setdefault(
                    request_id,
                    {
                        "jobId": job.id,
                        "events": [],
                    },
                )
                if entry["jobId"] != job.id:
                    raise ReleaseAuthorizationConflictError(
                        "release request spans multiple Creator jobs"
                    )
                entry["events"].append(event)

        for request_id, item in grouped.items():
            events = sorted(item["events"], key=lambda event: event["sequence"])
            candidate = events[0]["payload"]
            record = {
                "ledgerVersion": RELEASE_LEDGER_VERSION,
                "campaignId": candidate["campaignId"],
                "jobId": item["jobId"],
                "requestId": request_id,
                "events": events,
            }
            ledger._validate_record(record)
            if ledger.exists(request_id):
                existing = ledger._load(request_id)
                if existing != record:
                    raise ReleaseAuthorizationConflictError(
                        "restored release ledger conflicts with existing ledger"
                    )
            else:
                ledger._save(record)
        return ledger




def validate_release_lineage_artifacts(
    artifacts: Sequence[Artifact],
) -> list[dict[str, Any]]:
    """Validate checkpoint-carried release ledger events without mutable runtime state."""
    grouped: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.kind not in _RELEASE_KINDS:
            continue
        metadata = artifact.metadata
        if (
            not isinstance(metadata, Mapping)
            or set(metadata)
            != {
                "ledgerVersion",
                "requestId",
                "sequence",
                "eventType",
                "eventDigest",
                "payload",
            }
            or metadata["ledgerVersion"] != RELEASE_LEDGER_VERSION
        ):
            raise ReleaseAuthorizationError(
                f"invalid checkpoint release lineage artifact: {artifact.id}"
            )
        request_id = metadata["requestId"]
        if not isinstance(request_id, str) or not request_id:
            raise ReleaseAuthorizationError("release lineage requestId is invalid")
        event = {
            "sequence": metadata["sequence"],
            "eventType": metadata["eventType"],
            "eventDigest": metadata["eventDigest"],
            "payload": _clone(metadata["payload"]),
        }
        if artifact.id != _event_artifact_id(event):
            raise ReleaseAuthorizationConflictError(
                "release lineage artifact id does not match event digest"
            )
        entry = grouped.setdefault(
            request_id,
            {
                "events": [],
                "artifactIds": [],
                "parentsByDigest": {},
            },
        )
        entry["events"].append(event)
        entry["artifactIds"].append(artifact.id)
        entry["parentsByDigest"][event["eventDigest"]] = tuple(artifact.parents)

    summaries: list[dict[str, Any]] = []
    for request_id in sorted(grouped):
        events = sorted(grouped[request_id]["events"], key=lambda event: event["sequence"])
        state = _ledger_state(events)
        for index, event in enumerate(events):
            expected_parents = _event_parent_ids(events, index)
            actual_parents = grouped[request_id]["parentsByDigest"][event["eventDigest"]]
            if actual_parents != expected_parents:
                raise ReleaseAuthorizationConflictError(
                    "release lineage artifact parents do not match authorization event chain"
                )
        candidate = _validate_candidate(events[0]["payload"])
        request = _validate_request(events[1]["payload"])
        if request["requestId"] != request_id:
            raise ReleaseAuthorizationConflictError(
                "release lineage request identity mismatch"
            )
        if (
            candidate["candidateId"] != request["candidateId"]
            or candidate["campaignId"] != request["campaignId"]
            or candidate["jobId"] != request["jobId"]
            or candidate["artifactId"] != request["artifactId"]
            or candidate["artifactHash"] != request["artifactHash"]
            or candidate["lineageHash"] != request["lineageHash"]
            or _scope(candidate["destinationScope"])
            != _scope(request["destinationScope"])
        ):
            raise ReleaseAuthorizationConflictError(
                "release candidate/request immutable binding mismatch"
            )
        summaries.append(
            {
                "requestId": request_id,
                "campaignId": request["campaignId"],
                "jobId": request["jobId"],
                "candidateId": request["candidateId"],
                "artifactId": request["artifactId"],
                "artifactHash": request["artifactHash"],
                "lineageHash": request["lineageHash"],
                "state": state["state"],
                "executionState": state["executionState"],
                "eventDigests": [event["eventDigest"] for event in events],
            }
        )
    return summaries


class FakeLocalReleaseAdapter:
    """Local-only idempotent side-effect simulator. Never performs network I/O."""

    execution_mode = "local-simulated"

    def __init__(self, provider: str = "local-release-sim") -> None:
        self.provider = provider
        self.calls = 0
        self.accepted_side_effects = 0
        self._by_key: dict[str, tuple[str, dict[str, Any]]] = {}

    def release(
        self,
        plan: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        self.calls += 1
        wire = _canonical(plan)
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            previous_wire, result = existing
            if previous_wire != wire:
                raise ReleaseAuthorizationConflictError(
                    "simulated release idempotency key reused for different plan"
                )
            return _clone(result)
        self.accepted_side_effects += 1
        result = {
            "contractVersion": "release.local_simulated_result.v1",
            "simulated": True,
            "externalMutation": False,
            "provider": self.provider,
            "destination": plan["destinationScope"]["destination"],
            "operationId": "local-release-" + hashlib.sha256(
                idempotency_key.encode("utf-8")
            ).hexdigest()[:24],
        }
        self._by_key[idempotency_key] = (wire, result)
        return _clone(result)
