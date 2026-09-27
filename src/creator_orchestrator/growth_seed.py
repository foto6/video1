from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .integration import validate_growth_feedback
from .models import Artifact, utc_now

GROWTH_CREATOR_SEED_VERSION = "growth.creator_seed.v1"
GROWTH_FEEDBACK_BATCH_VERSION = "growth.feedback_batch.v1"
GROWTH_SEED_KIND = "growth_feedback_batch"
GROWTH_CAUSALITY_NOTICE = (
    "Observational analytics describe associations only; "
    "they do not establish causal effects."
)
CREATOR_GROWTH_SEED_LEDGER_VERSION = "creator.growth_seed_ledger.v1"


class GrowthCreatorSeedValidationError(ValueError):
    pass


class GrowthCreatorSeedConflictError(ValueError):
    pass


class GrowthCreatorSeedInjectedCrash(RuntimeError):
    pass


@dataclass(frozen=True)
class GrowthSeedConsumeReceipt:
    status: str
    sequence: int
    idempotency_key: str
    seed_digest: str
    artifact: Artifact


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise GrowthCreatorSeedValidationError(
            "growth creator seed must be JSON-compatible"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_iso(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise GrowthCreatorSeedValidationError(f"{field} must be a non-empty string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise GrowthCreatorSeedValidationError(f"{field} must be ISO-8601") from exc


def _feedback_wire(item: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    normalized = validate_growth_feedback(item)
    return normalized, _canonical_json(normalized)


def validate_growth_creator_seed(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly consume the frozen Growth growth.creator_seed.v1 handoff."""
    if not isinstance(payload, Mapping):
        raise GrowthCreatorSeedValidationError("creator seed must be an object")
    expected = {
        "handoff_version",
        "seed_kind",
        "idempotency_key",
        "batch_id",
        "campaign_id",
        "window",
        "payload_digest",
        "causal",
        "interpretation",
        "feedback",
    }
    if set(payload) != expected:
        raise GrowthCreatorSeedValidationError(
            "growth.creator_seed.v1 fields must match exactly"
        )
    if payload["handoff_version"] != GROWTH_CREATOR_SEED_VERSION:
        raise GrowthCreatorSeedValidationError(
            "handoff_version must be growth.creator_seed.v1"
        )
    if payload["seed_kind"] != GROWTH_SEED_KIND:
        raise GrowthCreatorSeedValidationError(
            "seed_kind must be growth_feedback_batch"
        )
    if payload["causal"] is not False:
        raise GrowthCreatorSeedValidationError(
            "Growth handoff must remain observational/non-causal"
        )
    if payload["interpretation"] != GROWTH_CAUSALITY_NOTICE:
        raise GrowthCreatorSeedValidationError(
            "Growth observational interpretation must be preserved exactly"
        )

    campaign_id = payload["campaign_id"]
    batch_id = payload["batch_id"]
    idempotency_key = payload["idempotency_key"]
    payload_digest = payload["payload_digest"]
    for value, field in (
        (campaign_id, "campaign_id"),
        (batch_id, "batch_id"),
        (idempotency_key, "idempotency_key"),
        (payload_digest, "payload_digest"),
    ):
        if not isinstance(value, str) or not value:
            raise GrowthCreatorSeedValidationError(
                f"{field} must be a non-empty string"
            )
    if idempotency_key != batch_id:
        raise GrowthCreatorSeedValidationError(
            "idempotency_key must equal the Growth batch_id"
        )

    window = payload["window"]
    if not isinstance(window, Mapping) or set(window) != {"label", "start", "end"}:
        raise GrowthCreatorSeedValidationError(
            "window must contain label/start/end exactly"
        )
    label = window["label"]
    if not isinstance(label, str) or not label:
        raise GrowthCreatorSeedValidationError("window.label must be non-empty")
    start = _parse_iso(window["start"], "window.start")
    end = _parse_iso(window["end"], "window.end")
    if start >= end:
        raise GrowthCreatorSeedValidationError("window.start must precede window.end")

    raw_feedback = payload["feedback"]
    if not isinstance(raw_feedback, list) or not raw_feedback:
        raise GrowthCreatorSeedValidationError("feedback must be a non-empty array")

    normalized_feedback: list[dict[str, Any]] = []
    feedback_wires: list[str] = []
    for item in raw_feedback:
        if not isinstance(item, Mapping):
            raise GrowthCreatorSeedValidationError(
                "feedback items must be CreatorFeedback 1.0 objects"
            )
        normalized, wire = _feedback_wire(item)
        normalized_feedback.append(normalized)
        feedback_wires.append(wire)

    content_job_ids = [item["content_job_id"] for item in normalized_feedback]
    if len(content_job_ids) != len(set(content_job_ids)):
        raise GrowthCreatorSeedValidationError(
            "feedback content_job_id values must be unique"
        )

    order = sorted(
        range(len(normalized_feedback)),
        key=lambda index: (
            normalized_feedback[index]["content_job_id"],
            normalized_feedback[index]["variant_id"] or "",
            normalized_feedback[index]["video_id"],
            feedback_wires[index],
        ),
    )
    if order != list(range(len(normalized_feedback))):
        raise GrowthCreatorSeedValidationError(
            "feedback array is not in canonical deterministic order"
        )

    expected_payload_digest = _sha256_text("\n".join(feedback_wires))
    if payload_digest != expected_payload_digest:
        raise GrowthCreatorSeedValidationError(
            "payload_digest does not match byte-stable CreatorFeedback 1.0 set"
        )

    identity_material = {
        "campaign_id": campaign_id,
        "window": {
            "label": label,
            "start": window["start"],
            "end": window["end"],
        },
        "evidence": [
            {
                "content_job_id": item["content_job_id"],
                "variant_id": item["variant_id"],
                "evidence_event_ids": sorted(item["evidence_event_ids"]),
            }
            for item in normalized_feedback
        ],
    }
    expected_batch_id = "fb1:" + _sha256_text(_canonical_json(identity_material))
    if batch_id != expected_batch_id:
        raise GrowthCreatorSeedValidationError(
            "batch_id does not match campaign/window/evidence identity"
        )

    return {
        "handoff_version": GROWTH_CREATOR_SEED_VERSION,
        "seed_kind": GROWTH_SEED_KIND,
        "idempotency_key": idempotency_key,
        "batch_id": batch_id,
        "campaign_id": campaign_id,
        "window": {
            "label": label,
            "start": window["start"],
            "end": window["end"],
        },
        "payload_digest": payload_digest,
        "causal": False,
        "interpretation": GROWTH_CAUSALITY_NOTICE,
        "feedback": normalized_feedback,
    }


class JsonGrowthSeedLedger:
    """Append-only exactly-once Creator consumer for Growth next-cycle seeds."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._rows: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise GrowthCreatorSeedConflictError(
                        f"invalid Creator Growth seed ledger JSON on line {line_number}"
                    ) from exc
                expected = {
                    "ledger_version",
                    "sequence",
                    "idempotency_key",
                    "seed_digest",
                    "artifact",
                    "status",
                }
                if not isinstance(row, Mapping) or set(row) != expected:
                    raise GrowthCreatorSeedConflictError(
                        "Creator Growth seed ledger row fields are invalid"
                    )
                if (
                    row["ledger_version"] != CREATOR_GROWTH_SEED_LEDGER_VERSION
                    or row["status"] != "committed"
                ):
                    raise GrowthCreatorSeedConflictError(
                        "unsupported Creator Growth seed ledger row"
                    )
                if row["sequence"] != len(self._rows) + 1:
                    raise GrowthCreatorSeedConflictError(
                        "Creator Growth seed ledger sequence is not contiguous"
                    )
                key = row["idempotency_key"]
                if not isinstance(key, str) or not key or key in self._rows:
                    raise GrowthCreatorSeedConflictError(
                        "duplicate or invalid Growth seed idempotency key"
                    )
                self._rows[key] = dict(row)

    @staticmethod
    def _artifact_from_row(row: Mapping[str, Any]) -> Artifact:
        item = row["artifact"]
        return Artifact(
            **{
                **item,
                "parents": tuple(item.get("parents", ())),
            }
        )

    def consume(
        self,
        payload: Mapping[str, Any],
        *,
        parents: Sequence[str] = (),
        artifact_created_at: str | None = None,
        fault: str | None = None,
    ) -> GrowthSeedConsumeReceipt:
        validated = validate_growth_creator_seed(payload)
        wire = _canonical_json(validated)
        seed_digest = _sha256_text(wire)
        key = validated["idempotency_key"]
        existing = self._rows.get(key)
        if existing is not None:
            if existing["seed_digest"] != seed_digest:
                raise GrowthCreatorSeedConflictError(
                    f"conflicting Growth seed for idempotency key {key}"
                )
            return GrowthSeedConsumeReceipt(
                status="duplicate",
                sequence=int(existing["sequence"]),
                idempotency_key=key,
                seed_digest=seed_digest,
                artifact=self._artifact_from_row(existing),
            )

        if fault not in {None, "after_commit"}:
            raise ValueError("fault must be None or 'after_commit'")

        artifact_kwargs = (
            {}
            if artifact_created_at is None
            else {"created_at": artifact_created_at}
        )
        artifact = Artifact(
            id="growth-seed-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            kind=GROWTH_SEED_KIND,
            uri=f"growth://creator-seed/{key}",
            producer="growth.creator_seed.v1",
            parents=tuple(parents),
            metadata=validated,
            **artifact_kwargs,
        )
        sequence = len(self._rows) + 1
        row = {
            "ledger_version": CREATOR_GROWTH_SEED_LEDGER_VERSION,
            "sequence": sequence,
            "idempotency_key": key,
            "seed_digest": seed_digest,
            "artifact": asdict(artifact),
            "status": "committed",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = _canonical_json(row)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._rows[key] = row

        if fault == "after_commit":
            raise GrowthCreatorSeedInjectedCrash(
                "injected crash after Creator Growth seed commit"
            )

        return GrowthSeedConsumeReceipt(
            status="committed",
            sequence=sequence,
            idempotency_key=key,
            seed_digest=seed_digest,
            artifact=artifact,
        )

    def receipt_for(self, idempotency_key: str) -> GrowthSeedConsumeReceipt | None:
        row = self._rows.get(idempotency_key)
        if row is None:
            return None
        return GrowthSeedConsumeReceipt(
            status=str(row["status"]),
            sequence=int(row["sequence"]),
            idempotency_key=idempotency_key,
            seed_digest=str(row["seed_digest"]),
            artifact=self._artifact_from_row(row),
        )

    @property
    def committed_count(self) -> int:
        return len(self._rows)
