from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Protocol

from .models import Artifact, StepResult
from .ports import Adapter, StepContext

GROWTH_FEEDBACK_CONTRACT_VERSION = "1.0"
MEDIA_RENDER_CONTRACT_VERSION = "media.render.v1"

_GROWTH_FIELDS = frozenset({"contract_version", "content_job_id", "channel_id", "video_id", "variant_id", "score", "uncertainty", "observed", "recommendations", "evidence_event_ids"})
_GROWTH_OBSERVED_FIELDS = frozenset({"ctr", "average_watch_time_seconds", "retention_auc"})


class IntegrationContractError(ValueError):
    pass


class GrowthFeedbackValidationError(IntegrationContractError):
    pass


class MediaIntegrationError(IntegrationContractError):
    pass


@dataclass(frozen=True)
class SeedArtifactInput:
    kind: str
    metadata: Mapping[str, Any]
    parents: tuple[str, ...] = ()
    created_at: str | None = None


class MediaEngineClient(Protocol):
    def plan_render(self, request: dict[str, Any]) -> Mapping[str, Any]: ...


def _json_clone(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise IntegrationContractError(f"{label} must be JSON-compatible") from exc
    return json.loads(encoded)


def _required_string(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise GrowthFeedbackValidationError(f"{field} must be a non-empty string")
    return value


def _bounded_number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GrowthFeedbackValidationError(f"{field} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise GrowthFeedbackValidationError(f"{field} must be a finite number")
    if minimum is not None and number < minimum:
        raise GrowthFeedbackValidationError(f"{field} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise GrowthFeedbackValidationError(f"{field} must be <= {maximum}")
    return number


def _string_array(value: Any, field: str, *, require_nonempty: bool) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise GrowthFeedbackValidationError(f"{field} must be an array of strings")
    if require_nonempty and not value:
        raise GrowthFeedbackValidationError(f"{field} must not be empty")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise GrowthFeedbackValidationError(f"{field} must contain only non-empty strings")
        result.append(item)
    return result


def validate_growth_feedback(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise GrowthFeedbackValidationError("CreatorFeedback payload must be an object")
    keys = set(payload.keys())
    missing = _GROWTH_FIELDS - keys
    extra = keys - _GROWTH_FIELDS
    if missing:
        raise GrowthFeedbackValidationError("CreatorFeedback payload missing fields: " + ", ".join(sorted(missing)))
    if extra:
        raise GrowthFeedbackValidationError("CreatorFeedback payload has unknown fields: " + ", ".join(sorted(extra)))
    version = payload["contract_version"]
    if not isinstance(version, str) or version != GROWTH_FEEDBACK_CONTRACT_VERSION:
        raise GrowthFeedbackValidationError(f"unsupported contract_version: {version!r}; expected '1.0'")
    observed = payload["observed"]
    if not isinstance(observed, Mapping):
        raise GrowthFeedbackValidationError("observed must be an object")
    observed_keys = set(observed.keys())
    if observed_keys != _GROWTH_OBSERVED_FIELDS:
        missing_observed = _GROWTH_OBSERVED_FIELDS - observed_keys
        extra_observed = observed_keys - _GROWTH_OBSERVED_FIELDS
        details: list[str] = []
        if missing_observed:
            details.append("missing " + ", ".join(sorted(missing_observed)))
        if extra_observed:
            details.append("unknown " + ", ".join(sorted(extra_observed)))
        raise GrowthFeedbackValidationError("observed fields invalid: " + "; ".join(details))
    normalized = {
        "contract_version": "1.0",
        "content_job_id": _required_string(payload["content_job_id"], "content_job_id"),
        "channel_id": _required_string(payload["channel_id"], "channel_id"),
        "video_id": _required_string(payload["video_id"], "video_id"),
        "variant_id": _required_string(payload["variant_id"], "variant_id", nullable=True),
        "score": _bounded_number(payload["score"], "score", minimum=0.0, maximum=1.0),
        "uncertainty": _bounded_number(payload["uncertainty"], "uncertainty", minimum=0.0, maximum=1.0),
        "observed": {
            "ctr": _bounded_number(observed["ctr"], "observed.ctr", minimum=0.0, maximum=1.0),
            "average_watch_time_seconds": _bounded_number(observed["average_watch_time_seconds"], "observed.average_watch_time_seconds", minimum=0.0),
            "retention_auc": _bounded_number(observed["retention_auc"], "observed.retention_auc", minimum=0.0, maximum=1.0),
        },
        "recommendations": _string_array(payload["recommendations"], "recommendations", require_nonempty=True),
        "evidence_event_ids": _string_array(payload["evidence_event_ids"], "evidence_event_ids", require_nonempty=False),
    }
    return _json_clone(normalized, "CreatorFeedback")


def validate_media_timeline_seed(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MediaIntegrationError("media_timeline_v1 metadata must be an object")
    if isinstance(payload.get("version"), bool) or payload.get("version") != 1:
        raise MediaIntegrationError("media_timeline_v1 requires timeline version 1")
    return _json_clone(payload, "media_timeline_v1 metadata")


def build_seed_artifact(job_id: str, seed: SeedArtifactInput, index: int) -> Artifact:
    if not isinstance(seed, SeedArtifactInput):
        raise IntegrationContractError("seed_artifacts must contain SeedArtifactInput values")
    if seed.kind == "growth_feedback":
        metadata = validate_growth_feedback(seed.metadata)
    elif seed.kind == "media_timeline_v1":
        metadata = validate_media_timeline_seed(seed.metadata)
    else:
        raise IntegrationContractError(f"unsupported seed kind: {seed.kind!r}")
    canonical = json.dumps({"job_id": job_id, "kind": seed.kind, "metadata": metadata, "parents": list(seed.parents)}, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    kwargs = {} if seed.created_at is None else {"created_at": seed.created_at}
    return Artifact(id=f"seed-{index}-{seed.kind}-{digest}", kind=seed.kind, uri=f"seed://{job_id}/{index}/{seed.kind}", producer="seed", parents=tuple(seed.parents), metadata=metadata, **kwargs)


def _validate_media_result(result: Mapping[str, Any], job_id: str) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise MediaIntegrationError("media.render.v1 result must be an object")
    if result.get("contractVersion") != MEDIA_RENDER_CONTRACT_VERSION:
        raise MediaIntegrationError("media result contractVersion must be media.render.v1")
    if result.get("jobId") != job_id:
        raise MediaIntegrationError("media result jobId does not match request")
    if result.get("dryRun") is not True:
        raise MediaIntegrationError("media result must confirm dryRun=true")
    validation = result.get("validation")
    if not isinstance(validation, Mapping) or validation.get("ok") is not True:
        raise MediaIntegrationError("media result validation must be ok")
    fingerprint = result.get("renderFingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise MediaIntegrationError("media result renderFingerprint is required")
    return _json_clone(result, "media.render.v1 result")


@dataclass
class MediaRenderPlanAdapter(Adapter):
    client: MediaEngineClient
    export_spec: Mapping[str, Any]
    output_path: str
    record_request_artifact: bool = False
    artifact_created_at: str | None = None
    name: str = "media-engine"

    def __post_init__(self) -> None:
        self.export_spec = _json_clone(self.export_spec, "exportSpec")
        if not isinstance(self.output_path, str) or not self.output_path:
            raise MediaIntegrationError("outputPath must be a non-empty string")

    def execute(self, context: StepContext) -> StepResult:
        timeline_artifacts = [a for a in context.artifacts if a.kind == "media_timeline_v1"]
        if len(timeline_artifacts) != 1:
            raise MediaIntegrationError("media planning requires exactly one seeded media_timeline_v1 artifact")
        timeline_artifact = timeline_artifacts[0]
        timeline = validate_media_timeline_seed(timeline_artifact.metadata)
        request = {
            "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
            "jobId": context.job_id,
            "timeline": timeline,
            "exportSpec": _json_clone(self.export_spec, "exportSpec"),
            "outputPath": self.output_path,
            "dryRun": True,
        }
        result = _validate_media_result(self.client.plan_render(request), context.job_id)
        fingerprint = result["renderFingerprint"]
        digest = hashlib.sha256(f"{context.idempotency_key}|{fingerprint}".encode()).hexdigest()[:16]
        parents = (timeline_artifact.id,)
        artifacts: list[Artifact] = []
        if self.record_request_artifact:
            request_digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
            upstream = tuple(a.id for a in context.artifacts if a.kind in {"visual_asset", "voice"})[-2:]
            request_kwargs = {} if self.artifact_created_at is None else {"created_at": self.artifact_created_at}
            request_artifact = Artifact(
                id=f"media-request-{request_digest}",
                kind="media_request",
                uri=f"memory://media-engine/{context.job_id}/request.json",
                producer=self.name,
                parents=(timeline_artifact.id, *upstream),
                metadata=request,
                **request_kwargs,
            )
            artifacts.append(request_artifact)
            parents = (timeline_artifact.id, request_artifact.id)
        plan_kwargs = {} if self.artifact_created_at is None else {"created_at": self.artifact_created_at}
        artifacts.append(
            Artifact(
                id=f"media-plan-{digest}",
                kind="media_plan",
                uri=f"memory://media-engine/{context.job_id}/plan.json",
                producer=self.name,
                parents=parents,
                metadata=result,
                **plan_kwargs,
            )
        )
        return StepResult(tuple(artifacts), {"provider": self.name, "contractVersion": MEDIA_RENDER_CONTRACT_VERSION, "dryRun": True})
