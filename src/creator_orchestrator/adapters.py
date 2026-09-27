from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from .models import Artifact, JobStage, StepResult
from .ports import Adapter, StepContext


class RealPublishingDisabled(RuntimeError):
    pass


class RunwayClient(Protocol):
    def generate_asset(self, *, prompt: str, idempotency_key: str) -> dict[str, Any]: ...


class DescriptClient(Protocol):
    def synthesize_voice(self, *, script_uri: str, idempotency_key: str) -> dict[str, Any]: ...
    def edit_video(self, *, asset_uris: list[str], voice_uri: str, idempotency_key: str) -> dict[str, Any]: ...


class MetricoolClient(Protocol):
    def queue_post(self, *, manifest: dict[str, Any], idempotency_key: str, dry_run: bool) -> dict[str, Any]: ...


class VidIQClient(Protocol):
    def research(self, *, topic: str, idempotency_key: str) -> dict[str, Any]: ...
    def analytics(self, *, topic: str, idempotency_key: str) -> dict[str, Any]: ...


def _artifact_id(provider: str, stage: JobStage, key: str) -> str:
    digest = hashlib.sha256(f"{provider}|{stage.value}|{key}".encode()).hexdigest()[:16]
    return f"{stage.value}-{digest}"


def _parents(context: StepContext) -> tuple[str, ...]:
    return tuple(a.id for a in context.artifacts[-4:])


@dataclass
class VidIQResearchAdapter(Adapter):
    client: VidIQClient | None = None
    name: str = "vidiq"

    def execute(self, context: StepContext) -> StepResult:
        payload = (
            self.client.research(topic=context.topic, idempotency_key=context.idempotency_key)
            if self.client else
            {"mode": "dry-run", "topic": context.topic}
        )
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind="research",
            uri=f"memory://vidiq/{context.job_id}/research.json",
            producer=self.name,
            parents=_parents(context),
            metadata=payload,
        )
        return StepResult((artifact,), {"provider": self.name})


@dataclass
class RunwayAssetAdapter(Adapter):
    client: RunwayClient | None = None
    name: str = "runway"

    def execute(self, context: StepContext) -> StepResult:
        prompt = f"Create visual assets for: {context.topic}"
        payload = (
            self.client.generate_asset(prompt=prompt, idempotency_key=context.idempotency_key)
            if self.client else
            {"mode": "dry-run", "prompt": prompt}
        )
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind="visual_asset",
            uri=f"memory://runway/{context.job_id}/assets.json",
            producer=self.name,
            parents=_parents(context),
            metadata=payload,
        )
        return StepResult((artifact,), {"provider": self.name})


@dataclass
class DescriptVoiceAdapter(Adapter):
    client: DescriptClient | None = None
    name: str = "descript"

    def execute(self, context: StepContext) -> StepResult:
        script = next((a for a in reversed(context.artifacts) if a.kind == "script"), None)
        script_uri = script.uri if script else f"memory://{context.job_id}/script"
        payload = (
            self.client.synthesize_voice(script_uri=script_uri, idempotency_key=context.idempotency_key)
            if self.client else
            {"mode": "dry-run", "script_uri": script_uri}
        )
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind="voice",
            uri=f"memory://descript/{context.job_id}/voice.wav",
            producer=self.name,
            parents=_parents(context),
            metadata=payload,
        )
        return StepResult((artifact,), {"provider": self.name})


@dataclass
class DescriptEditAdapter(Adapter):
    client: DescriptClient | None = None
    name: str = "descript"

    def execute(self, context: StepContext) -> StepResult:
        assets = [a.uri for a in context.artifacts if a.kind == "visual_asset"]
        voice = next((a.uri for a in reversed(context.artifacts) if a.kind == "voice"), "")
        payload = (
            self.client.edit_video(asset_uris=assets, voice_uri=voice, idempotency_key=context.idempotency_key)
            if self.client else
            {"mode": "dry-run", "asset_uris": assets, "voice_uri": voice}
        )
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind="edit",
            uri=f"memory://descript/{context.job_id}/edit.mp4",
            producer=self.name,
            parents=_parents(context),
            metadata=payload,
        )
        return StepResult((artifact,), {"provider": self.name})


@dataclass
class MetricoolPublishQueueAdapter(Adapter):
    client: MetricoolClient | None = None
    dry_run: bool = True
    name: str = "metricool"

    def execute(self, context: StepContext) -> StepResult:
        if not self.dry_run:
            raise RealPublishingDisabled("real publishing is disabled; queue/dry-run only")
        manifest = {
            "job_id": context.job_id,
            "topic": context.topic,
            "artifact_ids": [a.id for a in context.artifacts],
            "action": "queue_only",
        }
        payload = (
            self.client.queue_post(
                manifest=manifest,
                idempotency_key=context.idempotency_key,
                dry_run=True,
            )
            if self.client else
            {"mode": "dry-run", "queued": True}
        )
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind="publish_manifest",
            uri=f"memory://metricool/{context.job_id}/publish-queue.json",
            producer=self.name,
            parents=_parents(context),
            metadata={**manifest, **payload},
        )
        return StepResult((artifact,), {"provider": self.name, "dry_run": True})


@dataclass
class VidIQAnalyticsAdapter(Adapter):
    client: VidIQClient | None = None
    name: str = "vidiq"

    def execute(self, context: StepContext) -> StepResult:
        payload = (
            self.client.analytics(topic=context.topic, idempotency_key=context.idempotency_key)
            if self.client else
            {"mode": "dry-run", "feedback_available": False}
        )
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind="analytics_feedback",
            uri=f"memory://vidiq/{context.job_id}/analytics.json",
            producer=self.name,
            parents=_parents(context),
            metadata=payload,
        )
        return StepResult((artifact,), {"provider": self.name})


@dataclass
class DeterministicTextAdapter(Adapter):
    """Provider-neutral adapter for idea/script/critic stages in the MVP."""

    name: str
    kind: str

    def execute(self, context: StepContext) -> StepResult:
        artifact = Artifact(
            id=_artifact_id(self.name, context.stage, context.idempotency_key),
            kind=self.kind,
            uri=f"memory://{self.name}/{context.job_id}/{context.stage.value}.json",
            producer=self.name,
            parents=_parents(context),
            metadata={"mode": "deterministic-mvp", "topic": context.topic},
        )
        return StepResult((artifact,), {"provider": self.name})
