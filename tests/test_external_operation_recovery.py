from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.adapters import DeterministicTextAdapter
from creator_orchestrator.external_ops import (
    OperationBoundaryCrash,
    OperationResumePolicy,
    OperationState,
)
from creator_orchestrator.integration import SeedArtifactInput
from creator_orchestrator.models import JobStage, JobState, STAGE_ORDER
from creator_orchestrator.orchestrator import JsonJobStore, Orchestrator, RetryPolicy
from creator_orchestrator.resumable_media import GenericResumableMediaAdapter
from creator_orchestrator.sim_fakes import FakeResumableMediaOperationClient

ROOT = Path(__file__).resolve().parents[1]
MEDIA_FIXTURE = ROOT / "fixtures" / "media.render.v1.request.json"


def media_fixture():
    return json.loads(MEDIA_FIXTURE.read_text(encoding="utf-8"))


class OneShotBoundaryCrash:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.triggered = False

    def __call__(self, name, receipt) -> None:
        if name == self.boundary and not self.triggered:
            self.triggered = True
            raise OperationBoundaryCrash(name)


class ExternalOperationRecoveryTests(unittest.TestCase):
    def _setup_job(self, root: str, client, *, output_path=None, hook=None, retry_policy=None):
        fixture = media_fixture()
        store = JsonJobStore(Path(root) / "jobs")
        adapter = GenericResumableMediaAdapter(
            client=client,
            export_spec=fixture["exportSpec"],
            output_path=output_path or fixture["outputPath"],
            record_request_artifact=True,
        )
        orchestrator = Orchestrator(
            store,
            {
                JobStage.EDIT: adapter,
                JobStage.CRITIC: DeterministicTextAdapter("recovery-critic", "critique"),
            },
            retry_policy=retry_policy,
            operation_resume_policy=OperationResumePolicy(max_poll_attempts=10),
            operation_boundary_hook=hook,
        )
        if not (store.directory / "receipt-job.json").exists():
            orchestrator.create_job(
                "receipt-job",
                "external operation recovery",
                seed_artifacts=[
                    SeedArtifactInput("media_timeline_v1", fixture["timeline"])
                ],
            )
            job = store.load("receipt-job")
            job.stage_index = STAGE_ORDER.index(JobStage.EDIT)
            store.save(job)
        return store, orchestrator, adapter

    def _receipt(self, orchestrator, store):
        job = store.load("receipt-job")
        key = job.completed_idempotency_keys.get(JobStage.EDIT.value)
        if key is None:
            key = orchestrator._idempotency_key(job, JobStage.EDIT)
        return orchestrator.operation_ledger.load(
            job.id,
            JobStage.EDIT.value,
            key,
        )

    def test_crash_before_submit_persists_prepared_and_restart_submits_once(self):
        client = FakeResumableMediaOperationClient()
        with tempfile.TemporaryDirectory() as td:
            crash = OneShotBoundaryCrash("before_submit")
            store, orchestrator, _ = self._setup_job(td, client, hook=crash)

            with self.assertRaises(OperationBoundaryCrash):
                orchestrator.run_next("receipt-job")
            receipt = self._receipt(orchestrator, store)
            self.assertEqual(receipt.state, OperationState.PREPARED)
            self.assertEqual(client.submit_calls, 0)

            store, resumed, _ = self._setup_job(td, client)
            job = resumed.run_next("receipt-job")
            self.assertEqual(job.stage_index, STAGE_ORDER.index(JobStage.EDIT) + 1)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 1)
            self.assertEqual(
                self._receipt(resumed, store).state,
                OperationState.COMMITTED,
            )

    def test_restart_after_acceptance_polls_same_handle_without_resubmit(self):
        client = FakeResumableMediaOperationClient()
        with tempfile.TemporaryDirectory() as td:
            crash = OneShotBoundaryCrash("after_accept_persisted")
            store, orchestrator, _ = self._setup_job(td, client, hook=crash)

            with self.assertRaises(OperationBoundaryCrash):
                orchestrator.run_next("receipt-job")
            receipt = self._receipt(orchestrator, store)
            self.assertEqual(receipt.state, OperationState.ACCEPTED)
            accepted_handle = receipt.external_operation_id
            self.assertTrue(accepted_handle)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 0)

            store, resumed, _ = self._setup_job(td, client)
            job = resumed.run_next("receipt-job")
            self.assertEqual(job.stage_index, STAGE_ORDER.index(JobStage.EDIT) + 1)
            committed = self._receipt(resumed, store)
            self.assertEqual(committed.external_operation_id, accepted_handle)
            self.assertEqual(committed.state, OperationState.COMMITTED)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 1)

    def test_restart_after_result_persisted_commits_without_submit_or_poll(self):
        client = FakeResumableMediaOperationClient()
        with tempfile.TemporaryDirectory() as td:
            crash = OneShotBoundaryCrash("after_result_persisted")
            store, orchestrator, _ = self._setup_job(td, client, hook=crash)

            with self.assertRaises(OperationBoundaryCrash):
                orchestrator.run_next("receipt-job")
            receipt = self._receipt(orchestrator, store)
            self.assertEqual(receipt.state, OperationState.RESULT_OBTAINED)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 1)

            store, resumed, _ = self._setup_job(td, client)
            job = resumed.run_next("receipt-job")
            self.assertEqual(job.stage_index, STAGE_ORDER.index(JobStage.EDIT) + 1)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 1)
            self.assertEqual(
                self._receipt(resumed, store).state,
                OperationState.COMMITTED,
            )
            self.assertEqual(sum(a.kind == "media_plan" for a in job.artifacts), 1)

    def test_restart_after_artifact_commit_reconciles_receipt_without_provider_call(self):
        client = FakeResumableMediaOperationClient()
        with tempfile.TemporaryDirectory() as td:
            crash = OneShotBoundaryCrash("after_artifact_commit_before_receipt_commit")
            store, orchestrator, _ = self._setup_job(td, client, hook=crash)

            with self.assertRaises(OperationBoundaryCrash):
                orchestrator.run_next("receipt-job")
            job = store.load("receipt-job")
            self.assertEqual(job.stage_index, STAGE_ORDER.index(JobStage.EDIT) + 1)
            self.assertEqual(sum(a.kind == "media_plan" for a in job.artifacts), 1)
            receipt = self._receipt(orchestrator, store)
            self.assertEqual(receipt.state, OperationState.RESULT_OBTAINED)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 1)

            store, resumed, _ = self._setup_job(td, client)
            resumed.run_next("receipt-job")
            self.assertEqual(
                self._receipt(resumed, store).state,
                OperationState.COMMITTED,
            )
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 1)

    def test_duplicate_resume_allows_many_read_only_polls_and_one_submit(self):
        client = FakeResumableMediaOperationClient(pending_polls=2)
        with tempfile.TemporaryDirectory() as td:
            store, first, _ = self._setup_job(td, client)
            first_job = first.run_next("receipt-job")
            self.assertEqual(first_job.state, JobState.WAITING_RETRY)

            store, second, _ = self._setup_job(td, client)
            second_job = second.run_next("receipt-job")
            self.assertEqual(second_job.state, JobState.WAITING_RETRY)

            store, third, _ = self._setup_job(td, client)
            final_job = third.run_next("receipt-job")
            self.assertEqual(final_job.state, JobState.PENDING)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 3)
            receipt = self._receipt(third, store)
            self.assertEqual(receipt.poll_attempts, 3)
            self.assertEqual(receipt.state, OperationState.COMMITTED)

    def test_poll_timeout_uses_resume_policy_not_provider_retry_policy(self):
        client = FakeResumableMediaOperationClient(timeout_poll_numbers={1})
        with tempfile.TemporaryDirectory() as td:
            store, first, _ = self._setup_job(
                td,
                client,
                retry_policy=RetryPolicy(max_attempts=1),
            )
            timed_out = first.run_next("receipt-job")
            self.assertEqual(timed_out.state, JobState.WAITING_RETRY)
            self.assertIn("OperationPollTimeout", timed_out.last_error)
            self.assertEqual(client.submit_calls, 1)

            store, resumed, _ = self._setup_job(
                td,
                client,
                retry_policy=RetryPolicy(max_attempts=1),
            )
            completed = resumed.run_next("receipt-job")
            self.assertEqual(completed.state, JobState.PENDING)
            self.assertEqual(client.submit_calls, 1)
            self.assertEqual(client.poll_calls, 2)

    def test_conflicting_request_reusing_same_stage_key_fails_before_submit(self):
        client = FakeResumableMediaOperationClient()
        with tempfile.TemporaryDirectory() as td:
            crash = OneShotBoundaryCrash("before_submit")
            store, first, _ = self._setup_job(td, client, hook=crash)
            with self.assertRaises(OperationBoundaryCrash):
                first.run_next("receipt-job")
            self.assertEqual(client.submit_calls, 0)

            store, conflicting, _ = self._setup_job(
                td,
                client,
                output_path="round2-temp/conflicting-output.mp4",
            )
            job = conflicting.run_next("receipt-job")
            self.assertEqual(job.state, JobState.FAILED)
            self.assertIn("OperationConflictError", job.last_error)
            self.assertEqual(client.submit_calls, 0)

    def test_media_request_shape_remains_media_render_v1_dry_run(self):
        client = FakeResumableMediaOperationClient()
        fixture = media_fixture()
        with tempfile.TemporaryDirectory() as td:
            store, orchestrator, _ = self._setup_job(td, client)
            job = orchestrator.run_next("receipt-job")
            self.assertEqual(job.state, JobState.PENDING)
            self.assertEqual(client.submit_calls, 1)
            handle = next(iter(client._operations))
            request = client._operations[handle]["request"]
            self.assertEqual(
                set(request),
                {
                    "contractVersion",
                    "jobId",
                    "timeline",
                    "exportSpec",
                    "outputPath",
                    "dryRun",
                },
            )
            self.assertEqual(request["contractVersion"], "media.render.v1")
            self.assertEqual(request["timeline"], fixture["timeline"])
            self.assertEqual(request["exportSpec"], fixture["exportSpec"])
            self.assertIs(request["dryRun"], True)


if __name__ == "__main__":
    unittest.main()
