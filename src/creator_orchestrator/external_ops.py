from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .models import Artifact, JobStage, StepResult, utc_now
from .ports import StepContext


class OperationState(str, Enum):
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    RESULT_OBTAINED = "result_obtained"
    COMMITTED = "committed"


class OperationLedgerError(RuntimeError):
    pass


class OperationConflictError(OperationLedgerError):
    pass


class OperationPollTimeout(TimeoutError):
    pass


class OperationPending(RuntimeError):
    pass


class OperationPollingExhausted(RuntimeError):
    pass


class OperationBoundaryCrash(RuntimeError):
    """Test/simulation signal for a process crash at a durable handoff boundary."""


@dataclass(frozen=True)
class OperationAcceptance:
    external_operation_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationPollResult:
    done: bool
    result: StepResult | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ResumableAdapter(Protocol):
    name: str

    def prepare(self, context: StepContext) -> Mapping[str, Any]:
        """Build the immutable submission payload for this logical stage operation."""

    def submit(
        self,
        context: StepContext,
        request: Mapping[str, Any],
    ) -> OperationAcceptance:
        """Submit exactly one logical side-effect operation and return its stable handle."""

    def poll(
        self,
        context: StepContext,
        external_operation_id: str,
    ) -> OperationPollResult:
        """Read/resume a previously accepted operation without resubmitting it."""


@dataclass(frozen=True)
class OperationResumePolicy:
    max_poll_attempts: int = 100

    def __post_init__(self) -> None:
        if self.max_poll_attempts < 1:
            raise ValueError("max_poll_attempts must be >= 1")


@dataclass
class OperationReceipt:
    job_id: str
    stage: str
    idempotency_key: str
    adapter_name: str
    state: OperationState
    request: dict[str, Any]
    request_fingerprint: str
    external_operation_id: str | None = None
    acceptance_metadata: dict[str, Any] = field(default_factory=dict)
    poll_attempts: int = 0
    poll_metadata: dict[str, Any] = field(default_factory=dict)
    result: StepResult | None = None
    prepared_at: str = field(default_factory=utc_now)
    accepted_at: str | None = None
    result_obtained_at: str | None = None
    committed_at: str | None = None
    updated_at: str = field(default_factory=utc_now)


def _json_clone(value: Any, label: str) -> Any:
    try:
        wire = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise OperationLedgerError(f"{label} must be JSON-compatible") from exc
    return json.loads(wire)


def _request_fingerprint(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _serialize_result(result: StepResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "artifacts": [asdict(artifact) for artifact in result.artifacts],
        "metadata": _json_clone(result.metadata, "operation result metadata"),
    }


def _deserialize_result(payload: Mapping[str, Any] | None) -> StepResult | None:
    if payload is None:
        return None
    artifacts = tuple(
        Artifact(
            **{
                **item,
                "parents": tuple(item.get("parents", ())),
            }
        )
        for item in payload.get("artifacts", [])
    )
    return StepResult(
        artifacts=artifacts,
        metadata=dict(payload.get("metadata", {})),
    )


class JsonOperationLedger:
    """Durable provider-operation receipts keyed by Creator stage idempotency."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_component(value: str, label: str) -> str:
        safe = "".join(c for c in value if c.isalnum() or c in "-_.")
        if not safe or safe != value:
            raise ValueError(f"unsafe {label}")
        return safe

    def _path(self, job_id: str, stage: str, idempotency_key: str) -> Path:
        job = self._safe_component(job_id, "job id")
        stage_name = self._safe_component(stage, "stage")
        key = self._safe_component(idempotency_key, "idempotency key")
        return self.directory / f"{job}.{stage_name}.{key}.json"

    def exists(self, job_id: str, stage: str, idempotency_key: str) -> bool:
        return self._path(job_id, stage, idempotency_key).exists()

    def save(self, receipt: OperationReceipt) -> None:
        payload = {
            **asdict(receipt),
            "state": receipt.state.value,
            "result": _serialize_result(receipt.result),
        }
        path = self._path(receipt.job_id, receipt.stage, receipt.idempotency_key)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load(self, job_id: str, stage: str, idempotency_key: str) -> OperationReceipt:
        data = json.loads(
            self._path(job_id, stage, idempotency_key).read_text(encoding="utf-8")
        )
        data["state"] = OperationState(data["state"])
        data["result"] = _deserialize_result(data.get("result"))
        return OperationReceipt(**data)

    def prepare(
        self,
        *,
        job_id: str,
        stage: JobStage,
        idempotency_key: str,
        adapter_name: str,
        request: Mapping[str, Any],
    ) -> OperationReceipt:
        normalized = _json_clone(request, "operation request")
        fingerprint = _request_fingerprint(normalized)
        if self.exists(job_id, stage.value, idempotency_key):
            receipt = self.load(job_id, stage.value, idempotency_key)
            if receipt.adapter_name != adapter_name:
                raise OperationConflictError(
                    "idempotency key reused by a different resumable adapter"
                )
            if receipt.request_fingerprint != fingerprint:
                raise OperationConflictError(
                    "idempotency key reused with a conflicting operation request"
                )
            return receipt
        receipt = OperationReceipt(
            job_id=job_id,
            stage=stage.value,
            idempotency_key=idempotency_key,
            adapter_name=adapter_name,
            state=OperationState.PREPARED,
            request=normalized,
            request_fingerprint=fingerprint,
        )
        self.save(receipt)
        return receipt

    def accept(
        self,
        receipt: OperationReceipt,
        acceptance: OperationAcceptance,
    ) -> OperationReceipt:
        if receipt.state != OperationState.PREPARED:
            raise OperationLedgerError("only prepared operations may be accepted")
        handle = acceptance.external_operation_id
        if not isinstance(handle, str) or not handle:
            raise OperationLedgerError("accepted operation requires a stable external handle")
        receipt.state = OperationState.ACCEPTED
        receipt.external_operation_id = handle
        receipt.acceptance_metadata = _json_clone(
            acceptance.metadata, "operation acceptance metadata"
        )
        receipt.accepted_at = utc_now()
        receipt.updated_at = receipt.accepted_at
        self.save(receipt)
        return receipt

    def record_poll(
        self,
        receipt: OperationReceipt,
        metadata: Mapping[str, Any] | None = None,
    ) -> OperationReceipt:
        if receipt.state != OperationState.ACCEPTED:
            raise OperationLedgerError("only accepted operations may be polled")
        receipt.poll_attempts += 1
        if metadata is not None:
            receipt.poll_metadata = _json_clone(metadata, "operation poll metadata")
        receipt.updated_at = utc_now()
        self.save(receipt)
        return receipt

    def record_result(
        self,
        receipt: OperationReceipt,
        result: StepResult,
        metadata: Mapping[str, Any] | None = None,
    ) -> OperationReceipt:
        if receipt.state != OperationState.ACCEPTED:
            raise OperationLedgerError("only accepted operations may record a result")
        receipt.result = result
        if metadata is not None:
            receipt.poll_metadata = _json_clone(metadata, "operation poll metadata")
        receipt.state = OperationState.RESULT_OBTAINED
        receipt.result_obtained_at = utc_now()
        receipt.updated_at = receipt.result_obtained_at
        self.save(receipt)
        return receipt

    def mark_committed(self, receipt: OperationReceipt) -> OperationReceipt:
        if receipt.state == OperationState.COMMITTED:
            return receipt
        if receipt.state != OperationState.RESULT_OBTAINED:
            raise OperationLedgerError("only obtained results may be committed")
        receipt.state = OperationState.COMMITTED
        receipt.committed_at = utc_now()
        receipt.updated_at = receipt.committed_at
        self.save(receipt)
        return receipt
