from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .external_ops import OperationAcceptance, OperationPollResult, ResumableAdapter
from .integration import (
    MEDIA_RENDER_CONTRACT_VERSION,
    MediaIntegrationError,
    _json_clone,
    _validate_media_result,
    validate_media_timeline_seed,
)
from .models import Artifact, StepResult
from .ports import StepContext


class ResumableOperationClient(Protocol):
    """Protocol-neutral async-operation client owned by the provider integration."""

    def submit_operation(
        self,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> str: ...

    def read_operation(self, external_operation_id: str) -> Mapping[str, Any]: ...


@dataclass
class GenericResumableMediaAdapter(ResumableAdapter):
    """Creator-side durable handoff around a provider-neutral async operation.

    The submitted payload remains the frozen media.render.v1 planning request.
    The async submit/read protocol is intentionally generic and is not a video2
    runtime contract.
    """

    client: ResumableOperationClient
    export_spec: Mapping[str, Any]
    output_path: str
    record_request_artifact: bool = True
    artifact_created_at: str | None = None
    name: str = "resumable-media-planning"

    def __post_init__(self) -> None:
        self.export_spec = _json_clone(self.export_spec, "exportSpec")
        if not isinstance(self.output_path, str) or not self.output_path:
            raise MediaIntegrationError("outputPath must be a non-empty string")

    def _timeline_artifact(self, context: StepContext) -> Artifact:
        timelines = [
            artifact
            for artifact in context.artifacts
            if artifact.kind == "media_timeline_v1"
        ]
        if len(timelines) != 1:
            raise MediaIntegrationError(
                "resumable media planning requires exactly one media_timeline_v1 seed"
            )
        return timelines[0]

    def prepare(self, context: StepContext) -> Mapping[str, Any]:
        timeline = self._timeline_artifact(context)
        return {
            "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
            "jobId": context.job_id,
            "timeline": validate_media_timeline_seed(timeline.metadata),
            "exportSpec": _json_clone(self.export_spec, "exportSpec"),
            "outputPath": self.output_path,
            "dryRun": True,
        }

    def submit(
        self,
        context: StepContext,
        request: Mapping[str, Any],
    ) -> OperationAcceptance:
        handle = self.client.submit_operation(
            request,
            idempotency_key=context.idempotency_key,
        )
        if not isinstance(handle, str) or not handle:
            raise MediaIntegrationError("resumable media submit returned no operation handle")
        return OperationAcceptance(
            external_operation_id=handle,
            metadata={
                "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
                "dryRun": True,
            },
        )

    def poll(
        self,
        context: StepContext,
        external_operation_id: str,
    ) -> OperationPollResult:
        status = self.client.read_operation(external_operation_id)
        if not isinstance(status, Mapping):
            raise MediaIntegrationError("resumable media operation status must be an object")
        state = status.get("state")
        if state in {"pending", "running"}:
            return OperationPollResult(
                done=False,
                metadata={"state": state},
            )
        if state == "failed":
            raise MediaIntegrationError(
                f"resumable media operation failed: {status.get('error', 'unknown')}"
            )
        if state != "succeeded":
            raise MediaIntegrationError(
                f"unsupported resumable media operation state: {state!r}"
            )
        result = status.get("result")
        if not isinstance(result, Mapping):
            raise MediaIntegrationError("succeeded media operation is missing result")
        validated = _validate_media_result(result, context.job_id)
        timeline = self._timeline_artifact(context)
        request = self.prepare(context)
        artifacts: list[Artifact] = []
        plan_parents: tuple[str, ...] = (timeline.id,)

        if self.record_request_artifact:
            request_digest = hashlib.sha256(
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:16]
            upstream = tuple(
                artifact.id
                for artifact in context.artifacts
                if artifact.kind in {"visual_asset", "voice"}
            )[-2:]
            kwargs = (
                {}
                if self.artifact_created_at is None
                else {"created_at": self.artifact_created_at}
            )
            request_artifact = Artifact(
                id=f"media-request-{request_digest}",
                kind="media_request",
                uri=f"memory://media-engine/{context.job_id}/request.json",
                producer=self.name,
                parents=(timeline.id, *upstream),
                metadata=dict(request),
                **kwargs,
            )
            artifacts.append(request_artifact)
            plan_parents = (timeline.id, request_artifact.id)

        fingerprint = validated["renderFingerprint"]
        digest = hashlib.sha256(
            f"{context.idempotency_key}|{fingerprint}".encode("utf-8")
        ).hexdigest()[:16]
        kwargs = (
            {}
            if self.artifact_created_at is None
            else {"created_at": self.artifact_created_at}
        )
        artifacts.append(
            Artifact(
                id=f"media-plan-{digest}",
                kind="media_plan",
                uri=f"memory://media-engine/{context.job_id}/plan.json",
                producer=self.name,
                parents=plan_parents,
                metadata=validated,
                **kwargs,
            )
        )
        return OperationPollResult(
            done=True,
            result=StepResult(
                tuple(artifacts),
                {
                    "provider": self.name,
                    "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
                    "dryRun": True,
                },
            ),
            metadata={"state": "succeeded"},
        )
