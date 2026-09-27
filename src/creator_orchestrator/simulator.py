from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .adapters import RealPublishingDisabled
from .integration import MediaRenderPlanAdapter, SeedArtifactInput, validate_growth_feedback
from .lineage import LineageReport, validate_artifact_dag
from .models import Artifact, JobStage, JobState, StepResult
from .orchestrator import JsonJobStore, Orchestrator, RetryPolicy
from .ports import Adapter, StepContext
from .sim_fakes import (
    FailureInjectingAdapter,
    FakeDescript,
    FakeMediaEngine,
    FakeMetricool,
    FakeRunway,
    FakeVidIQ,
)

CAMPAIGN_CONTRACT_VERSION = "creator.campaign.sim.v2"
_FAILURE_STAGES = frozenset(
    {"research", "script", "assets", "voice", "media", "critic", "queue", "analytics"}
)
_REVISION_STAGES = {
    "research": JobStage.RESEARCH,
    "idea": JobStage.IDEA,
    "script": JobStage.SCRIPT,
    "assets": JobStage.ASSETS,
    "voice": JobStage.VOICE,
    "media": JobStage.EDIT,
}
_STAGE_ALIAS = {
    "research": "research",
    "idea": "idea",
    "script": "script",
    "assets": "assets",
    "voice": "voice",
    "edit": "media",
    "critic": "critic",
    "publish_queue": "queue",
    "analytics": "analytics",
}


class CampaignConfigError(ValueError):
    pass


class CampaignSimulationError(RuntimeError):
    pass


class DuplicateAnalyticsEventConflict(CampaignSimulationError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _clone(value: Any) -> Any:
    return json.loads(_canonical(value))


def _config_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _safe_output_template(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise CampaignConfigError("outputPathTemplate must be a non-empty string")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        raise CampaignConfigError("outputPathTemplate must remain a relative simulation path")
    if any(part == ".." for part in normalized.split("/")):
        raise CampaignConfigError("outputPathTemplate may not traverse parent directories")
    allowed = {"campaign_id", "cycle", "job_id"}
    import string

    for _, field_name, _, _ in string.Formatter().parse(value):
        if field_name and field_name not in allowed:
            raise CampaignConfigError(f"unsupported outputPathTemplate field: {field_name}")
    return value


@dataclass(frozen=True)
class CampaignConfig:
    campaign_id: str
    topic: str
    cycles: int
    max_attempts_per_stage: int
    max_critic_revisions: int
    revision_stage: str
    critic_rejects_by_cycle: dict[int, int]
    failures_by_cycle: dict[int, dict[str, tuple[int, ...]]]
    timeline: dict[str, Any]
    export_spec: dict[str, Any]
    output_path_template: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CampaignConfig":
        if not isinstance(payload, Mapping):
            raise CampaignConfigError("campaign fixture must be an object")
        raw = _clone(payload)
        allowed_top = {"contractVersion", "campaignId", "topic", "cycles", "maxAttemptsPerStage", "maxCriticRevisions", "critic", "failures", "media"}
        unknown_top = set(raw) - allowed_top
        if unknown_top:
            raise CampaignConfigError("campaign fixture contains unknown fields: " + ", ".join(sorted(unknown_top)))
        if raw.get("contractVersion") != CAMPAIGN_CONTRACT_VERSION:
            raise CampaignConfigError(
                f"contractVersion must be {CAMPAIGN_CONTRACT_VERSION}"
            )
        campaign_id = raw.get("campaignId")
        topic = raw.get("topic")
        if not isinstance(campaign_id, str) or not campaign_id:
            raise CampaignConfigError("campaignId is required")
        if not isinstance(topic, str) or not topic:
            raise CampaignConfigError("topic is required")
        cycles = raw.get("cycles")
        max_attempts = raw.get("maxAttemptsPerStage")
        max_revisions = raw.get("maxCriticRevisions")
        if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
            raise CampaignConfigError("cycles must be >= 1")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise CampaignConfigError("maxAttemptsPerStage must be >= 1")
        if isinstance(max_revisions, bool) or not isinstance(max_revisions, int) or max_revisions < 0:
            raise CampaignConfigError("maxCriticRevisions must be >= 0")
        critic_raw = raw.get("critic", {})
        if not isinstance(critic_raw, Mapping) or set(critic_raw) - {"revisionStage", "rejectsByCycle"}:
            raise CampaignConfigError("critic contains unsupported fields")
        revision_stage = critic_raw.get("revisionStage", "script")
        if revision_stage not in _REVISION_STAGES:
            raise CampaignConfigError("critic.revisionStage must target a pre-critic stage")
        reject_raw = critic_raw.get("rejectsByCycle", {})
        if not isinstance(reject_raw, Mapping):
            raise CampaignConfigError("critic.rejectsByCycle must be an object")
        rejects: dict[int, int] = {}
        for key, value in reject_raw.items():
            try:
                cycle = int(key)
            except (TypeError, ValueError) as exc:
                raise CampaignConfigError("critic cycle keys must be integers") from exc
            if cycle < 1 or cycle > cycles or isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CampaignConfigError("critic reject counts must be non-negative and in range")
            rejects[cycle] = value

        failures_raw = raw.get("failures", {})
        if not isinstance(failures_raw, Mapping):
            raise CampaignConfigError("failures must be an object")
        failures: dict[int, dict[str, tuple[int, ...]]] = {}
        for cycle_key, stage_map in failures_raw.items():
            try:
                cycle = int(cycle_key)
            except (TypeError, ValueError) as exc:
                raise CampaignConfigError("failure cycle keys must be integers") from exc
            if cycle < 1 or cycle > cycles or not isinstance(stage_map, Mapping):
                raise CampaignConfigError("failure cycle must be in range and map stages")
            normalized: dict[str, tuple[int, ...]] = {}
            for stage, attempts in stage_map.items():
                if stage not in _FAILURE_STAGES or not isinstance(attempts, list):
                    raise CampaignConfigError(f"invalid failure stage: {stage}")
                values: list[int] = []
                for attempt in attempts:
                    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= max_attempts:
                        raise CampaignConfigError("failure attempts must fit maxAttemptsPerStage")
                    values.append(attempt)
                normalized[stage] = tuple(sorted(set(values)))
            failures[cycle] = normalized

        media_raw = raw.get("media", {})
        if not isinstance(media_raw, Mapping) or set(media_raw) - {"timeline", "exportSpec", "outputPathTemplate"}:
            raise CampaignConfigError("media contains unsupported fields")
        timeline = media_raw.get("timeline")
        export_spec = media_raw.get("exportSpec")
        output_template = _safe_output_template(media_raw.get("outputPathTemplate"))
        if not isinstance(timeline, Mapping) or timeline.get("version") != 1:
            raise CampaignConfigError("media.timeline must be a caller-supplied timeline version 1")
        if not isinstance(export_spec, Mapping):
            raise CampaignConfigError("media.exportSpec must be an object")

        return cls(
            campaign_id=campaign_id,
            topic=topic,
            cycles=cycles,
            max_attempts_per_stage=max_attempts,
            max_critic_revisions=max_revisions,
            revision_stage=revision_stage,
            critic_rejects_by_cycle=rejects,
            failures_by_cycle=failures,
            timeline=_clone(timeline),
            export_spec=_clone(export_spec),
            output_path_template=output_template,
            raw=raw,
        )

    def output_path(self, cycle: int, job_id: str) -> str:
        return self.output_path_template.format(
            campaign_id=self.campaign_id,
            cycle=f"{cycle:02d}",
            job_id=job_id,
        )


@dataclass
class CampaignState:
    campaign_id: str
    config_digest: str
    status: str = "running"
    current_cycle: int = 1
    cycle_job_ids: dict[str, str] = field(default_factory=dict)
    completed_cycles: list[int] = field(default_factory=list)
    feedback_by_cycle: dict[str, dict[str, Any]] = field(default_factory=dict)
    handled_critic_ids: list[str] = field(default_factory=list)
    event_digest_by_id: dict[str, str] = field(default_factory=dict)
    duplicate_events_suppressed: int = 0
    last_error: str | None = None
    report_artifact: Artifact | None = None


class JsonCampaignStore:
    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, campaign_id: str) -> Path:
        safe = "".join(c for c in campaign_id if c.isalnum() or c in "-_.")
        if not safe or safe != campaign_id:
            raise ValueError("unsafe campaign id")
        return self.directory / f"{safe}.json"

    def exists(self, campaign_id: str) -> bool:
        return self._path(campaign_id).exists()

    def save(self, state: CampaignState) -> None:
        payload = asdict(state)
        path = self._path(state.campaign_id)
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

    def load(self, campaign_id: str) -> CampaignState:
        data = json.loads(self._path(campaign_id).read_text(encoding="utf-8"))
        report = data.get("report_artifact")
        if report is not None:
            data["report_artifact"] = Artifact(
                **{**report, "parents": tuple(report.get("parents", ()))}
            )
        return CampaignState(**data)


_SIM_BASE = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)
_STAGE_OFFSETS = {
    JobStage.RESEARCH: 0,
    JobStage.IDEA: 10,
    JobStage.SCRIPT: 20,
    JobStage.ASSETS: 30,
    JobStage.VOICE: 40,
    JobStage.EDIT: 50,
    JobStage.CRITIC: 60,
    JobStage.PUBLISH_QUEUE: 70,
    JobStage.ANALYTICS: 80,
}


def _sim_time(cycle: int, stage: JobStage, ordinal: int = 0) -> str:
    value = _SIM_BASE + timedelta(days=cycle - 1, minutes=_STAGE_OFFSETS[stage], seconds=ordinal)
    return value.isoformat()


def _artifact_id(prefix: str, context: StepContext, suffix: str = "") -> str:
    raw = f"{prefix}|{context.idempotency_key}|{suffix}"
    return f"{prefix}-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _latest(context: StepContext, kind: str) -> Artifact | None:
    return next((a for a in reversed(context.artifacts) if a.kind == kind), None)


class SimResearchAdapter(Adapter):
    name = "sim-vidiq-research"

    def __init__(self, client: FakeVidIQ, cycle: int) -> None:
        self.client = client
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        response = self.client.research(topic=context.topic, idempotency_key=context.idempotency_key)
        parents = tuple(
            a.id
            for a in context.artifacts
            if a.kind in {"growth_feedback", "growth_feedback_batch"}
        )
        artifact = Artifact(
            id=_artifact_id("research", context),
            kind="research",
            uri=f"sim://research/{context.job_id}.json",
            producer=self.name,
            parents=parents,
            metadata=response,
            created_at=_sim_time(self.cycle, context.stage),
        )
        return StepResult((artifact,), {"provider": "vidiq", "simulated": True})


class SimIdeaAdapter(Adapter):
    name = "sim-idea"

    def __init__(self, cycle: int) -> None:
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        research = _latest(context, "research")
        parents = (research.id,) if research else ()
        artifact = Artifact(
            id=_artifact_id("idea", context),
            kind="idea",
            uri=f"sim://idea/{context.job_id}.json",
            producer=self.name,
            parents=parents,
            metadata={
                "cycle": self.cycle,
                "concept": f"{context.topic} / deterministic angle {self.cycle}",
            },
            created_at=_sim_time(self.cycle, context.stage),
        )
        return StepResult((artifact,), {"simulated": True})


class SimScriptAdapter(Adapter):
    name = "sim-script"

    def __init__(self, cycle: int) -> None:
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        revision = sum(1 for a in context.artifacts if a.kind == "script") + 1
        idea = _latest(context, "idea")
        parents = (idea.id,) if idea else ()
        artifact = Artifact(
            id=_artifact_id("script", context, str(revision)),
            kind="script",
            uri=f"sim://script/{context.job_id}/r{revision}.json",
            producer=self.name,
            parents=parents,
            metadata={
                "cycle": self.cycle,
                "revision": revision,
                "text": f"Cycle {self.cycle} script revision {revision}: {context.topic}",
            },
            created_at=_sim_time(self.cycle, context.stage, revision),
        )
        return StepResult((artifact,), {"simulated": True, "revision": revision})


class SimRunwayAdapter(Adapter):
    name = "sim-runway"

    def __init__(self, client: FakeRunway, cycle: int) -> None:
        self.client = client
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        script = _latest(context, "script")
        if script is None:
            raise CampaignSimulationError("assets stage requires a script artifact")
        prompt = f"vertical visual package for {context.topic}; script={script.id}"
        request = Artifact(
            id=_artifact_id("asset-request", context),
            kind="asset_request",
            uri=f"sim://runway/{context.job_id}/request.json",
            producer=self.name,
            parents=(script.id,),
            metadata={"prompt": prompt},
            created_at=_sim_time(self.cycle, context.stage),
        )
        response = self.client.generate_asset(prompt=prompt, idempotency_key=context.idempotency_key)
        asset = Artifact(
            id=_artifact_id("visual-asset", context),
            kind="visual_asset",
            uri=response["asset_uri"],
            producer=self.name,
            parents=(request.id,),
            metadata=response,
            created_at=_sim_time(self.cycle, context.stage, 1),
        )
        return StepResult((request, asset), {"provider": "runway", "simulated": True})


class SimVoiceAdapter(Adapter):
    name = "sim-descript-voice"

    def __init__(self, client: FakeDescript, cycle: int) -> None:
        self.client = client
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        script = _latest(context, "script")
        if script is None:
            raise CampaignSimulationError("voice stage requires a script artifact")
        request = Artifact(
            id=_artifact_id("voice-request", context),
            kind="voice_request",
            uri=f"sim://descript/{context.job_id}/voice-request.json",
            producer=self.name,
            parents=(script.id,),
            metadata={"script_uri": script.uri},
            created_at=_sim_time(self.cycle, context.stage),
        )
        response = self.client.synthesize_voice(
            script_uri=script.uri,
            idempotency_key=context.idempotency_key,
        )
        voice = Artifact(
            id=_artifact_id("voice", context),
            kind="voice",
            uri=response["voice_uri"],
            producer=self.name,
            parents=(request.id,),
            metadata=response,
            created_at=_sim_time(self.cycle, context.stage, 1),
        )
        return StepResult((request, voice), {"provider": "descript", "simulated": True})


class SimCriticAdapter(Adapter):
    name = "sim-critic"

    def __init__(self, cycle: int, planned_rejects: int, revision_stage: str) -> None:
        self.cycle = cycle
        self.planned_rejects = planned_rejects
        self.revision_stage = revision_stage

    def execute(self, context: StepContext) -> StepResult:
        prior_rejects = sum(
            1
            for artifact in context.artifacts
            if artifact.kind == "critic_decision" and artifact.metadata.get("decision") == "reject"
        )
        decision = "reject" if prior_rejects < self.planned_rejects else "accept"
        media = _latest(context, "media_final_artifact") or _latest(context, "media_plan")
        script = _latest(context, "script")
        parents = tuple(a.id for a in (script, media) if a is not None)
        ordinal = sum(1 for a in context.artifacts if a.kind == "critic_decision") + 1
        artifact = Artifact(
            id=_artifact_id("critic-decision", context, str(ordinal)),
            kind="critic_decision",
            uri=f"sim://critic/{context.job_id}/{ordinal}.json",
            producer=self.name,
            parents=parents,
            metadata={
                "cycle": self.cycle,
                "decision": decision,
                "revision_stage": self.revision_stage if decision == "reject" else None,
                "reason": "deterministic_revision_gate" if decision == "reject" else "quality_gate_passed",
            },
            created_at=_sim_time(self.cycle, context.stage, ordinal),
        )
        return StepResult((artifact,), {"simulated": True, "decision": decision})


class SimQueueAdapter(Adapter):
    name = "sim-metricool-queue"

    def __init__(self, client: FakeMetricool, cycle: int) -> None:
        self.client = client
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        critic = _latest(context, "critic_decision")
        media = _latest(context, "media_final_artifact") or _latest(context, "media_plan")
        if critic is None or critic.metadata.get("decision") != "accept":
            raise RealPublishingDisabled("simulator cannot queue without an accepted critic decision")
        manifest = {
            "job_id": context.job_id,
            "topic": context.topic,
            "artifact_ids": [a.id for a in context.artifacts],
            "action": "queue_only",
        }
        response = self.client.queue_post(
            manifest=manifest,
            idempotency_key=context.idempotency_key,
            dry_run=True,
        )
        parents = tuple(a.id for a in (media, critic) if a is not None)
        artifact = Artifact(
            id=_artifact_id("publish-queue-item", context),
            kind="publish_queue_item",
            uri=f"sim://metricool/{context.job_id}/queue.json",
            producer=self.name,
            parents=parents,
            metadata={"manifest": manifest, "response": response, "dry_run": True},
            created_at=_sim_time(self.cycle, context.stage),
        )
        return StepResult((artifact,), {"provider": "metricool", "dry_run": True})


class SimAnalyticsAdapter(Adapter):
    name = "sim-vidiq-analytics"

    def __init__(self, client: FakeVidIQ, cycle: int) -> None:
        self.client = client
        self.cycle = cycle

    def execute(self, context: StepContext) -> StepResult:
        queue = _latest(context, "publish_queue_item")
        if queue is None:
            raise CampaignSimulationError("analytics stage requires a publish queue item")
        response = self.client.analytics(
            topic=context.topic,
            idempotency_key=context.idempotency_key,
        )
        artifact = Artifact(
            id=_artifact_id("analytics-feedback", context),
            kind="analytics_feedback",
            uri=f"sim://analytics/{context.job_id}.json",
            producer=self.name,
            parents=(queue.id,),
            metadata=response,
            created_at=_sim_time(self.cycle, context.stage),
        )
        return StepResult((artifact,), {"provider": "vidiq", "simulated": True})


class CampaignRunner:
    """Durable deterministic multi-cycle simulator.

    A single ``step`` performs at most one durable state-machine transition or
    stage attempt. Reconstructing the runner between any two steps exercises the
    same persisted job/campaign state used by normal execution.
    """

    def __init__(self, state_root: str | os.PathLike[str], config: CampaignConfig) -> None:
        self.root = Path(state_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.job_store = JsonJobStore(self.root / "jobs")
        self.campaign_store = JsonCampaignStore(self.root / "campaigns")

    def initialize(self) -> CampaignState:
        if self.campaign_store.exists(self.config.campaign_id):
            state = self.campaign_store.load(self.config.campaign_id)
            if state.config_digest != _config_digest(self.config.raw):
                raise CampaignSimulationError("campaign configuration changed during resume")
            return state
        state = CampaignState(
            campaign_id=self.config.campaign_id,
            config_digest=_config_digest(self.config.raw),
        )
        self.campaign_store.save(state)
        return state

    def _job_id(self, cycle: int) -> str:
        return f"{self.config.campaign_id}-cycle-{cycle:02d}"

    def _all_job_artifacts(self, state: CampaignState) -> list[Artifact]:
        artifacts: list[Artifact] = []
        for cycle in sorted(int(key) for key in state.cycle_job_ids):
            job_id = state.cycle_job_ids[str(cycle)]
            artifacts.extend(self.job_store.load(job_id).artifacts)
        return artifacts

    def _previous_analytics(self, state: CampaignState, cycle: int) -> Artifact | None:
        if cycle <= 1:
            return None
        previous_job = state.cycle_job_ids.get(str(cycle - 1))
        if previous_job is None:
            return None
        job = self.job_store.load(previous_job)
        return next((a for a in reversed(job.artifacts) if a.kind == "analytics_feedback"), None)

    def _seed_inputs(self, state: CampaignState, cycle: int) -> list[SeedArtifactInput]:
        base_time = (_SIM_BASE + timedelta(days=cycle - 1, seconds=1)).isoformat()
        seeds = [
            SeedArtifactInput(
                "media_timeline_v1",
                self.config.timeline,
                created_at=base_time,
            )
        ]
        if cycle > 1:
            feedback = state.feedback_by_cycle.get(str(cycle - 1))
            previous = self._previous_analytics(state, cycle)
            if feedback is None or previous is None:
                raise CampaignSimulationError("previous cycle feedback is missing during transition")
            seeds.insert(
                0,
                SeedArtifactInput(
                    "growth_feedback",
                    feedback,
                    parents=(previous.id,),
                    created_at=base_time,
                ),
            )
        return seeds

    def _wrap_failures(self, adapter: Adapter, cycle: int) -> Adapter:
        return FailureInjectingAdapter(
            wrapped=adapter,
            fail_attempts=self.config.failures_by_cycle.get(cycle, {}),
        )

    def _orchestrator(self, cycle: int) -> Orchestrator:
        vidiq = FakeVidIQ(cycle)
        runway = FakeRunway()
        descript = FakeDescript()
        metricool = FakeMetricool()
        media = FakeMediaEngine()
        job_id = self._job_id(cycle)
        media_adapter = MediaRenderPlanAdapter(
            client=media,
            export_spec=self.config.export_spec,
            output_path=self.config.output_path(cycle, job_id),
            record_request_artifact=True,
            artifact_created_at=_sim_time(cycle, JobStage.EDIT),
        )
        adapters: dict[JobStage, Adapter] = {
            JobStage.RESEARCH: SimResearchAdapter(vidiq, cycle),
            JobStage.IDEA: SimIdeaAdapter(cycle),
            JobStage.SCRIPT: SimScriptAdapter(cycle),
            JobStage.ASSETS: SimRunwayAdapter(runway, cycle),
            JobStage.VOICE: SimVoiceAdapter(descript, cycle),
            JobStage.EDIT: media_adapter,
            JobStage.CRITIC: SimCriticAdapter(
                cycle,
                self.config.critic_rejects_by_cycle.get(cycle, 0),
                self.config.revision_stage,
            ),
            JobStage.PUBLISH_QUEUE: SimQueueAdapter(metricool, cycle),
            JobStage.ANALYTICS: SimAnalyticsAdapter(vidiq, cycle),
        }
        for stage in (
            JobStage.RESEARCH,
            JobStage.SCRIPT,
            JobStage.ASSETS,
            JobStage.VOICE,
            JobStage.EDIT,
            JobStage.CRITIC,
            JobStage.PUBLISH_QUEUE,
            JobStage.ANALYTICS,
        ):
            adapters[stage] = self._wrap_failures(adapters[stage], cycle)
        return Orchestrator(
            self.job_store,
            adapters,
            retry_policy=RetryPolicy(self.config.max_attempts_per_stage),
        )

    def _latest_critic(self, job_id: str) -> Artifact | None:
        job = self.job_store.load(job_id)
        return next((a for a in reversed(job.artifacts) if a.kind == "critic_decision"), None)

    def _dedupe_events(self, state: CampaignState, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        for event in events:
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise CampaignSimulationError("analytics event_id is required")
            digest = hashlib.sha256(_canonical(event).encode()).hexdigest()
            previous = state.event_digest_by_id.get(event_id)
            if previous is not None:
                if previous != digest:
                    raise DuplicateAnalyticsEventConflict(
                        f"analytics event conflict for {event_id}"
                    )
                state.duplicate_events_suppressed += 1
                continue
            state.event_digest_by_id[event_id] = digest
            unique.append(event)
        return unique

    def _growth_feedback(self, state: CampaignState, cycle: int, job_id: str) -> dict[str, Any]:
        job = self.job_store.load(job_id)
        analytics = next((a for a in reversed(job.artifacts) if a.kind == "analytics_feedback"), None)
        if analytics is None:
            raise CampaignSimulationError("completed cycle has no analytics feedback artifact")
        raw_events = analytics.metadata.get("events")
        if not isinstance(raw_events, list):
            raise CampaignSimulationError("analytics feedback must carry events")
        events = self._dedupe_events(state, [_clone(event) for event in raw_events])
        if not events:
            raise CampaignSimulationError("cycle must contribute at least one unique analytics event")
        impressions = sum(int(event["impressions"]) for event in events)
        views = sum(int(event["views"]) for event in events)
        clicks = sum(int(event["clicks"]) for event in events)
        watch_time = sum(float(event["watch_time_seconds"]) for event in events)
        ctr = clicks / impressions if impressions else 0.0
        average_watch = watch_time / views if views else 0.0
        retention_auc = (
            sum(float(event["retention_auc"]) * int(event["impressions"]) for event in events)
            / impressions
            if impressions
            else 0.0
        )
        score = (
            0.35 * min(ctr / 0.10, 1.0)
            + 0.35 * min(average_watch / 60.0, 1.0)
            + 0.30 * min(max(retention_auc, 0.0), 1.0)
        )
        uncertainty = min(1.0, 1.0 / math.sqrt(max(impressions, 1)))
        recommendations: list[str] = []
        if ctr < 0.04:
            recommendations.append("test_thumbnail_or_title")
        if average_watch / 60.0 < 0.35:
            recommendations.append("strengthen_opening_and_pacing")
        if retention_auc < 0.45:
            recommendations.append("inspect_retention_drop_points")
        if not recommendations:
            recommendations.append("preserve_current_pattern")
        payload = {
            "contract_version": "1.0",
            "content_job_id": job_id,
            "channel_id": "sim-channel",
            "video_id": f"{self.config.campaign_id}-video-{cycle:02d}",
            "variant_id": f"cycle-{cycle:02d}",
            "score": round(score, 8),
            "uncertainty": round(uncertainty, 8),
            "observed": {
                "ctr": round(ctr, 8),
                "average_watch_time_seconds": round(average_watch, 8),
                "retention_auc": round(retention_auc, 8),
            },
            "recommendations": recommendations,
            "evidence_event_ids": sorted(event["event_id"] for event in events),
        }
        return validate_growth_feedback(payload)

    def _lineage_report(self, state: CampaignState) -> LineageReport:
        return validate_artifact_dag(self._all_job_artifacts(state))

    def _build_report(self, state: CampaignState) -> Artifact:
        stage_attempts: Counter[str] = Counter()
        artifact_counts: Counter[str] = Counter()
        retries = 0
        critic_rejects = 0
        render_fingerprints: list[str] = []
        report_parents: list[str] = []
        for cycle in range(1, self.config.cycles + 1):
            job = self.job_store.load(state.cycle_job_ids[str(cycle)])
            for stage, count in job.attempts.items():
                stage_attempts[_STAGE_ALIAS.get(stage, stage)] += count
            retries += sum(max(0, count - 1) for count in job.idempotency_attempts.values())
            for artifact in job.artifacts:
                artifact_counts[artifact.kind] += 1
                if artifact.kind == "critic_decision" and artifact.metadata.get("decision") == "reject":
                    critic_rejects += 1
                if artifact.kind == "media_plan":
                    render_fingerprints.append(artifact.metadata["renderFingerprint"])
            analytics = next(a for a in reversed(job.artifacts) if a.kind == "analytics_feedback")
            report_parents.append(analytics.id)
        artifact_counts["campaign_report"] += 1
        lineage = self._lineage_report(state)
        metadata = {
            "contractVersion": CAMPAIGN_CONTRACT_VERSION,
            "campaignId": self.config.campaign_id,
            "cycles": self.config.cycles,
            "stage_attempts": dict(sorted(stage_attempts.items())),
            "retries": retries,
            "critic_rejects": critic_rejects,
            "artifact_counts": dict(sorted(artifact_counts.items())),
            "cycle_transitions": max(0, len(state.completed_cycles) - 1),
            "duplicate_events_suppressed": state.duplicate_events_suppressed,
            "render_fingerprints": render_fingerprints,
            "simulated_performance_feedback": [
                state.feedback_by_cycle[str(cycle)]
                for cycle in range(1, self.config.cycles + 1)
            ],
            "lineage": {
                "node_count": lineage.node_count,
                "edge_count": lineage.edge_count,
                "root_ids": list(lineage.root_ids),
                "leaf_ids": list(lineage.leaf_ids),
            },
        }
        digest = hashlib.sha256(_canonical(metadata).encode()).hexdigest()[:16]
        return Artifact(
            id=f"campaign-report-{digest}",
            kind="campaign_report",
            uri=f"campaign://{self.config.campaign_id}/report.json",
            producer="campaign-simulator-v2",
            parents=tuple(report_parents),
            metadata=metadata,
            created_at=(_SIM_BASE + timedelta(days=self.config.cycles, hours=2)).isoformat(),
        )

    def step(self) -> CampaignState:
        state = self.initialize()
        if state.status in {"complete", "failed"}:
            return state
        cycle = state.current_cycle
        cycle_key = str(cycle)
        job_id = state.cycle_job_ids.get(cycle_key)
        orchestrator = self._orchestrator(cycle)

        if job_id is None:
            job_id = self._job_id(cycle)
            orchestrator.create_job(
                job_id,
                self.config.topic,
                seed_artifacts=self._seed_inputs(state, cycle),
            )
            state.cycle_job_ids[cycle_key] = job_id
            self.campaign_store.save(state)
            return state

        job = self.job_store.load(job_id)
        if job.state == JobState.FAILED:
            state.status = "failed"
            state.last_error = job.last_error or f"cycle {cycle} failed"
            self.campaign_store.save(state)
            return state

        if job.state == JobState.COMPLETE:
            if cycle not in state.completed_cycles:
                try:
                    feedback = self._growth_feedback(state, cycle, job_id)
                    state.feedback_by_cycle[cycle_key] = feedback
                    state.completed_cycles.append(cycle)
                    validate_artifact_dag(self._all_job_artifacts(state))
                except Exception as exc:
                    state.status = "failed"
                    state.last_error = f"{type(exc).__name__}: {exc}"
                    self.campaign_store.save(state)
                    return state
            if cycle < self.config.cycles:
                state.current_cycle = cycle + 1
                self.campaign_store.save(state)
                return state
            state.report_artifact = self._build_report(state)
            validate_artifact_dag([*self._all_job_artifacts(state), state.report_artifact])
            state.status = "complete"
            self.campaign_store.save(state)
            return state

        if job.stage == JobStage.PUBLISH_QUEUE:
            critic = self._latest_critic(job_id)
            if (
                critic is not None
                and critic.metadata.get("decision") == "reject"
                and critic.id not in state.handled_critic_ids
            ):
                reject_count = sum(
                    1
                    for artifact in job.artifacts
                    if artifact.kind == "critic_decision" and artifact.metadata.get("decision") == "reject"
                )
                if reject_count > self.config.max_critic_revisions:
                    state.status = "failed"
                    state.last_error = (
                        f"critic revision budget exhausted in cycle {cycle}: "
                        f"{reject_count}>{self.config.max_critic_revisions}"
                    )
                    self.campaign_store.save(state)
                    return state
                orchestrator.request_revision(
                    job_id,
                    _REVISION_STAGES[self.config.revision_stage],
                )
                state.handled_critic_ids.append(critic.id)
                self.campaign_store.save(state)
                return state

        job = orchestrator.run_next(job_id)
        if job.state == JobState.FAILED:
            state.status = "failed"
            state.last_error = job.last_error
            self.campaign_store.save(state)
        return state

    def run_to_terminal(self, max_steps: int = 1000) -> CampaignState:
        state = self.initialize()
        for _ in range(max_steps):
            if state.status in {"complete", "failed"}:
                return state
            state = self.step()
        state.status = "failed"
        state.last_error = f"simulation exceeded max_steps={max_steps}"
        self.campaign_store.save(state)
        return state


def load_campaign_fixture(path: str | os.PathLike[str]) -> CampaignConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CampaignConfig.from_dict(payload)
