from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .adapters import RealPublishingDisabled
from .integration import MEDIA_RENDER_CONTRACT_VERSION
from .models import JobStage, StepResult
from .orchestrator import RetryableStepError
from .ports import Adapter, StepContext


class DuplicateRequestConflict(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


@dataclass
class _IdempotentFake:
    calls: list[dict[str, Any]] = field(default_factory=list)
    _cache: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)

    def _execute_once(
        self,
        key: str,
        request: Mapping[str, Any],
        factory: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        request_wire = _canonical(request)
        existing = self._cache.get(key)
        if existing is not None:
            previous_wire, response = existing
            if previous_wire != request_wire:
                raise DuplicateRequestConflict(f"idempotency conflict for {key}")
            return json.loads(_canonical(response))
        response = factory()
        self.calls.append(json.loads(request_wire))
        self._cache[key] = (request_wire, json.loads(_canonical(response)))
        return json.loads(_canonical(response))


class FakeRunway(_IdempotentFake):
    def generate_asset(self, *, prompt: str, idempotency_key: str) -> dict[str, Any]:
        request = {"prompt": prompt}
        return self._execute_once(
            idempotency_key,
            request,
            lambda: {
                "request": request,
                "asset_uri": f"sim://runway/{hashlib.sha256(prompt.encode()).hexdigest()[:12]}.mp4",
                "width": 720,
                "height": 1280,
            },
        )


class FakeDescript(_IdempotentFake):
    def synthesize_voice(self, *, script_uri: str, idempotency_key: str) -> dict[str, Any]:
        request = {"script_uri": script_uri}
        return self._execute_once(
            idempotency_key,
            {"operation": "voice", **request},
            lambda: {
                "request": request,
                "voice_uri": f"sim://descript/{hashlib.sha256(script_uri.encode()).hexdigest()[:12]}.wav",
            },
        )

    def edit_video(self, *, asset_uris: list[str], voice_uri: str, idempotency_key: str) -> dict[str, Any]:
        request = {"asset_uris": list(asset_uris), "voice_uri": voice_uri}
        return self._execute_once(
            idempotency_key,
            {"operation": "edit", **request},
            lambda: {
                "request": request,
                "edit_uri": f"sim://descript/{hashlib.sha256(_canonical(request).encode()).hexdigest()[:12]}.mp4",
            },
        )


class FakeMetricool(_IdempotentFake):
    def queue_post(self, *, manifest: dict[str, Any], idempotency_key: str, dry_run: bool) -> dict[str, Any]:
        if dry_run is not True:
            raise RealPublishingDisabled("simulator only permits queue dry-run")
        if manifest.get("action") != "queue_only":
            raise RealPublishingDisabled("simulator only permits queue_only manifests")
        request = {"manifest": manifest, "dry_run": True}
        return self._execute_once(
            idempotency_key,
            request,
            lambda: {
                "mode": "dry-run",
                "queued": True,
                "queue_id": f"queue-{hashlib.sha256(_canonical(manifest).encode()).hexdigest()[:12]}",
            },
        )


class FakeVidIQ(_IdempotentFake):
    def __init__(self, cycle: int = 1) -> None:
        super().__init__()
        self.cycle = cycle

    def research(self, *, topic: str, idempotency_key: str) -> dict[str, Any]:
        request = {"topic": topic}
        return self._execute_once(
            idempotency_key,
            {"operation": "research", **request},
            lambda: {
                "request": request,
                "query": f"{topic} cycle {self.cycle}",
                "signals": [
                    f"hook-{self.cycle}",
                    f"format-{(self.cycle % 3) + 1}",
                ],
            },
        )

    def analytics(self, *, topic: str, idempotency_key: str) -> dict[str, Any]:
        base_impressions = 1000 + (self.cycle - 1) * 250
        ctr = min(0.03 + self.cycle * 0.01, 0.09)
        views = 500 + self.cycle * 40
        clicks = int(round(base_impressions * ctr))
        watch_time = float(views * (11 + self.cycle * 2))
        event_a = {
            "event_id": f"cycle-{self.cycle}-a",
            "impressions": base_impressions,
            "views": views,
            "clicks": clicks,
            "watch_time_seconds": watch_time,
            "retention_auc": round(min(0.48 + self.cycle * 0.06, 0.8), 4),
        }
        event_b = {
            "event_id": f"cycle-{self.cycle}-b",
            "impressions": 200,
            "views": 100,
            "clicks": max(1, int(round(200 * ctr))),
            "watch_time_seconds": float(100 * (10 + self.cycle)),
            "retention_auc": round(min(0.45 + self.cycle * 0.05, 0.75), 4),
        }
        request = {"operation": "analytics", "topic": topic, "cycle": self.cycle}
        return self._execute_once(
            idempotency_key,
            request,
            lambda: {
                "request": {"topic": topic},
                "events": [event_a, dict(event_a), event_b],
            },
        )


class FakeMediaEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._cache: dict[str, dict[str, Any]] = {}

    def plan_render(self, request: dict[str, Any]) -> dict[str, Any]:
        expected = {"contractVersion", "jobId", "timeline", "exportSpec", "outputPath", "dryRun"}
        if set(request) != expected:
            raise ValueError("media.render.v1 request fields do not match frozen contract")
        if request["contractVersion"] != MEDIA_RENDER_CONTRACT_VERSION:
            raise ValueError("unsupported media contract")
        if request["dryRun"] is not True:
            raise ValueError("fake media engine accepts dryRun=true only")
        if not isinstance(request.get("timeline"), dict) or request["timeline"].get("version") != 1:
            raise ValueError("timeline.version must be 1")
        key = _canonical(request)
        if key not in self._cache:
            plan_input = {"timeline": request["timeline"], "exportSpec": request["exportSpec"]}
            fingerprint = hashlib.sha256(_canonical(plan_input).encode()).hexdigest()
            result = {
                "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
                "jobId": request["jobId"],
                "dryRun": True,
                "validation": {"ok": True, "timelineVersion": 1},
                "renderFingerprint": fingerprint,
                "command": ["ffmpeg", "-i", "<dry-run-plan>"],
            }
            self.calls.append(json.loads(key))
            self._cache[key] = result
        return json.loads(_canonical(self._cache[key]))


_STAGE_ALIASES = {
    JobStage.RESEARCH: "research",
    JobStage.SCRIPT: "script",
    JobStage.ASSETS: "assets",
    JobStage.VOICE: "voice",
    JobStage.EDIT: "media",
    JobStage.CRITIC: "critic",
    JobStage.PUBLISH_QUEUE: "queue",
    JobStage.ANALYTICS: "analytics",
}


@dataclass
class FailureInjectingAdapter(Adapter):
    wrapped: Adapter
    fail_attempts: Mapping[str, tuple[int, ...] | list[int] | set[int]]

    @property
    def name(self) -> str:
        return f"failure-injector:{self.wrapped.name}"

    def execute(self, context: StepContext) -> StepResult:
        alias = _STAGE_ALIASES.get(context.stage, context.stage.value)
        attempts = set(self.fail_attempts.get(alias, ()))
        if context.stage_attempt in attempts:
            raise RetryableStepError(
                f"injected transient failure stage={alias} attempt={context.stage_attempt}"
            )
        return self.wrapped.execute(context)


class FakeResumableMediaOperationClient:
    """Deterministic remote-operation fake with one side-effecting submit per key."""

    def __init__(
        self,
        *,
        pending_polls: int = 0,
        timeout_poll_numbers: set[int] | None = None,
    ) -> None:
        self.pending_polls = pending_polls
        self.timeout_poll_numbers = set(timeout_poll_numbers or ())
        self.submit_calls = 0
        self.poll_calls = 0
        self._by_key: dict[str, tuple[str, str]] = {}
        self._operations: dict[str, dict[str, Any]] = {}
        self._polls_by_handle: dict[str, int] = {}

    def submit_operation(
        self,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> str:
        request_wire = _canonical(request)
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            previous_wire, handle = existing
            if previous_wire != request_wire:
                raise DuplicateRequestConflict(
                    f"idempotency conflict for {idempotency_key}"
                )
            return handle

        handle = (
            "operation-"
            + hashlib.sha256(
                f"{idempotency_key}|{request_wire}".encode("utf-8")
            ).hexdigest()[:16]
        )
        plan_input = {
            "timeline": request["timeline"],
            "exportSpec": request["exportSpec"],
        }
        fingerprint = hashlib.sha256(
            _canonical(plan_input).encode("utf-8")
        ).hexdigest()
        result = {
            "contractVersion": MEDIA_RENDER_CONTRACT_VERSION,
            "jobId": request["jobId"],
            "dryRun": True,
            "validation": {
                "ok": True,
                "timelineVersion": request["timeline"]["version"],
            },
            "renderFingerprint": fingerprint,
            "command": ["ffmpeg", "-i", "<resumable-dry-run-plan>"],
        }
        self.submit_calls += 1
        self._by_key[idempotency_key] = (request_wire, handle)
        self._operations[handle] = {
            "request": json.loads(request_wire),
            "result": result,
        }
        self._polls_by_handle[handle] = 0
        return handle

    def read_operation(self, external_operation_id: str) -> Mapping[str, Any]:
        from .external_ops import OperationPollTimeout

        if external_operation_id not in self._operations:
            raise KeyError(external_operation_id)
        self.poll_calls += 1
        self._polls_by_handle[external_operation_id] += 1
        poll_number = self._polls_by_handle[external_operation_id]
        if poll_number in self.timeout_poll_numbers:
            raise OperationPollTimeout(
                f"simulated provider poll timeout #{poll_number}"
            )
        if poll_number <= self.pending_polls:
            return {"state": "pending"}
        return {
            "state": "succeeded",
            "result": json.loads(
                _canonical(self._operations[external_operation_id]["result"])
            ),
        }


class FakeMediaJobV1Client:
    """Exact-shape media.job.v1 fake with side-effect counters."""

    def __init__(
        self,
        *,
        pending_polls: int = 0,
        response_timeout_after_acceptance_once: bool = False,
        media_internal_retries: int = 0,
    ) -> None:
        self.pending_polls = pending_polls
        self.response_timeout_after_acceptance_once = (
            response_timeout_after_acceptance_once
        )
        self.media_internal_retries = media_internal_retries
        self.submit_requests = 0
        self.accepted_jobs = 0
        self.resume_calls = 0
        self.status_calls = 0
        self.cancel_calls = 0
        self._timeout_used = False
        self._by_key: dict[str, str] = {}
        self._jobs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _work_wire(request: Mapping[str, Any]) -> str:
        return _canonical(request)

    def _telemetry(self, job: Mapping[str, Any]) -> dict[str, Any]:
        succeeded = job["status"] == "succeeded"
        dry_run = job["request"]["dryRun"] is True
        live_succeeded = succeeded and not dry_run
        return {
            "planningMs": 1,
            "queueWaitMs": 0,
            "renderMs": 1 if live_succeeded else 0,
            "probeMs": 1 if live_succeeded else 0,
            "qaMs": 1 if live_succeeded else 0,
            "retries": self.media_internal_retries if live_succeeded else 0,
            "outputSize": 2048 if live_succeeded else None,
            "outputSha256": job["output_sha"] if live_succeeded else None,
            "sideEffects": {
                "executorInvocations": (
                    1 + self.media_internal_retries if live_succeeded else 0
                ),
                "probeInvocations": 1 if live_succeeded else 0,
                "qaEvaluations": 1 if live_succeeded else 0,
                "finalizeInvocations": 1 if live_succeeded else 0,
                "successfulFinalizations": 1 if live_succeeded else 0,
            },
            "protocol": {
                "submitCount": job["submit_count"],
                "duplicateSubmits": job["duplicate_submits"],
                "pollCount": job["poll_count"],
                "resumeCount": job["resume_count"],
                "cancelRequests": job["cancel_requests"],
                "reconciliations": 0,
            },
        }

    def _snapshot(self, job: Mapping[str, Any], *, duplicate=None) -> dict[str, Any]:
        status = job["status"]
        terminal = status in {"succeeded", "failed", "cancelled"}
        dry_run = job["request"]["dryRun"] is True
        final_artifact = None
        if status == "succeeded" and not dry_run:
            final_artifact = {
                "outputPath": job["request"]["outputPath"],
                "size": 2048,
                "sha256": job["output_sha"],
            }
        result = {
            "contractVersion": "media.job.v1",
            "accepted": True,
            "jobId": job["job_id"],
            "idempotencyKey": job["idempotency_key"],
            "status": status,
            "terminal": terminal,
            "dryRun": dry_run,
            "renderFingerprint": job["render_fingerprint"],
            "retryOwner": "media",
            "reconciliation": {"required": False},
            "failure": job.get("failure"),
            "finalArtifact": final_artifact,
            "telemetry": self._telemetry(job),
        }
        if duplicate is not None:
            result["duplicate"] = duplicate
        return result

    def handle(self, message: Mapping[str, Any]) -> Mapping[str, Any]:
        from .media_job_v1 import (
            MEDIA_JOB_CONTRACT_VERSION,
            MediaJobV1ProtocolError,
            MediaJobV1ResponseTimeout,
        )

        if not isinstance(message, Mapping):
            raise MediaJobV1ProtocolError("invalid_request", "message must be object")
        if message.get("contractVersion") != MEDIA_JOB_CONTRACT_VERSION:
            raise MediaJobV1ProtocolError(
                "invalid_request",
                "contractVersion must be media.job.v1",
            )
        action = message.get("action")

        if action == "submit":
            expected = {
                "contractVersion",
                "action",
                "idempotencyKey",
                "request",
            }
            if set(message) != expected:
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "submit fields must match media.job.v1 exactly",
                )
            key = message["idempotencyKey"]
            request = message["request"]
            if not isinstance(key, str) or not key:
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "submit requires idempotencyKey",
                )
            if not isinstance(request, Mapping):
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "submit.request must be object",
                )
            request_expected = {
                "contractVersion",
                "jobId",
                "timeline",
                "exportSpec",
                "outputPath",
                "dryRun",
            }
            if set(request) != request_expected:
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "media.render.v1 fields must match exactly",
                )
            if request["contractVersion"] != "media.render.v1":
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "request contractVersion must be media.render.v1",
                )
            job_id = request["jobId"]
            wire = self._work_wire(request)
            self.submit_requests += 1

            existing_job_id = self._by_key.get(key)
            if existing_job_id is not None:
                existing = self._jobs[existing_job_id]
                existing["submit_count"] += 1
                if existing["request_wire"] != wire or existing_job_id != job_id:
                    raise MediaJobV1ProtocolError(
                        "idempotency_conflict",
                        "idempotency key reused for different work",
                    )
                existing["duplicate_submits"] += 1
                return self._snapshot(existing, duplicate=True)

            if job_id in self._jobs:
                raise MediaJobV1ProtocolError(
                    "job_conflict",
                    "jobId reused for different work",
                )

            plan_input = {
                "timeline": request["timeline"],
                "exportSpec": request["exportSpec"],
            }
            fingerprint = hashlib.sha256(
                _canonical(plan_input).encode("utf-8")
            ).hexdigest()
            output_sha = hashlib.sha256(
                f"qa-final:{job_id}:{fingerprint}".encode("utf-8")
            ).hexdigest()
            job = {
                "job_id": job_id,
                "idempotency_key": key,
                "request": json.loads(wire),
                "request_wire": wire,
                "status": "queued",
                "render_fingerprint": fingerprint,
                "output_sha": output_sha,
                "submit_count": 1,
                "duplicate_submits": 0,
                "poll_count": 0,
                "resume_count": 0,
                "cancel_requests": 0,
            }
            self._jobs[job_id] = job
            self._by_key[key] = job_id
            self.accepted_jobs += 1

            if (
                self.response_timeout_after_acceptance_once
                and not self._timeout_used
            ):
                self._timeout_used = True
                raise MediaJobV1ResponseTimeout(
                    "simulated response timeout after Media accepted job"
                )
            return self._snapshot(job, duplicate=False)

        if action in {"status", "resume_or_poll"}:
            expected = {"contractVersion", "action", "jobId"}
            if set(message) != expected:
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    f"{action} fields must match media.job.v1 exactly",
                )
            job_id = message["jobId"]
            job = self._jobs.get(job_id)
            if job is None:
                raise MediaJobV1ProtocolError("not_found", "unknown Media jobId")
            if action == "status":
                self.status_calls += 1
                job["poll_count"] += 1
                return self._snapshot(job)
            self.resume_calls += 1
            job["resume_count"] += 1
            if job["status"] not in {"cancelled", "failed", "succeeded"}:
                if job["resume_count"] > self.pending_polls:
                    job["status"] = "succeeded"
                else:
                    job["status"] = "queued"
            return self._snapshot(job)

        if action == "cancel":
            expected = {
                "contractVersion",
                "action",
                "jobId",
                "reason",
            }
            if set(message) != expected:
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "cancel fields must match media.job.v1 exactly",
                )
            job_id = message["jobId"]
            job = self._jobs.get(job_id)
            if job is None:
                raise MediaJobV1ProtocolError("not_found", "unknown Media jobId")
            reason = message["reason"]
            if not isinstance(reason, str) or not reason:
                raise MediaJobV1ProtocolError(
                    "invalid_request",
                    "cancel reason must be non-empty",
                )
            self.cancel_calls += 1
            job["cancel_requests"] += 1
            if job["status"] not in {"succeeded", "failed"}:
                job["status"] = "cancelled"
            return self._snapshot(job)

        raise MediaJobV1ProtocolError(
            "invalid_request",
            f"unsupported media.job.v1 action: {action}",
        )
