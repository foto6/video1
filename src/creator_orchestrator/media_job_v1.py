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
    validate_media_timeline_seed,
)
from .models import Artifact, StepResult
from .ports import StepContext

MEDIA_JOB_CONTRACT_VERSION = "media.job.v1"


class MediaJobV1ProtocolError(MediaIntegrationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class MediaJobV1ResponseTimeout(TimeoutError):
    """Caller-side response timeout where Media acceptance may already exist."""


class MediaJobV1Client(Protocol):
    def handle(self, message: Mapping[str, Any]) -> Mapping[str, Any]: ...


_BASE_RESPONSE_FIELDS = {
    "contractVersion",
    "accepted",
    "jobId",
    "idempotencyKey",
    "status",
    "terminal",
    "dryRun",
    "renderFingerprint",
    "retryOwner",
    "reconciliation",
    "failure",
    "finalArtifact",
    "telemetry",
}
_TELEMETRY_FIELDS = {
    "planningMs",
    "queueWaitMs",
    "renderMs",
    "probeMs",
    "qaMs",
    "retries",
    "outputSize",
    "outputSha256",
    "sideEffects",
    "protocol",
}
_SIDE_EFFECT_FIELDS = {
    "executorInvocations",
    "probeInvocations",
    "qaEvaluations",
    "finalizeInvocations",
    "successfulFinalizations",
}
_PROTOCOL_TELEMETRY_FIELDS = {
    "submitCount",
    "duplicateSubmits",
    "pollCount",
    "resumeCount",
    "cancelRequests",
    "reconciliations",
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _strict_media_render_request(request: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "contractVersion",
        "jobId",
        "timeline",
        "exportSpec",
        "outputPath",
        "dryRun",
    }
    if not isinstance(request, Mapping) or set(request) != expected:
        raise MediaJobV1ProtocolError(
            "invalid_request",
            "media.render.v1 request fields must match exactly",
        )
    if request["contractVersion"] != MEDIA_RENDER_CONTRACT_VERSION:
        raise MediaJobV1ProtocolError(
            "invalid_request",
            "submit.request contractVersion must be media.render.v1",
        )
    job_id = request["jobId"]
    output_path = request["outputPath"]
    dry_run = request["dryRun"]
    if not isinstance(job_id, str) or not job_id:
        raise MediaJobV1ProtocolError("invalid_request", "request.jobId is required")
    if not isinstance(output_path, str) or not output_path:
        raise MediaJobV1ProtocolError("invalid_request", "request.outputPath is required")
    if not isinstance(dry_run, bool):
        raise MediaJobV1ProtocolError("invalid_request", "request.dryRun must be boolean")
    timeline = validate_media_timeline_seed(request["timeline"])
    export_spec = _json_clone(request["exportSpec"], "exportSpec")
    if not isinstance(export_spec, dict):
        raise MediaJobV1ProtocolError("invalid_request", "exportSpec must be an object")
    return {
        "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
        "jobId": job_id,
        "timeline": timeline,
        "exportSpec": export_spec,
        "outputPath": output_path,
        "dryRun": dry_run,
    }


def validate_media_job_v1_response(
    payload: Mapping[str, Any],
    *,
    expected_job_id: str,
    expected_idempotency_key: str,
    expected_dry_run: bool,
    submit_response: bool,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MediaJobV1ProtocolError("invalid_response", "Media response must be an object")
    expected_fields = set(_BASE_RESPONSE_FIELDS)
    if submit_response:
        expected_fields.add("duplicate")
    if set(payload) != expected_fields:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "media.job.v1 response fields do not match producer v1",
        )
    if payload["contractVersion"] != MEDIA_JOB_CONTRACT_VERSION:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "response contractVersion must be media.job.v1",
        )
    if payload["accepted"] is not True:
        raise MediaJobV1ProtocolError("invalid_response", "Media job was not accepted")
    if payload["jobId"] != expected_job_id:
        raise MediaJobV1ProtocolError("invalid_response", "Media jobId changed")
    if payload["idempotencyKey"] != expected_idempotency_key:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "Media idempotencyKey changed",
        )
    if payload["dryRun"] is not expected_dry_run:
        raise MediaJobV1ProtocolError("invalid_response", "Media dryRun changed")
    if payload["retryOwner"] != "media":
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "Media must remain retry owner",
        )
    if not isinstance(payload["status"], str) or not payload["status"]:
        raise MediaJobV1ProtocolError("invalid_response", "Media status is invalid")
    if not isinstance(payload["terminal"], bool):
        raise MediaJobV1ProtocolError("invalid_response", "Media terminal is invalid")
    fingerprint = payload["renderFingerprint"]
    if not isinstance(fingerprint, str) or not fingerprint:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "renderFingerprint is required",
        )

    reconciliation = payload["reconciliation"]
    if not isinstance(reconciliation, Mapping):
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "reconciliation must be an object",
        )
    if reconciliation.get("required") is False:
        if set(reconciliation) != {"required"}:
            raise MediaJobV1ProtocolError(
                "invalid_response",
                "non-required reconciliation fields are invalid",
            )
    elif reconciliation.get("required") is True:
        if set(reconciliation) != {"required", "reason"}:
            raise MediaJobV1ProtocolError(
                "invalid_response",
                "required reconciliation must include reason exactly",
            )
    else:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "reconciliation.required must be boolean",
        )

    telemetry = payload["telemetry"]
    if not isinstance(telemetry, Mapping) or set(telemetry) != _TELEMETRY_FIELDS:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "telemetry fields do not match media.job.v1",
        )
    side_effects = telemetry["sideEffects"]
    protocol = telemetry["protocol"]
    if not isinstance(side_effects, Mapping) or set(side_effects) != _SIDE_EFFECT_FIELDS:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "sideEffects telemetry fields do not match media.job.v1",
        )
    if not isinstance(protocol, Mapping) or set(protocol) != _PROTOCOL_TELEMETRY_FIELDS:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "protocol telemetry fields do not match media.job.v1",
        )
    if submit_response and not isinstance(payload["duplicate"], bool):
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "submit response duplicate must be boolean",
        )

    final_artifact = payload["finalArtifact"]
    if payload["status"] == "succeeded" and not expected_dry_run:
        if not isinstance(final_artifact, Mapping) or set(final_artifact) != {
            "outputPath",
            "size",
            "sha256",
        }:
            raise MediaJobV1ProtocolError(
                "invalid_response",
                "succeeded live Media job requires exact finalArtifact",
            )
        if (
            not isinstance(final_artifact["size"], int)
            or isinstance(final_artifact["size"], bool)
            or final_artifact["size"] <= 0
        ):
            raise MediaJobV1ProtocolError(
                "invalid_response",
                "finalArtifact.size must be positive",
            )
        sha = final_artifact["sha256"]
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(char not in "0123456789abcdef" for char in sha)
        ):
            raise MediaJobV1ProtocolError(
                "invalid_response",
                "finalArtifact.sha256 must be lowercase SHA-256",
            )
    elif final_artifact is not None:
        raise MediaJobV1ProtocolError(
            "invalid_response",
            "finalArtifact is allowed only for succeeded live jobs",
        )

    return _json_clone(payload, "media.job.v1 response")


@dataclass
class MediaJobV1ResumableAdapter(ResumableAdapter):
    """Concrete Creator consumer for the frozen Media media.job.v1 protocol."""

    client: MediaJobV1Client
    export_spec: Mapping[str, Any]
    output_path: str
    dry_run: bool = False
    logical_job_id: str | None = None
    artifact_created_at: str | None = None
    name: str = "media-job-v1"

    def __post_init__(self) -> None:
        self.export_spec = _json_clone(self.export_spec, "exportSpec")
        if not isinstance(self.output_path, str) or not self.output_path:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "outputPath must be a non-empty string",
            )
        if self.logical_job_id is not None and (
            not isinstance(self.logical_job_id, str) or not self.logical_job_id
        ):
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "logical_job_id must be non-empty when provided",
            )
        if not isinstance(self.dry_run, bool):
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "dry_run must be boolean",
            )

    def _timeline_artifact(self, context: StepContext) -> Artifact:
        timelines = [
            artifact
            for artifact in context.artifacts
            if artifact.kind == "media_timeline_v1"
        ]
        if len(timelines) != 1:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "media.job.v1 requires exactly one media_timeline_v1 seed",
            )
        return timelines[0]

    def _job_id(self, context: StepContext) -> str:
        if self.logical_job_id is not None:
            return self.logical_job_id
        suffix = context.idempotency_key[:16]
        return f"creator-{context.job_id}-{context.stage.value}-{suffix}"

    @staticmethod
    def _idempotency_key(context: StepContext) -> str:
        return f"creator:{context.idempotency_key}"

    def prepare(self, context: StepContext) -> Mapping[str, Any]:
        timeline = self._timeline_artifact(context)
        render_request = _strict_media_render_request(
            {
                "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
                "jobId": self._job_id(context),
                "timeline": validate_media_timeline_seed(timeline.metadata),
                "exportSpec": self.export_spec,
                "outputPath": self.output_path,
                "dryRun": self.dry_run,
            }
        )
        return {
            "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
            "action": "submit",
            "idempotencyKey": self._idempotency_key(context),
            "request": render_request,
        }

    def submit(
        self,
        context: StepContext,
        request: Mapping[str, Any],
    ) -> OperationAcceptance:
        expected = {"contractVersion", "action", "idempotencyKey", "request"}
        if set(request) != expected:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "media.job.v1 submit fields must match exactly",
            )
        render_request = _strict_media_render_request(request["request"])
        job_id = render_request["jobId"]
        idempotency_key = self._idempotency_key(context)
        if request["contractVersion"] != MEDIA_JOB_CONTRACT_VERSION:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "submit contractVersion must be media.job.v1",
            )
        if request["action"] != "submit":
            raise MediaJobV1ProtocolError("invalid_request", "submit action is required")
        if request["idempotencyKey"] != idempotency_key:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "Creator stage idempotency changed before submit",
            )
        try:
            response = self.client.handle(request)
        except MediaJobV1ResponseTimeout:
            # Creator supplied the stable Media jobId. Acceptance may have happened,
            # so persist that same handle and resume/poll it rather than resubmitting.
            return OperationAcceptance(
                external_operation_id=job_id,
                metadata={
                    "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
                    "idempotencyKey": idempotency_key,
                    "responseTimeoutAfterPossibleAcceptance": True,
                    "retryOwner": "media",
                },
            )

        validated = validate_media_job_v1_response(
            response,
            expected_job_id=job_id,
            expected_idempotency_key=idempotency_key,
            expected_dry_run=self.dry_run,
            submit_response=True,
        )
        return OperationAcceptance(
            external_operation_id=validated["jobId"],
            metadata={
                "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
                "idempotencyKey": idempotency_key,
                "duplicate": validated["duplicate"],
                "renderFingerprint": validated["renderFingerprint"],
                "retryOwner": "media",
            },
        )

    def poll(
        self,
        context: StepContext,
        external_operation_id: str,
    ) -> OperationPollResult:
        message = {
            "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
            "action": "resume_or_poll",
            "jobId": external_operation_id,
        }
        response = validate_media_job_v1_response(
            self.client.handle(message),
            expected_job_id=external_operation_id,
            expected_idempotency_key=self._idempotency_key(context),
            expected_dry_run=self.dry_run,
            submit_response=False,
        )
        metadata = {
            "status": response["status"],
            "terminal": response["terminal"],
            "reconciliation": response["reconciliation"],
            "retryOwner": response["retryOwner"],
            "telemetry": response["telemetry"],
        }
        if not response["terminal"]:
            return OperationPollResult(done=False, metadata=metadata)
        if response["status"] == "cancelled":
            raise MediaJobV1ProtocolError(
                "cancelled",
                f"Media job {external_operation_id} was cancelled",
            )
        if response["status"] != "succeeded":
            failure = response["failure"]
            code = failure.get("code", "media_failed") if isinstance(failure, Mapping) else "media_failed"
            raise MediaJobV1ProtocolError(
                code,
                f"Media job {external_operation_id} failed",
            )

        timeline = self._timeline_artifact(context)
        submit_message = self.prepare(context)
        request_digest = hashlib.sha256(
            _canonical(submit_message).encode("utf-8")
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
            id=f"media-job-request-{request_digest}",
            kind="media_job_request",
            uri=f"media-job://{external_operation_id}/submit",
            producer=self.name,
            parents=(timeline.id, *upstream),
            metadata=dict(submit_message),
            **kwargs,
        )
        fingerprint = response["renderFingerprint"]
        if self.dry_run:
            final = Artifact(
                id="media-plan-"
                + hashlib.sha256(
                    f"{context.idempotency_key}|{fingerprint}".encode("utf-8")
                ).hexdigest()[:16],
                kind="media_plan",
                uri=f"media-job://{external_operation_id}/plan",
                producer=self.name,
                parents=(request_artifact.id,),
                metadata=response,
                **kwargs,
            )
        else:
            final_artifact = response["finalArtifact"]
            final = Artifact(
                id="media-final-"
                + hashlib.sha256(
                    f"{external_operation_id}|{final_artifact['sha256']}".encode("utf-8")
                ).hexdigest()[:16],
                kind="media_final_artifact",
                uri=final_artifact["outputPath"],
                producer=self.name,
                parents=(request_artifact.id,),
                metadata={
                    "jobId": response["jobId"],
                    "idempotencyKey": response["idempotencyKey"],
                    "renderFingerprint": fingerprint,
                    "retryOwner": "media",
                    "qaPassed": True,
                    "finalArtifact": final_artifact,
                    "telemetry": response["telemetry"],
                },
                **kwargs,
            )
        return OperationPollResult(
            done=True,
            result=StepResult(
                artifacts=(request_artifact, final),
                metadata={
                    "provider": self.name,
                    "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
                    "retryOwner": "media",
                    "dryRun": self.dry_run,
                },
            ),
            metadata=metadata,
        )

    def status(
        self,
        context: StepContext,
        external_operation_id: str,
    ) -> dict[str, Any]:
        message = {
            "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
            "action": "status",
            "jobId": external_operation_id,
        }
        return validate_media_job_v1_response(
            self.client.handle(message),
            expected_job_id=external_operation_id,
            expected_idempotency_key=self._idempotency_key(context),
            expected_dry_run=self.dry_run,
            submit_response=False,
        )

    def cancel(
        self,
        context: StepContext,
        external_operation_id: str,
        *,
        reason: str = "creator_cancelled",
    ) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "cancel reason must be non-empty",
            )
        message = {
            "contractVersion": MEDIA_JOB_CONTRACT_VERSION,
            "action": "cancel",
            "jobId": external_operation_id,
            "reason": reason,
        }
        return validate_media_job_v1_response(
            self.client.handle(message),
            expected_job_id=external_operation_id,
            expected_idempotency_key=self._idempotency_key(context),
            expected_dry_run=self.dry_run,
            submit_response=False,
        )
