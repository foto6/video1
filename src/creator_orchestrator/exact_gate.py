from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .external_ops import OperationBoundaryCrash, OperationResumePolicy
from .growth_seed import (
    GROWTH_CAUSALITY_NOTICE,
    JsonGrowthSeedLedger,
    validate_growth_creator_seed,
)
from .integration import SeedArtifactInput, validate_growth_feedback
from .lineage import validate_artifact_dag
from .media_job_v1 import MediaJobV1ResumableAdapter
from .models import Artifact, JobStage, JobState
from .orchestrator import JsonJobStore, Orchestrator
from .sim_fakes import (
    FakeDescript,
    FakeMediaJobV1Client,
    FakeMetricool,
    FakeRunway,
    FakeVidIQ,
)
from .simulator import (
    SimAnalyticsAdapter,
    SimCriticAdapter,
    SimIdeaAdapter,
    SimQueueAdapter,
    SimResearchAdapter,
    SimRunwayAdapter,
    SimScriptAdapter,
    SimVoiceAdapter,
)

_GATE_TIME = "2026-09-27T00:00:00+00:00"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _simulate_growth_handoff_from_analytics(
    analytics: Artifact,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    """Simulation-only Growth producer used by the cross-repo integration gate."""
    raw_events = analytics.metadata.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError("analytics artifact must contain events")
    by_id: dict[str, Mapping[str, Any]] = {}
    for event in raw_events:
        if not isinstance(event, Mapping):
            raise ValueError("analytics event must be an object")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("analytics event_id is required")
        existing = by_id.get(event_id)
        if existing is not None and _canonical(existing) != _canonical(event):
            raise ValueError("conflicting analytics replay")
        by_id[event_id] = event

    events = [by_id[key] for key in sorted(by_id)]
    impressions = sum(int(event["impressions"]) for event in events)
    views = sum(int(event["views"]) for event in events)
    clicks = sum(int(event["clicks"]) for event in events)
    watch_time = sum(float(event["watch_time_seconds"]) for event in events)
    ctr = clicks / impressions
    average_watch = watch_time / views
    retention = (
        sum(float(event["retention_auc"]) * int(event["impressions"]) for event in events)
        / impressions
    )
    feedback = validate_growth_feedback(
        {
            "contract_version": "1.0",
            "content_job_id": f"{campaign_id}-cycle-03",
            "channel_id": "sim-channel",
            "video_id": f"{campaign_id}-video-02",
            "variant_id": "cycle-02",
            "score": round(
                0.35 * min(ctr / 0.10, 1.0)
                + 0.35 * min(average_watch / 60.0, 1.0)
                + 0.30 * retention,
                8,
            ),
            "uncertainty": round(1.0 / (impressions ** 0.5), 8),
            "observed": {
                "ctr": round(ctr, 8),
                "average_watch_time_seconds": round(average_watch, 8),
                "retention_auc": round(retention, 8),
            },
            "recommendations": ["strengthen_opening_and_pacing"],
            "evidence_event_ids": sorted(by_id),
        }
    )
    feedback_wire = _canonical(feedback)
    window = {
        "label": "creator-wave4-cycle-02",
        "start": "2026-09-16T00:00:00Z",
        "end": "2026-09-23T00:00:00Z",
    }
    identity = {
        "campaign_id": campaign_id,
        "window": window,
        "evidence": [
            {
                "content_job_id": feedback["content_job_id"],
                "variant_id": feedback["variant_id"],
                "evidence_event_ids": sorted(feedback["evidence_event_ids"]),
            }
        ],
    }
    batch_id = "fb1:" + _sha256(_canonical(identity))
    payload = {
        "handoff_version": "growth.creator_seed.v1",
        "seed_kind": "growth_feedback_batch",
        "idempotency_key": batch_id,
        "batch_id": batch_id,
        "campaign_id": campaign_id,
        "window": window,
        "payload_digest": _sha256(feedback_wire),
        "causal": False,
        "interpretation": GROWTH_CAUSALITY_NOTICE,
        "feedback": [feedback],
    }
    return validate_growth_creator_seed(payload)


class _CrashOnce:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.triggered = False

    def __call__(self, name, _receipt) -> None:
        if name == self.boundary and not self.triggered:
            self.triggered = True
            raise OperationBoundaryCrash(name)


def _build_orchestrator(
    store: JsonJobStore,
    media_client: FakeMediaJobV1Client,
    media_fixture: Mapping[str, Any],
    *,
    boundary_hook=None,
) -> Orchestrator:
    submit = media_fixture["submit"]
    render_request = submit["request"]
    adapters = {
        JobStage.RESEARCH: SimResearchAdapter(FakeVidIQ(2), 2),
        JobStage.IDEA: SimIdeaAdapter(2),
        JobStage.SCRIPT: SimScriptAdapter(2),
        JobStage.ASSETS: SimRunwayAdapter(FakeRunway(), 2),
        JobStage.VOICE: SimVoiceAdapter(FakeDescript(), 2),
        JobStage.EDIT: MediaJobV1ResumableAdapter(
            client=media_client,
            export_spec=render_request["exportSpec"],
            output_path="outputs/creator/wave4-cycle-02.mp4",
            dry_run=False,
            logical_job_id="creator-wave4-cycle-02-edit",
            artifact_created_at="2026-09-28T00:50:00+00:00",
        ),
        JobStage.CRITIC: SimCriticAdapter(2, 0, "script"),
        JobStage.PUBLISH_QUEUE: SimQueueAdapter(FakeMetricool(), 2),
        JobStage.ANALYTICS: SimAnalyticsAdapter(FakeVidIQ(2), 2),
    }
    return Orchestrator(
        store,
        adapters,
        operation_resume_policy=OperationResumePolicy(max_poll_attempts=20),
        operation_boundary_hook=boundary_hook,
    )


def run_exact_growth_creator_media_gate(
    state_root: str | Path,
    *,
    growth_fixture_path: str | Path,
    media_fixture_path: str | Path,
) -> dict[str, Any]:
    """Run the deterministic Growth -> Creator -> Media durable integration gate."""
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    growth_payload = json.loads(Path(growth_fixture_path).read_text(encoding="utf-8"))
    media_fixture = json.loads(Path(media_fixture_path).read_text(encoding="utf-8"))

    prior_analytics = Artifact(
        id="wave4-cycle-01-analytics",
        kind="analytics_feedback",
        uri="growth://round2-learning-demo/cycle-01/analytics",
        producer="growth-fixture-boundary",
        metadata={"committed": True},
        created_at=_GATE_TIME,
    )
    growth_ledger = JsonGrowthSeedLedger(root / "growth-seeds.jsonl")
    first_seed = growth_ledger.consume(
        growth_payload,
        parents=(prior_analytics.id,),
        artifact_created_at="2026-09-27T00:00:01+00:00",
    )
    replay_seed = growth_ledger.consume(growth_payload)
    if replay_seed.artifact != first_seed.artifact:
        raise RuntimeError("identical Growth replay did not resolve to the same seed")

    store = JsonJobStore(root / "jobs")
    media_client = FakeMediaJobV1Client(
        pending_polls=1,
        reconciliation_blocked_polls=1,
        media_internal_retries=1,
    )
    crash = _CrashOnce("after_accept_persisted")
    orchestrator = _build_orchestrator(
        store,
        media_client,
        media_fixture,
        boundary_hook=crash,
    )
    render_request = media_fixture["submit"]["request"]
    job_id = "wave4-cycle-02"
    orchestrator.create_job(
        job_id,
        "exact Growth Creator Media durable integration",
        seed_artifacts=(
            first_seed.artifact,
            SeedArtifactInput(
                "media_timeline_v1",
                render_request["timeline"],
                created_at="2026-09-27T00:00:02+00:00",
            ),
        ),
    )

    for _ in range(5):
        job = orchestrator.run_next(job_id)
        if job.state == JobState.FAILED:
            raise RuntimeError(job.last_error)

    try:
        orchestrator.run_next(job_id)
    except OperationBoundaryCrash:
        pass
    else:
        raise RuntimeError("expected restart boundary after Media acceptance receipt")

    accepted_receipts = list((store.directory / "_operations").glob("*.json"))
    if len(accepted_receipts) != 1:
        raise RuntimeError("expected exactly one durable Media operation receipt")

    resumed = _build_orchestrator(store, media_client, media_fixture)
    pending = resumed.run_next(job_id)
    if pending.state != JobState.WAITING_RETRY:
        raise RuntimeError("expected Media status to remain pending on first resume")

    resumed_again = _build_orchestrator(store, media_client, media_fixture)
    completed_edit = resumed_again.run_next(job_id)
    if completed_edit.state == JobState.FAILED:
        raise RuntimeError(completed_edit.last_error)

    while True:
        runner = _build_orchestrator(store, media_client, media_fixture)
        job = runner.run_next(job_id)
        if job.state == JobState.COMPLETE:
            break
        if job.state == JobState.FAILED:
            raise RuntimeError(job.last_error)
        if job.state == JobState.WAITING_RETRY:
            continue

    final_media = next(
        artifact
        for artifact in reversed(job.artifacts)
        if artifact.kind == "media_final_artifact"
    )
    edit_key = job.completed_idempotency_keys[JobStage.EDIT.value]
    media_receipt = runner.operation_ledger.load(
        job.id,
        JobStage.EDIT.value,
        edit_key,
    )
    analytics = next(
        artifact
        for artifact in reversed(job.artifacts)
        if artifact.kind == "analytics_feedback"
    )
    next_growth_payload = _simulate_growth_handoff_from_analytics(
        analytics,
        campaign_id="round2-learning-demo",
    )
    next_seed = growth_ledger.consume(
        next_growth_payload,
        parents=(analytics.id,),
        artifact_created_at="2026-09-29T00:00:01+00:00",
    )

    combined = [
        prior_analytics,
        *job.artifacts,
        next_seed.artifact,
    ]
    lineage = validate_artifact_dag(combined)
    return {
        "contractVersion": "creator.exact_growth_media_gate.v1",
        "jobId": job_id,
        "growth": {
            "committedSeeds": growth_ledger.committed_count,
            "initialStatus": first_seed.status,
            "initialReplayStatus": replay_seed.status,
            "initialIdempotencyKey": first_seed.idempotency_key,
            "nextIdempotencyKey": next_seed.idempotency_key,
        },
        "media": {
            "acceptedJobs": media_client.accepted_jobs,
            "submitRequests": media_client.submit_requests,
            "resumeCalls": media_client.resume_calls,
            "statusCalls": media_client.status_calls,
            "cancelCalls": media_client.cancel_calls,
            "jobId": final_media.metadata["jobId"],
            "renderFingerprint": final_media.metadata["renderFingerprint"],
            "qaPassed": final_media.metadata["qaPassed"],
            "finalArtifact": final_media.metadata["finalArtifact"],
            "mediaOwnedRetries": final_media.metadata["telemetry"]["retries"],
            "executorInvocations": final_media.metadata["telemetry"]["sideEffects"][
                "executorInvocations"
            ],
            "reconciliationBlockedResponses": (
                media_client.reconciliation_blocked_responses
            ),
            "mediaProtocolReconciliations": final_media.metadata["telemetry"][
                "protocol"
            ]["reconciliations"],
            "operationPollAttempts": media_receipt.poll_attempts,
        },
        "creator": {
            "state": job.state.value,
            "artifactCount": len(job.artifacts),
            "queueOnly": True,
        },
        "lineage": {
            "nodeCount": lineage.node_count,
            "edgeCount": lineage.edge_count,
            "growthSeedId": first_seed.artifact.id,
            "mediaFinalId": final_media.id,
            "analyticsId": analytics.id,
            "nextGrowthSeedId": next_seed.artifact.id,
        },
    }
