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
