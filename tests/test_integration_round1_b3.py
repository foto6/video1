from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.adapters import (
    DeterministicTextAdapter,
    MetricoolPublishQueueAdapter,
    RealPublishingDisabled,
)
from creator_orchestrator.defaults import (
    build_default_orchestrator,
    build_media_planning_orchestrator,
)
from creator_orchestrator.integration import (
    GrowthFeedbackValidationError,
    MediaIntegrationError,
    SeedArtifactInput,
)
from creator_orchestrator.models import Artifact, JobStage, JobState, StepResult
from creator_orchestrator.orchestrator import JsonJobStore, Orchestrator
from creator_orchestrator.ports import StepContext

ROOT = Path(__file__).resolve().parents[1]
GROWTH_FIXTURE = ROOT / "fixtures" / "creator_feedback_v1.json"
MEDIA_FIXTURE = ROOT / "fixtures" / "media.render.v1.request.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class RecordingResearchAdapter:
    name = "recording-research"

    def __init__(self):
        self.contexts = []

    def execute(self, context: StepContext) -> StepResult:
        self.contexts.append(context)
        return DeterministicTextAdapter(self.name, "research").execute(context)


class FakeMediaClient:
    def __init__(self):
        self.requests = []

    def plan_render(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        return {
            "contractVersion": "media.render.v1",
            "jobId": request["jobId"],
            "dryRun": True,
            "validation": {"ok": True, "timelineVersion": 1},
            "renderFingerprint": "fixture-fingerprint-b3",
            "command": ["ffmpeg", "-version"],
        }


class IntegrationRound1B3Tests(unittest.TestCase):
    def test_growth_feedback_seed_validates_persists_and_is_visible_at_stage_zero(self):
        feedback = load_json(GROWTH_FIXTURE)
        caller_copy = json.loads(json.dumps(feedback))

        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            recording = RecordingResearchAdapter()
            orchestrator = Orchestrator(store, {JobStage.RESEARCH: recording})
            created = orchestrator.create_job(
                "growth-seeded",
                "seeded research",
                seed_artifacts=[SeedArtifactInput("growth_feedback", feedback)],
            )

            feedback["score"] = 0.0
            loaded = store.load(created.id)
            self.assertEqual(len(loaded.artifacts), 1)
            seed = loaded.artifacts[0]
            self.assertEqual(seed.kind, "growth_feedback")
            self.assertEqual(seed.metadata, caller_copy)

            advanced = orchestrator.run_next(created.id)
            self.assertEqual(advanced.stage_index, 1)
            self.assertEqual(recording.contexts[0].artifacts[0].id, seed.id)
            self.assertEqual(recording.contexts[0].artifacts[0].metadata, caller_copy)

    def test_growth_feedback_unknown_version_is_rejected_before_job_persistence(self):
        feedback = load_json(GROWTH_FIXTURE)
        feedback["contract_version"] = "2.0"

        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = build_default_orchestrator(store)
            with self.assertRaises(GrowthFeedbackValidationError):
                orchestrator.create_job(
                    "bad-growth",
                    "invalid seed",
                    seed_artifacts=[SeedArtifactInput("growth_feedback", feedback)],
                )
            self.assertFalse((Path(td) / "bad-growth.json").exists())

    def test_seed_artifacts_change_stage_zero_idempotency_lineage(self):
        feedback = load_json(GROWTH_FIXTURE)
        with tempfile.TemporaryDirectory() as seeded_td, tempfile.TemporaryDirectory() as plain_td:
            seeded_adapter = RecordingResearchAdapter()
            plain_adapter = RecordingResearchAdapter()
            seeded = Orchestrator(JsonJobStore(seeded_td), {JobStage.RESEARCH: seeded_adapter})
            plain = Orchestrator(JsonJobStore(plain_td), {JobStage.RESEARCH: plain_adapter})

            seeded.create_job(
                "same-job",
                "same topic",
                seed_artifacts=[SeedArtifactInput("growth_feedback", feedback)],
            )
            plain.create_job("same-job", "same topic")
            seeded.run_next("same-job")
            plain.run_next("same-job")

            self.assertNotEqual(
                seeded_adapter.contexts[0].idempotency_key,
                plain_adapter.contexts[0].idempotency_key,
            )

    def test_seeded_media_timeline_is_sent_unchanged_in_exact_b2_request_and_plan_is_recorded(self):
        fixture = load_json(MEDIA_FIXTURE)
        fake = FakeMediaClient()

        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = build_media_planning_orchestrator(
                store,
                media_client=fake,
                export_spec=fixture["exportSpec"],
                output_path=fixture["outputPath"],
            )
            orchestrator.create_job(
                fixture["jobId"],
                "round 1 media integration",
                seed_artifacts=[SeedArtifactInput("media_timeline_v1", fixture["timeline"])],
            )

            for _ in range(6):
                job = orchestrator.run_next(fixture["jobId"])
            self.assertEqual(job.stage_index, 6)
            self.assertEqual(len(fake.requests), 1)

            request = fake.requests[0]
            self.assertEqual(
                set(request),
                {"contractVersion", "jobId", "timeline", "exportSpec", "outputPath", "dryRun"},
            )
            self.assertEqual(request["contractVersion"], "media.render.v1")
            self.assertEqual(request["jobId"], fixture["jobId"])
            self.assertEqual(request["timeline"], fixture["timeline"])
            self.assertEqual(request["exportSpec"], fixture["exportSpec"])
            self.assertEqual(request["outputPath"], fixture["outputPath"])
            self.assertIs(request["dryRun"], True)

            persisted = store.load(fixture["jobId"])
            timeline_seed = next(a for a in persisted.artifacts if a.kind == "media_timeline_v1")
            media_plan = next(a for a in persisted.artifacts if a.kind == "media_plan")
            self.assertEqual(media_plan.metadata["renderFingerprint"], "fixture-fingerprint-b3")
            self.assertEqual(media_plan.parents, (timeline_seed.id,))

    def test_media_adapter_refuses_to_synthesize_timeline_from_generic_artifacts(self):
        fixture = load_json(MEDIA_FIXTURE)
        fake = FakeMediaClient()
        adapter = build_media_planning_orchestrator(
            JsonJobStore(tempfile.mkdtemp()),
            media_client=fake,
            export_spec=fixture["exportSpec"],
            output_path=fixture["outputPath"],
        ).adapters[JobStage.EDIT]
        context = StepContext(
            job_id="missing-timeline",
            topic="no synthetic metadata",
            stage=JobStage.EDIT,
            idempotency_key="key",
            artifacts=(
                Artifact(
                    id="asset-1",
                    kind="visual_asset",
                    uri="memory://asset",
                    producer="test",
                    metadata={"unknown_duration": True},
                ),
            ),
        )
        with self.assertRaises(MediaIntegrationError):
            adapter.execute(context)
        self.assertEqual(fake.requests, [])

    def test_default_pipeline_remains_nine_stages_and_real_publish_stays_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonJobStore(td)
            orchestrator = build_default_orchestrator(store)
            orchestrator.create_job("unchanged-default", "default")
            job = orchestrator.run_to_terminal("unchanged-default")
            self.assertEqual(job.state, JobState.COMPLETE)
            self.assertEqual(job.stage_index, 9)
            self.assertEqual(len(job.artifacts), 9)
            self.assertEqual(sum(a.kind == "media_plan" for a in job.artifacts), 0)

        adapter = MetricoolPublishQueueAdapter(dry_run=False)
        with self.assertRaises(RealPublishingDisabled):
            adapter.execute(
                StepContext(
                    job_id="publish-blocked",
                    topic="safety",
                    stage=JobStage.PUBLISH_QUEUE,
                    idempotency_key="key",
                    artifacts=(),
                )
            )


if __name__ == "__main__":
    unittest.main()
