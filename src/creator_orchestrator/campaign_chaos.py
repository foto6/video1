from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .external_ops import OperationBoundaryCrash, OperationResumePolicy, OperationState
from .growth_seed import (
    GROWTH_CAUSALITY_NOTICE,
    GrowthCreatorSeedConflictError,
    GrowthCreatorSeedInjectedCrash,
    JsonGrowthSeedLedger,
    validate_growth_creator_seed,
)
from .integration import SeedArtifactInput, validate_growth_feedback
from .lineage import validate_artifact_dag
from .media_job_v1 import MediaJobV1ProtocolError, MediaJobV1ResumableAdapter
from .models import Artifact, JobStage, JobState
from .orchestrator import JsonJobStore, Orchestrator
from .ports import StepContext
from .sim_fakes import FakeDescript, FakeMediaJobV1Client, FakeMetricool, FakeRunway, FakeVidIQ
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

REPORT_VERSION = "creator.campaign_chaos_report.v1"
GROWTH_SOURCE_REPO = "foto6/video3"
GROWTH_SOURCE_HEAD = "8d1a94cae77f2886b514477c272d7bc6de978042"
GROWTH_SOURCE_BLOB = "6c663665313cacd10a34f84af153b2546a8dc2c0"
GROWTH_SOURCE_SHA256 = "58e100ab79b8a52b0f1286dc0af2c83179fc918b40d82808731f234046839224"
MEDIA_SOURCE_REPO = "foto6/video2"
MEDIA_SOURCE_HEAD = "c921308a9deef916d088dc7c2c1186071eccb6e8"
MEDIA_SOURCE_BLOB = "678042975df835d258a249d3ec235d6f06b8c089"
MEDIA_SOURCE_SHA256 = "02d6d0cc39ef746974c91cba54dfe2e84477bf68fd014cccd18525bc2f739cae"
_BASE_TIME = datetime(2026, 9, 27, tzinfo=timezone.utc)
_MEDIA_BOUNDARIES = (
    "after_accept_persisted",
    "after_result_persisted",
    "after_artifact_commit_before_receipt_commit",
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha(value: Any) -> str:
    wire = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def _fixed_time(cycle: int, seconds: int = 0) -> str:
    return (_BASE_TIME + timedelta(days=cycle - 1, seconds=seconds)).isoformat()


def _feedback_from_analytics(
    analytics: Artifact,
    *,
    cycle: int,
    variant: int,
) -> dict[str, Any]:
    raw_events = analytics.metadata.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise RuntimeError("analytics artifact must contain events")
    by_id: dict[str, Mapping[str, Any]] = {}
    for event in raw_events:
        if not isinstance(event, Mapping):
            raise RuntimeError("analytics event must be an object")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise RuntimeError("analytics event_id is required")
        previous = by_id.get(event_id)
        if previous is not None and _canonical(previous) != _canonical(event):
            raise RuntimeError("conflicting analytics replay")
        by_id[event_id] = event

    events = [by_id[key] for key in sorted(by_id)]
    impressions = sum(int(event["impressions"]) for event in events)
    views = sum(int(event["views"]) for event in events)
    clicks = sum(int(event["clicks"]) for event in events)
    watch_time = sum(float(event["watch_time_seconds"]) for event in events)
    ctr = clicks / impressions if impressions else 0.0
    average_watch = watch_time / views if views else 0.0
    retention = (
        sum(float(event["retention_auc"]) * int(event["impressions"]) for event in events)
        / impressions
        if impressions
        else 0.0
    )
    return validate_growth_feedback(
        {
            "contract_version": "1.0",
            "content_job_id": f"chaos-c{cycle:02d}-v{variant:02d}",
            "channel_id": "chaos-channel",
            "video_id": f"chaos-video-c{cycle:02d}-v{variant:02d}",
            "variant_id": f"v{variant:02d}",
            "score": round(
                0.35 * min(ctr / 0.10, 1.0)
                + 0.35 * min(average_watch / 60.0, 1.0)
                + 0.30 * min(max(retention, 0.0), 1.0),
                8,
            ),
            "uncertainty": round(1.0 / (max(impressions, 1) ** 0.5), 8),
            "observed": {
                "ctr": round(ctr, 8),
                "average_watch_time_seconds": round(average_watch, 8),
                "retention_auc": round(retention, 8),
            },
            "recommendations": ["preserve_current_pattern"],
            "evidence_event_ids": sorted(by_id),
        }
    )


def _growth_payload(
    analytics: Sequence[Artifact],
    *,
    campaign_id: str,
    next_cycle: int,
) -> dict[str, Any]:
    feedback = [
        _feedback_from_analytics(item, cycle=next_cycle - 1, variant=index)
        for index, item in enumerate(analytics, 1)
    ]
    feedback.sort(
        key=lambda item: (
            item["content_job_id"],
            item["variant_id"] or "",
            item["video_id"],
            _canonical(item),
        )
    )
    window = {
        "label": f"chaos-cycle-{next_cycle:02d}",
        "start": (_BASE_TIME + timedelta(days=next_cycle - 2)).strftime("%Y-%m-%dT00:00:00Z"),
        "end": (_BASE_TIME + timedelta(days=next_cycle - 1)).strftime("%Y-%m-%dT00:00:00Z"),
    }
    identity = {
        "campaign_id": campaign_id,
        "window": window,
        "evidence": [
            {
                "content_job_id": item["content_job_id"],
                "variant_id": item["variant_id"],
                "evidence_event_ids": sorted(item["evidence_event_ids"]),
            }
            for item in feedback
        ],
    }
    batch_id = "fb1:" + _sha(identity)
    payload = {
        "handoff_version": "growth.creator_seed.v1",
        "seed_kind": "growth_feedback_batch",
        "idempotency_key": batch_id,
        "batch_id": batch_id,
        "campaign_id": campaign_id,
        "window": window,
        "payload_digest": _sha("\n".join(_canonical(item) for item in feedback)),
        "causal": False,
        "interpretation": GROWTH_CAUSALITY_NOTICE,
        "feedback": feedback,
    }
    return validate_growth_creator_seed(payload)


def _growth_conflict(payload: Mapping[str, Any]) -> dict[str, Any]:
    conflict = json.loads(_canonical(payload))
    conflict["feedback"][0]["score"] = round(
        max(0.0, float(conflict["feedback"][0]["score"]) - 0.00000001),
        8,
    )
    normalized = [validate_growth_feedback(item) for item in conflict["feedback"]]
    conflict["feedback"] = normalized
    conflict["payload_digest"] = _sha("\n".join(_canonical(item) for item in normalized))
    return validate_growth_creator_seed(conflict)


class _BoundaryCrashPlan:
    def __init__(self, job_id: str, boundary: str, crashed: set[tuple[str, str]]) -> None:
        self.job_id = job_id
        self.boundary = boundary
        self.crashed = crashed

    def __call__(self, name: str, _receipt) -> None:
        key = (self.job_id, name)
        if name == self.boundary and key not in self.crashed:
            self.crashed.add(key)
            raise OperationBoundaryCrash(name)


def _build_orchestrator(
    store: JsonJobStore,
    client: FakeMediaJobV1Client,
    media_fixture: Mapping[str, Any],
    *,
    cycle: int,
    variant: int,
    job_id: str,
    boundary_hook=None,
) -> tuple[Orchestrator, MediaJobV1ResumableAdapter]:
    request = media_fixture["submit"]["request"]
    fake_cycle = cycle * 10 + variant
    media = MediaJobV1ResumableAdapter(
        client=client,
        export_spec=request["exportSpec"],
        output_path=f"outputs/chaos/{job_id}.mp4",
        dry_run=False,
        logical_job_id=f"{job_id}-media",
        artifact_created_at=_fixed_time(cycle, 50 + variant),
    )
    adapters = {
        JobStage.RESEARCH: SimResearchAdapter(FakeVidIQ(fake_cycle), cycle),
        JobStage.IDEA: SimIdeaAdapter(cycle),
        JobStage.SCRIPT: SimScriptAdapter(cycle),
        JobStage.ASSETS: SimRunwayAdapter(FakeRunway(), cycle),
        JobStage.VOICE: SimVoiceAdapter(FakeDescript(), cycle),
        JobStage.EDIT: media,
        JobStage.CRITIC: SimCriticAdapter(cycle, 0, "script"),
        JobStage.PUBLISH_QUEUE: SimQueueAdapter(FakeMetricool(), cycle),
        JobStage.ANALYTICS: SimAnalyticsAdapter(FakeVidIQ(fake_cycle), cycle),
    }
    return (
        Orchestrator(
            store,
            adapters,
            operation_resume_policy=OperationResumePolicy(max_poll_attempts=12),
            operation_boundary_hook=boundary_hook,
        ),
        media,
    )


def _edit_receipt(orchestrator: Orchestrator, job_id: str):
    candidates = sorted(
        orchestrator.operation_ledger.directory.glob(f"{job_id}.edit.*.json")
    )
    if not candidates:
        return None
    if len(candidates) != 1:
        raise RuntimeError(f"expected one edit receipt for {job_id}")
    payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    return orchestrator.operation_ledger.load(
        job_id,
        JobStage.EDIT.value,
        payload["idempotency_key"],
    )


def _artifact_digest(artifacts: Sequence[Artifact]) -> str:
    return _sha([asdict(item) for item in artifacts])


def _job_order(variants: int, cycle: int, ordering: str, seed: int) -> list[int]:
    values = list(range(1, variants + 1))
    if ordering == "forward":
        return values
    if ordering != "permuted":
        raise ValueError("ordering must be 'forward' or 'permuted'")
    if (cycle + seed) % 2:
        values.reverse()
    else:
        shift = seed % variants
        values = values[shift:] + values[:shift]
    return values


def run_campaign_chaos(
    state_root: str | Path,
    *,
    growth_fixture_path: str | Path,
    media_fixture_path: str | Path,
    cycles: int = 50,
    variants_per_cycle: int = 2,
    seed: int = 73421,
    ordering: str = "forward",
) -> dict[str, Any]:
    if cycles < 50:
        raise ValueError("campaign chaos soak requires at least 50 cycles")
    if variants_per_cycle < 2:
        raise ValueError("campaign chaos soak requires multiple variants per cycle")

    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    growth_path = Path(growth_fixture_path)
    media_path = Path(media_fixture_path)
    if hashlib.sha256(growth_path.read_bytes()).hexdigest() != GROWTH_SOURCE_SHA256:
        raise RuntimeError("Growth fixture bytes do not match pinned producer provenance")
    if hashlib.sha256(media_path.read_bytes()).hexdigest() != MEDIA_SOURCE_SHA256:
        raise RuntimeError("Media fixture bytes do not match pinned producer provenance")

    initial_growth = validate_growth_creator_seed(
        json.loads(growth_path.read_text(encoding="utf-8"))
    )
    media_fixture = json.loads(media_path.read_text(encoding="utf-8"))
    campaign_id = "creator-chaos-campaign"

    transitions: list[dict[str, Any]] = []
    crashed: set[tuple[str, str]] = set()
    immutable: dict[str, str] = {}
    media_clients: dict[str, FakeMediaJobV1Client] = {}
    seed_artifacts: list[Artifact] = []
    all_job_ids: list[str] = []
    analytics_by_cycle: dict[int, list[Artifact]] = {}
    growth_deliveries = 0
    growth_duplicates = 0
    growth_conflicts = 0
    media_conflicts = 0
    restarts = 0
    live_publish_calls = 0
    applied_batches: set[str] = set()

    growth_ledger_path = root / "growth-seeds.jsonl"
    next_payload = initial_growth
    next_parents: tuple[str, ...] = ()

    for cycle in range(1, cycles + 1):
        ledger = JsonGrowthSeedLedger(growth_ledger_path)
        growth_deliveries += 1
        try:
            ledger.consume(
                next_payload,
                parents=next_parents,
                artifact_created_at=_fixed_time(cycle, 1),
                fault="after_commit",
            )
        except GrowthCreatorSeedInjectedCrash:
            transitions.append({"kind": "crash", "boundary": "growth_after_commit", "cycle": cycle})
        else:
            raise RuntimeError("expected Growth commit crash")
        restarts += 1

        ledger = JsonGrowthSeedLedger(growth_ledger_path)
        growth_deliveries += 1
        receipt = ledger.consume(next_payload)
        if receipt.status != "duplicate":
            raise RuntimeError("Growth replay after commit crash must be duplicate")
        growth_duplicates += 1
        restarts += 1

        ledger = JsonGrowthSeedLedger(growth_ledger_path)
        growth_deliveries += 1
        replay = ledger.consume(next_payload)
        if replay.artifact != receipt.artifact or replay.status != "duplicate":
            raise RuntimeError("Growth replay must resolve to immutable seed")
        growth_duplicates += 1
        seed_artifact = replay.artifact
        seed_artifacts.append(seed_artifact)
        if replay.idempotency_key in applied_batches:
            raise RuntimeError("Growth batch applied to more than one campaign cycle")
        applied_batches.add(replay.idempotency_key)
        transitions.append(
            {
                "kind": "growth_seed",
                "cycle": cycle,
                "batch": replay.idempotency_key,
                "artifact": seed_artifact.id,
            }
        )

        if cycle % 10 == 0:
            growth_conflicts += 1
            try:
                ledger.consume(_growth_conflict(next_payload))
            except GrowthCreatorSeedConflictError:
                transitions.append({"kind": "growth_conflict_rejected", "cycle": cycle})
            else:
                raise RuntimeError("conflicting Growth idempotency reuse was accepted")

        current_analytics: list[Artifact] = []
        for variant in _job_order(variants_per_cycle, cycle, ordering, seed):
            job_id = f"chaos-c{cycle:02d}-v{variant:02d}"
            all_job_ids.append(job_id)
            ordinal = (cycle - 1) * variants_per_cycle + variant
            client = FakeMediaJobV1Client(
                pending_polls=1 if ordinal % 4 == 0 else 0,
                reconciliation_blocked_polls=1 if ordinal % 3 == 0 else 0,
                response_timeout_after_acceptance_once=ordinal % 11 == 0,
                media_internal_retries=ordinal % 2,
            )
            media_clients[job_id] = client
            boundary = _MEDIA_BOUNDARIES[(ordinal + seed) % len(_MEDIA_BOUNDARIES)]
            hook = _BoundaryCrashPlan(job_id, boundary, crashed)

            store = JsonJobStore(root / "jobs")
            orchestrator, _ = _build_orchestrator(
                store,
                client,
                media_fixture,
                cycle=cycle,
                variant=variant,
                job_id=job_id,
                boundary_hook=hook,
            )
            orchestrator.create_job(
                job_id,
                f"campaign chaos cycle {cycle} variant {variant}",
                seed_artifacts=(
                    seed_artifact,
                    SeedArtifactInput(
                        "media_timeline_v1",
                        media_fixture["submit"]["request"]["timeline"],
                        created_at=_fixed_time(cycle, 2 + variant),
                    ),
                ),
            )
            transitions.append({"kind": "job_create", "cycle": cycle, "variant": variant, "job": job_id})

            status_polled = False
            media_conflict_probed = False
            while True:
                store = JsonJobStore(root / "jobs")
                orchestrator, media_adapter = _build_orchestrator(
                    store,
                    client,
                    media_fixture,
                    cycle=cycle,
                    variant=variant,
                    job_id=job_id,
                    boundary_hook=hook,
                )
                try:
                    job = orchestrator.run_next(job_id)
                except OperationBoundaryCrash as exc:
                    transitions.append(
                        {
                            "kind": "crash",
                            "boundary": str(exc),
                            "cycle": cycle,
                            "variant": variant,
                            "job": job_id,
                        }
                    )
                    restarts += 1
                    continue

                transitions.append(
                    {
                        "kind": "stage",
                        "cycle": cycle,
                        "variant": variant,
                        "job": job_id,
                        "state": job.state.value,
                        "stage": None if job.stage is None else job.stage.value,
                        "artifactCount": len(job.artifacts),
                    }
                )
                restarts += 1

                receipt_now = _edit_receipt(orchestrator, job_id)
                if (
                    receipt_now is not None
                    and receipt_now.state == OperationState.ACCEPTED
                    and receipt_now.external_operation_id
                    and not status_polled
                ):
                    context = StepContext(
                        job_id=job_id,
                        topic=job.topic,
                        stage=JobStage.EDIT,
                        idempotency_key=receipt_now.idempotency_key,
                        artifacts=tuple(job.artifacts),
                    )
                    before = (client.submit_requests, client.accepted_jobs)
                    first_status = media_adapter.status(context, receipt_now.external_operation_id)
                    second_status = media_adapter.status(context, receipt_now.external_operation_id)
                    after = (client.submit_requests, client.accepted_jobs)
                    if before != after:
                        raise RuntimeError("read-only Media status caused submit side effects")
                    if first_status["jobId"] != second_status["jobId"]:
                        raise RuntimeError("Media status identity changed across read-only polls")
                    status_polled = True
                    transitions.append(
                        {
                            "kind": "media_status_reads",
                            "job": job_id,
                            "count": 2,
                            "status": second_status["status"],
                        }
                    )

                if (
                    receipt_now is not None
                    and receipt_now.external_operation_id
                    and ordinal % 10 == 0
                    and not media_conflict_probed
                ):
                    conflict = json.loads(_canonical(receipt_now.request))
                    conflict["request"]["outputPath"] = f"outputs/chaos/{job_id}-conflict.mp4"
                    try:
                        client.handle(conflict)
                    except MediaJobV1ProtocolError as exc:
                        if exc.code != "idempotency_conflict":
                            raise
                    else:
                        raise RuntimeError("conflicting Media idempotency reuse was accepted")
                    media_conflicts += 1
                    media_conflict_probed = True
                    transitions.append({"kind": "media_conflict_rejected", "job": job_id})

                if job.state == JobState.FAILED:
                    raise RuntimeError(f"{job_id} failed: {job.last_error}")
                if job.state == JobState.COMPLETE:
                    break

            final_store = JsonJobStore(root / "jobs")
            terminal = final_store.load(job_id)
            before_terminal = _canonical(
                {
                    "state": terminal.state.value,
                    "stage_index": terminal.stage_index,
                    "artifacts": [asdict(item) for item in terminal.artifacts],
                    "completed": terminal.completed_idempotency_keys,
                }
            )
            for _ in range(2):
                check_orchestrator, _ = _build_orchestrator(
                    JsonJobStore(root / "jobs"),
                    client,
                    media_fixture,
                    cycle=cycle,
                    variant=variant,
                    job_id=job_id,
                )
                checked = check_orchestrator.run_next(job_id)
                after_terminal = _canonical(
                    {
                        "state": checked.state.value,
                        "stage_index": checked.stage_index,
                        "artifacts": [asdict(item) for item in checked.artifacts],
                        "completed": checked.completed_idempotency_keys,
                    }
                )
                if after_terminal != before_terminal or checked.state != JobState.COMPLETE:
                    raise RuntimeError("terminal Creator state was not monotonic")
                restarts += 1

            final_job = final_store.load(job_id)
            immutable[job_id] = _artifact_digest(final_job.artifacts)
            queue_items = [item for item in final_job.artifacts if item.kind == "publish_queue_item"]
            if len(queue_items) != 1 or queue_items[0].metadata.get("dry_run") is not True:
                raise RuntimeError("Creator chaos harness attempted non-dry-run publishing")
            live_publish_calls += sum(
                1
                for item in queue_items
                if item.metadata.get("dry_run") is not True
            )
            analytics = next(
                item for item in reversed(final_job.artifacts) if item.kind == "analytics_feedback"
            )
            current_analytics.append(analytics)
            transitions.append(
                {
                    "kind": "job_complete",
                    "job": job_id,
                    "artifactDigest": immutable[job_id],
                }
            )

        current_analytics.sort(key=lambda item: item.id)
        analytics_by_cycle[cycle] = current_analytics
        if cycle < cycles:
            next_payload = _growth_payload(
                current_analytics,
                campaign_id=campaign_id,
                next_cycle=cycle + 1,
            )
            next_parents = tuple(item.id for item in current_analytics)
            restarts += 1
            transitions.append(
                {
                    "kind": "analytics_handoff",
                    "cycle": cycle,
                    "nextBatch": next_payload["batch_id"],
                    "parents": list(next_parents),
                }
            )

    final_store = JsonJobStore(root / "jobs")
    job_artifacts: list[Artifact] = []
    operation_polls = 0
    artifact_count = 0
    for job_id in sorted(all_job_ids):
        job = final_store.load(job_id)
        if _artifact_digest(job.artifacts) != immutable[job_id]:
            raise RuntimeError("completed artifact lineage mutated after later cycles")
        artifact_count += len(job.artifacts)
        job_artifacts.extend(job.artifacts)
        receipts = sorted((root / "jobs" / "_operations").glob(f"{job_id}.edit.*.json"))
        if len(receipts) != 1:
            raise RuntimeError(f"expected one durable Media receipt for {job_id}")
        payload = json.loads(receipts[0].read_text(encoding="utf-8"))
        if payload["state"] != OperationState.COMMITTED.value:
            raise RuntimeError(f"Media receipt not committed for {job_id}")
        operation_polls += int(payload["poll_attempts"])

    unique_artifacts: dict[str, Artifact] = {}
    for artifact in [*seed_artifacts, *job_artifacts]:
        existing = unique_artifacts.get(artifact.id)
        if existing is not None:
            if _canonical(asdict(existing)) != _canonical(asdict(artifact)):
                raise RuntimeError(f"artifact identity mutated: {artifact.id}")
            continue
        unique_artifacts[artifact.id] = artifact
    combined = [unique_artifacts[key] for key in sorted(unique_artifacts)]
    lineage = validate_artifact_dag(combined)
    artifact_count = len(combined)
    lineage_rows = sorted(
        (
            {
                "id": item.id,
                "kind": item.kind,
                "parents": sorted(item.parents),
                "producer": item.producer,
                "uri": item.uri,
                "metadataHash": _sha(item.metadata),
            }
            for item in combined
        ),
        key=lambda item: item["id"],
    )

    accepted_jobs = sum(client.accepted_jobs for client in media_clients.values())
    submit_requests = sum(client.submit_requests for client in media_clients.values())
    resume_calls = sum(client.resume_calls for client in media_clients.values())
    status_calls = sum(client.status_calls for client in media_clients.values())
    blocked = sum(client.reconciliation_blocked_responses for client in media_clients.values())
    if accepted_jobs != len(all_job_ids):
        raise RuntimeError("one Creator logical render did not map to one Media logical job")
    if max((client.accepted_jobs for client in media_clients.values()), default=0) != 1:
        raise RuntimeError("Media accepted duplicate logical jobs")
    if max((client.resume_calls for client in media_clients.values()), default=0) > 4:
        raise RuntimeError("nested retry storm detected")
    if len(applied_batches) != cycles:
        raise RuntimeError("Growth batch application count diverged from cycle count")
    if live_publish_calls != 0:
        raise RuntimeError("live publishing occurred")

    transition_rows = sorted((_canonical(item) for item in transitions))
    report = {
        "contractVersion": REPORT_VERSION,
        "seed": seed,
        "cycles": cycles,
        "variantsPerCycle": variants_per_cycle,
        "jobs": len(all_job_ids),
        "crashes": len(crashed) + cycles,
        "restarts": restarts,
        "submits": submit_requests,
        "polls": operation_polls,
        "artifacts": artifact_count,
        "transitionHash": _sha("\n".join(transition_rows)),
        "lineageHash": _sha(lineage_rows),
        "growth": {
            "deliveries": growth_deliveries,
            "committedBatches": len(applied_batches),
            "duplicateDeliveries": growth_duplicates,
            "conflictsRejected": growth_conflicts,
        },
        "media": {
            "acceptedJobs": accepted_jobs,
            "submitRequests": submit_requests,
            "resumeCalls": resume_calls,
            "statusCalls": status_calls,
            "operationPolls": operation_polls,
            "conflictsRejected": media_conflicts,
            "reconciliationBlockedResponses": blocked,
        },
        "creator": {
            "completeJobs": len(all_job_ids),
            "immutableLineageChecks": len(immutable),
            "terminalMonotonicChecks": len(all_job_ids) * 2,
            "livePublishCalls": live_publish_calls,
        },
        "lineage": {
            "nodeCount": lineage.node_count,
            "edgeCount": lineage.edge_count,
            "rootIds": list(lineage.root_ids),
            "leafIds": list(lineage.leaf_ids),
        },
        "producerProvenance": {
            "growth": {
                "repo": GROWTH_SOURCE_REPO,
                "head": GROWTH_SOURCE_HEAD,
                "blob": GROWTH_SOURCE_BLOB,
                "sha256": GROWTH_SOURCE_SHA256,
            },
            "media": {
                "repo": MEDIA_SOURCE_REPO,
                "head": MEDIA_SOURCE_HEAD,
                "blob": MEDIA_SOURCE_BLOB,
                "sha256": MEDIA_SOURCE_SHA256,
            },
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--growth-fixture", required=True)
    parser.add_argument("--media-fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cycles", type=int, default=50)
    parser.add_argument("--variants", type=int, default=2)
    parser.add_argument("--seed", type=int, default=73421)
    parser.add_argument("--ordering", choices=("forward", "permuted"), default="forward")
    args = parser.parse_args()
    report = run_campaign_chaos(
        args.state_root,
        growth_fixture_path=args.growth_fixture,
        media_fixture_path=args.media_fixture,
        cycles=args.cycles,
        variants_per_cycle=args.variants,
        seed=args.seed,
        ordering=args.ordering,
    )
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
