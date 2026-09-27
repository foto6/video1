import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.adapters import (
    DeterministicTextAdapter,
    MetricoolPublishQueueAdapter,
    RealPublishingDisabled,
)
from creator_orchestrator.defaults import build_default_orchestrator
from creator_orchestrator.models import Evaluation, JobStage, JobState, StepResult
from creator_orchestrator.orchestrator import JsonJobStore, Orchestrator, RetryPolicy, RetryableStepError
from creator_orchestrator.ports import StepContext


class FlakyAdapter:
    name = "flaky"

    def __init__(self):
        self.calls = 0

    def execute(self, context: StepContext) -> StepResult:
        self.calls += 1
        if self.calls == 1:
            raise RetryableStepError("temporary provider failure")
        return DeterministicTextAdapter("flaky", "research").execute(context)


class RejectingHook:
    name = "quality-gate"

    def evaluate(self, job, stage, result):
        return Evaluation(hook=self.name, approved=False, score=0.1, notes="below threshold")


class CreatorOrchestratorTests(unittest.TestCase):
    def test_default_pipeline_reaches_complete_and_records_lineage(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = build_default_orchestrator(store)
            orchestrator.create_job("job-1", "durable creator agents")

            job = orchestrator.run_to_terminal("job-1")
            self.assertEqual(job.state, JobState.COMPLETE)
            self.assertEqual(job.stage_index, 9)
            self.assertEqual(len(job.artifacts), 9)
            publish = next(a for a in job.artifacts if a.kind == "publish_manifest")
            self.assertEqual(publish.metadata["action"], "queue_only")
            self.assertEqual(publish.metadata["mode"], "dry-run")
            self.assertTrue(any(a.parents for a in job.artifacts[1:]))

    def test_retryable_failure_persists_and_then_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            flaky = FlakyAdapter()
            orchestrator = Orchestrator(
                store,
                {JobStage.RESEARCH: flaky},
                retry_policy=RetryPolicy(max_attempts=2),
            )
            orchestrator.create_job("job-2", "retry")
            first = orchestrator.run_next("job-2")
            self.assertEqual(first.state, JobState.WAITING_RETRY)
            second = orchestrator.run_next("job-2")
            self.assertEqual(second.stage_index, 1)
            self.assertEqual(second.attempts["research"], 2)

    def test_terminal_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = build_default_orchestrator(store)
            orchestrator.create_job("job-3", "idempotency")
            complete = orchestrator.run_to_terminal("job-3")
            artifact_ids = [a.id for a in complete.artifacts]
            again = orchestrator.run_to_terminal("job-3")
            self.assertEqual([a.id for a in again.artifacts], artifact_ids)
            self.assertEqual(again.attempts, complete.attempts)

    def test_real_publish_is_disabled(self):
        adapter = MetricoolPublishQueueAdapter(dry_run=False)
        context = StepContext(
            job_id="job-4",
            topic="safety",
            stage=JobStage.PUBLISH_QUEUE,
            idempotency_key="key",
            artifacts=(),
        )
        with self.assertRaises(RealPublishingDisabled):
            adapter.execute(context)

    def test_json_store_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = build_default_orchestrator(store)
            created = orchestrator.create_job("job-5", "durability")
            loaded = store.load(created.id)
            self.assertEqual(loaded.id, created.id)
            self.assertEqual(loaded.state, JobState.PENDING)
            self.assertTrue((Path(td) / "job-5.json").exists())

    def test_evaluation_hook_can_block_progress(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = Orchestrator(
                store,
                {JobStage.RESEARCH: DeterministicTextAdapter("research", "research")},
                evaluation_hooks=[RejectingHook()],
            )
            orchestrator.create_job("job-6", "quality")
            job = orchestrator.run_next("job-6")
            self.assertEqual(job.state, JobState.FAILED)
            self.assertIn("quality-gate", job.last_error)
            self.assertEqual(job.stage_index, 0)


if __name__ == "__main__":
    unittest.main()
