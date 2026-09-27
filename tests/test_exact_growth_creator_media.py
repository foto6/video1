from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.exact_gate import run_exact_growth_creator_media_gate
from creator_orchestrator.external_ops import (
    OperationBoundaryCrash,
    OperationState,
)
from creator_orchestrator.growth_seed import (
    GrowthCreatorSeedConflictError,
    GrowthCreatorSeedInjectedCrash,
    JsonGrowthSeedLedger,
    validate_growth_creator_seed,
)
from creator_orchestrator.integration import SeedArtifactInput, validate_growth_feedback
from creator_orchestrator.media_job_v1 import (
    MediaJobV1ProtocolError,
    MediaJobV1ResumableAdapter,
)
from creator_orchestrator.models import JobStage, JobState, STAGE_ORDER
from creator_orchestrator.orchestrator import JsonJobStore, Orchestrator
from creator_orchestrator.ports import StepContext
from creator_orchestrator.sim_fakes import FakeMediaJobV1Client

ROOT = Path(__file__).resolve().parents[1]
GROWTH_FIXTURE = (
    ROOT / "fixtures" / "upstream" / "growth" / "creator_next_cycle_seed_v1.json"
)
MEDIA_FIXTURE = (
    ROOT / "fixtures" / "upstream" / "media" / "media.job.v1.consumer.json"
)
MANIFEST = ROOT / "fixtures" / "upstream" / "manifest.json"
EXPECTED_GATE = ROOT / "fixtures" / "exact_growth_creator_media_gate_v1.expected.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class CrashOnce:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.triggered = False

    def __call__(self, name, _receipt) -> None:
        if name == self.boundary and not self.triggered:
            self.triggered = True
            raise OperationBoundaryCrash(name)


class ExactGrowthCreatorMediaTests(unittest.TestCase):
    def _media_setup(
        self,
        root: str,
        client: FakeMediaJobV1Client,
        *,
        hook=None,
        output_path="outputs/creator/wave4-test.mp4",
    ):
        fixture = load_json(MEDIA_FIXTURE)
        render = fixture["submit"]["request"]
        store = JsonJobStore(Path(root) / "jobs")
        adapter = MediaJobV1ResumableAdapter(
            client=client,
            export_spec=render["exportSpec"],
            output_path=output_path,
            dry_run=False,
            logical_job_id="wave4-media-job",
        )
        orchestrator = Orchestrator(
            store,
            {JobStage.EDIT: adapter},
            operation_boundary_hook=hook,
        )
        path = store.directory / "wave4-job.json"
        if not path.exists():
            orchestrator.create_job(
                "wave4-job",
                "exact media job recovery",
                seed_artifacts=[
                    SeedArtifactInput("media_timeline_v1", render["timeline"])
                ],
            )
            job = store.load("wave4-job")
            job.stage_index = STAGE_ORDER.index(JobStage.EDIT)
            store.save(job)
        return store, orchestrator, adapter

    def _context(self, store: JsonJobStore, orchestrator: Orchestrator) -> StepContext:
        job = store.load("wave4-job")
        key = job.completed_idempotency_keys.get(JobStage.EDIT.value)
        if key is None:
            key = orchestrator._idempotency_key(job, JobStage.EDIT)
        return StepContext(
            job_id=job.id,
            topic=job.topic,
            stage=JobStage.EDIT,
            idempotency_key=key,
            artifacts=tuple(job.artifacts),
            attempt=1,
            stage_attempt=1,
        )

    def _receipt(self, store: JsonJobStore, orchestrator: Orchestrator):
        job = store.load("wave4-job")
        key = job.completed_idempotency_keys.get(JobStage.EDIT.value)
        if key is None:
            key = orchestrator._idempotency_key(job, JobStage.EDIT)
        return orchestrator.operation_ledger.load(
            job.id,
            JobStage.EDIT.value,
            key,
        )

    def test_copied_upstream_fixtures_match_frozen_hash_manifest(self):
        manifest = load_json(MANIFEST)
        by_path = {item["consumerPath"]: item for item in manifest["fixtures"]}
        expected = {
            "fixtures/upstream/growth/creator_next_cycle_seed_v1.json": (
                "8d1a94cae77f2886b514477c272d7bc6de978042",
                "6c663665313cacd10a34f84af153b2546a8dc2c0",
                "58e100ab79b8a52b0f1286dc0af2c83179fc918b40d82808731f234046839224",
            ),
            "fixtures/upstream/media/media.job.v1.consumer.json": (
                "c921308a9deef916d088dc7c2c1186071eccb6e8",
                "678042975df835d258a249d3ec235d6f06b8c089",
                "02d6d0cc39ef746974c91cba54dfe2e84477bf68fd014cccd18525bc2f739cae",
            ),
        }
        for consumer_path, (head, blob, sha256) in expected.items():
            with self.subTest(consumer_path=consumer_path):
                item = by_path[consumer_path]
                self.assertEqual(item["sourceHead"], head)
                self.assertEqual(item["gitBlobSha1"], blob)
                data = (ROOT / consumer_path).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), sha256)

    def test_growth_creator_seed_exactly_once_replay_restart_and_conflict(self):
        payload = load_json(GROWTH_FIXTURE)
        validated = validate_growth_creator_seed(payload)
        self.assertEqual(validated["handoff_version"], "growth.creator_seed.v1")
        self.assertEqual(validated["idempotency_key"], validated["batch_id"])
        self.assertTrue(
            all(item["contract_version"] == "1.0" for item in validated["feedback"])
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "creator-growth-seeds.jsonl"
            ledger = JsonGrowthSeedLedger(path)
            first = ledger.consume(payload, parents=("cycle-n-analytics",))
            replay = ledger.consume(payload, parents=("ignored-replay-parent",))
            reopened = JsonGrowthSeedLedger(path)
            replay_after_restart = reopened.consume(payload)
            self.assertEqual(first.status, "committed")
            self.assertEqual(replay.status, "duplicate")
            self.assertEqual(replay_after_restart.status, "duplicate")
            self.assertEqual(first.artifact, replay.artifact)
            self.assertEqual(first.artifact, replay_after_restart.artifact)
            self.assertEqual(reopened.committed_count, 1)

            conflicting = json.loads(json.dumps(payload))
            conflicting["feedback"][0]["score"] = round(
                conflicting["feedback"][0]["score"] - 0.01, 8
            )
            normalized = [
                validate_growth_feedback(item)
                for item in conflicting["feedback"]
            ]
            conflicting["payload_digest"] = hashlib.sha256(
                "\n".join(canonical(item) for item in normalized).encode("utf-8")
            ).hexdigest()
            validate_growth_creator_seed(conflicting)
            with self.assertRaises(GrowthCreatorSeedConflictError):
                reopened.consume(conflicting)
            self.assertEqual(reopened.committed_count, 1)

    def test_growth_replay_after_local_commit_crash_is_same_seed(self):
        payload = load_json(GROWTH_FIXTURE)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "creator-growth-seeds.jsonl"
            ledger = JsonGrowthSeedLedger(path)
            with self.assertRaises(GrowthCreatorSeedInjectedCrash):
                ledger.consume(payload, fault="after_commit")
            reopened = JsonGrowthSeedLedger(path)
            receipt = reopened.consume(payload)
            self.assertEqual(receipt.status, "duplicate")
            self.assertEqual(reopened.committed_count, 1)

    def test_crash_after_media_submit_before_accept_receipt_reuses_same_media_job(self):
        client = FakeMediaJobV1Client()
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_submit_before_accept_persisted")
            store, first, _ = self._media_setup(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("wave4-job")
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(self._receipt(store, first).state, OperationState.PREPARED)

            store, resumed, _ = self._media_setup(td, client)
            job = resumed.run_next("wave4-job")
            self.assertEqual(job.state, JobState.PENDING)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.submit_requests, 2)
            self.assertEqual(client.resume_calls, 1)
            self.assertEqual(
                self._receipt(store, resumed).state,
                OperationState.COMMITTED,
            )

    def test_response_timeout_after_acceptance_never_resubmits(self):
        client = FakeMediaJobV1Client(
            pending_polls=1,
            response_timeout_after_acceptance_once=True,
        )
        with tempfile.TemporaryDirectory() as td:
            store, first, _ = self._media_setup(td, client)
            pending = first.run_next("wave4-job")
            self.assertEqual(pending.state, JobState.WAITING_RETRY)
            receipt = self._receipt(store, first)
            self.assertEqual(receipt.state, OperationState.ACCEPTED)
            self.assertEqual(receipt.external_operation_id, "wave4-media-job")
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.submit_requests, 1)

            store, resumed, _ = self._media_setup(td, client)
            done = resumed.run_next("wave4-job")
            self.assertEqual(done.state, JobState.PENDING)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.resume_calls, 2)

    def test_exact_status_pending_then_resume_same_job(self):
        client = FakeMediaJobV1Client(pending_polls=2)
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_accept_persisted")
            store, first, adapter = self._media_setup(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("wave4-job")
            receipt = self._receipt(store, first)
            context = self._context(store, first)
            status = adapter.status(context, receipt.external_operation_id)
            self.assertEqual(status["contractVersion"], "media.job.v1")
            self.assertEqual(status["status"], "queued")
            self.assertFalse(status["terminal"])
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)

            for _ in range(3):
                store, resumed, _ = self._media_setup(td, client)
                job = resumed.run_next("wave4-job")
                if job.state == JobState.PENDING:
                    break
            self.assertEqual(job.state, JobState.PENDING)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertGreaterEqual(client.resume_calls, 3)

    def test_reconciliation_blocked_restart_polls_same_media_job_until_success(self):
        client = FakeMediaJobV1Client(
            reconciliation_blocked_polls=1,
            pending_polls=1,
        )
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_accept_persisted")
            store, first, _ = self._media_setup(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("wave4-job")

            accepted = self._receipt(store, first)
            self.assertEqual(accepted.state, OperationState.ACCEPTED)
            self.assertEqual(accepted.external_operation_id, "wave4-media-job")
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)

            store, blocked_runner, _ = self._media_setup(td, client)
            blocked_job = blocked_runner.run_next("wave4-job")
            self.assertEqual(blocked_job.state, JobState.WAITING_RETRY)
            blocked_receipt = self._receipt(store, blocked_runner)
            self.assertEqual(blocked_receipt.state, OperationState.ACCEPTED)
            self.assertEqual(
                blocked_receipt.external_operation_id,
                accepted.external_operation_id,
            )
            self.assertEqual(
                blocked_receipt.poll_metadata["status"],
                "retry_wait",
            )
            self.assertEqual(
                blocked_receipt.poll_metadata["reconciliation"],
                {
                    "required": True,
                    "reason": "uncertain_render_attempt",
                },
            )
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.resume_calls, 1)

            store, pending_runner, _ = self._media_setup(td, client)
            pending_job = pending_runner.run_next("wave4-job")
            self.assertEqual(pending_job.state, JobState.WAITING_RETRY)
            pending_receipt = self._receipt(store, pending_runner)
            self.assertEqual(
                pending_receipt.external_operation_id,
                accepted.external_operation_id,
            )
            self.assertEqual(pending_receipt.poll_metadata["status"], "queued")
            self.assertEqual(
                pending_receipt.poll_metadata["reconciliation"],
                {"required": False},
            )
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.resume_calls, 2)

            store, final_runner, _ = self._media_setup(td, client)
            final_job = final_runner.run_next("wave4-job")
            self.assertEqual(final_job.state, JobState.PENDING)
            final_receipt = self._receipt(store, final_runner)
            self.assertEqual(final_receipt.state, OperationState.COMMITTED)
            self.assertEqual(
                final_receipt.external_operation_id,
                accepted.external_operation_id,
            )
            self.assertEqual(final_receipt.poll_attempts, 3)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.resume_calls, 3)
            self.assertEqual(client.reconciliation_blocked_responses, 1)
            final_artifacts = [
                artifact
                for artifact in final_job.artifacts
                if artifact.kind == "media_final_artifact"
            ]
            self.assertEqual(len(final_artifacts), 1)
            self.assertEqual(
                final_artifacts[0].metadata["jobId"],
                accepted.external_operation_id,
            )
            self.assertEqual(
                final_artifacts[0].metadata["telemetry"]["protocol"][
                    "reconciliations"
                ],
                1,
            )

    def test_reconciliation_blocked_identity_change_fails_closed(self):
        client = FakeMediaJobV1Client(
            reconciliation_blocked_polls=1,
            conflicting_reconciliation_identity_once=True,
        )
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_accept_persisted")
            store, first, _ = self._media_setup(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("wave4-job")
            accepted = self._receipt(store, first)
            self.assertEqual(accepted.external_operation_id, "wave4-media-job")

            store, resumed, _ = self._media_setup(td, client)
            failed = resumed.run_next("wave4-job")
            self.assertEqual(failed.state, JobState.FAILED)
            self.assertIn("Media jobId changed", failed.last_error)
            receipt = self._receipt(store, resumed)
            self.assertEqual(receipt.state, OperationState.ACCEPTED)
            self.assertEqual(
                receipt.external_operation_id,
                accepted.external_operation_id,
            )
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.resume_calls, 1)
            self.assertFalse(
                any(
                    artifact.kind == "media_final_artifact"
                    for artifact in failed.artifacts
                )
            )

    def test_restart_after_media_success_before_artifact_commit_uses_durable_result(self):
        client = FakeMediaJobV1Client(media_internal_retries=2)
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_result_persisted")
            store, first, _ = self._media_setup(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("wave4-job")
            self.assertEqual(self._receipt(store, first).state, OperationState.RESULT_OBTAINED)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.resume_calls, 1)

            store, resumed, _ = self._media_setup(td, client)
            job = resumed.run_next("wave4-job")
            final = next(a for a in job.artifacts if a.kind == "media_final_artifact")
            self.assertTrue(final.metadata["qaPassed"])
            self.assertEqual(final.metadata["retryOwner"], "media")
            self.assertEqual(final.metadata["telemetry"]["retries"], 2)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.resume_calls, 1)

    def test_conflicting_media_idempotency_key_fails_closed(self):
        client = FakeMediaJobV1Client()
        fixture = load_json(MEDIA_FIXTURE)
        first = fixture["submit"]
        accepted = client.handle(first)
        self.assertFalse(accepted["duplicate"])
        conflicting = json.loads(json.dumps(first))
        conflicting["request"]["jobId"] = "conflicting-job"
        conflicting["request"]["outputPath"] = "outputs/creator/conflicting.mp4"
        with self.assertRaises(MediaJobV1ProtocolError) as captured:
            client.handle(conflicting)
        self.assertEqual(captured.exception.code, "idempotency_conflict")
        self.assertEqual(client.accepted_jobs, 1)

    def test_cancel_race_uses_exact_cancel_and_never_submits_again(self):
        client = FakeMediaJobV1Client(pending_polls=10)
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_accept_persisted")
            store, first, adapter = self._media_setup(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("wave4-job")
            receipt = self._receipt(store, first)
            context = self._context(store, first)
            cancelled = adapter.cancel(
                context,
                receipt.external_operation_id,
                reason="creator_cancelled",
            )
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertIsNone(cancelled["finalArtifact"])
            self.assertEqual(client.cancel_calls, 1)

            store, resumed, _ = self._media_setup(td, client)
            failed = resumed.run_next("wave4-job")
            self.assertEqual(failed.state, JobState.FAILED)
            self.assertIn("cancelled", failed.last_error)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.submit_requests, 1)

    def test_deterministic_cross_cycle_gate_connects_full_lineage(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = run_exact_growth_creator_media_gate(
                first,
                growth_fixture_path=GROWTH_FIXTURE,
                media_fixture_path=MEDIA_FIXTURE,
            )
            right = run_exact_growth_creator_media_gate(
                second,
                growth_fixture_path=GROWTH_FIXTURE,
                media_fixture_path=MEDIA_FIXTURE,
            )
            self.assertEqual(left, right)
            self.assertEqual(left, load_json(EXPECTED_GATE))
            self.assertEqual(left["growth"]["committedSeeds"], 2)
            self.assertEqual(left["growth"]["initialStatus"], "committed")
            self.assertEqual(left["growth"]["initialReplayStatus"], "duplicate")
            self.assertEqual(left["media"]["acceptedJobs"], 1)
            self.assertEqual(left["media"]["submitRequests"], 1)
            self.assertEqual(left["media"]["reconciliationBlockedResponses"], 1)
            self.assertEqual(left["media"]["mediaProtocolReconciliations"], 1)
            self.assertEqual(left["media"]["operationPollAttempts"], 3)
            self.assertEqual(left["media"]["resumeCalls"], 3)
            self.assertTrue(left["media"]["qaPassed"])
            self.assertEqual(left["media"]["mediaOwnedRetries"], 1)
            self.assertEqual(left["creator"]["state"], "complete")
            self.assertTrue(left["creator"]["queueOnly"])
            self.assertNotEqual(
                left["lineage"]["growthSeedId"],
                left["lineage"]["nextGrowthSeedId"],
            )


if __name__ == "__main__":
    unittest.main()
