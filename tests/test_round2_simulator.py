from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.adapters import (
    DescriptVoiceAdapter,
    MetricoolPublishQueueAdapter,
    RealPublishingDisabled,
    RunwayAssetAdapter,
    VidIQAnalyticsAdapter,
    VidIQResearchAdapter,
)
from creator_orchestrator.demo import run_demo
from creator_orchestrator.lineage import LineageValidationError, validate_artifact_dag
from creator_orchestrator.models import Artifact, JobStage, JobState
from creator_orchestrator.ports import StepContext
from creator_orchestrator.sim_fakes import FakeDescript, FakeMetricool, FakeRunway, FakeVidIQ
from creator_orchestrator.simulator import (
    CampaignConfig,
    CampaignConfigError,
    CampaignRunner,
    load_campaign_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_FIXTURE = ROOT / "fixtures" / "campaign.autonomous.v2.json"
EXPECTED_DEMO = ROOT / "fixtures" / "campaign.autonomous.v2.expected.json"


def fixture_payload():
    return json.loads(CAMPAIGN_FIXTURE.read_text(encoding="utf-8"))


def one_cycle_config(*, failures=None, rejects=0, max_revisions=2):
    payload = fixture_payload()
    payload["campaignId"] = "one-cycle"
    payload["cycles"] = 1
    payload["failures"] = failures or {}
    payload["maxCriticRevisions"] = max_revisions
    payload["critic"]["rejectsByCycle"] = {"1": rejects} if rejects else {}
    return CampaignConfig.from_dict(payload)


class Round2CampaignTests(unittest.TestCase):
    def test_sample_campaign_runs_three_cycles_and_seeds_next_cycle(self):
        config = load_campaign_fixture(CAMPAIGN_FIXTURE)
        with tempfile.TemporaryDirectory() as td:
            runner = CampaignRunner(td, config)
            state = runner.run_to_terminal()
            self.assertEqual(state.status, "complete")
            self.assertEqual(state.completed_cycles, [1, 2, 3])
            self.assertIsNotNone(state.report_artifact)

            cycle1 = runner.job_store.load(state.cycle_job_ids["1"])
            cycle2 = runner.job_store.load(state.cycle_job_ids["2"])
            analytics1 = next(a for a in reversed(cycle1.artifacts) if a.kind == "analytics_feedback")
            growth2 = next(a for a in cycle2.artifacts if a.kind == "growth_feedback")
            self.assertEqual(growth2.metadata, state.feedback_by_cycle["1"])
            self.assertEqual(growth2.parents, (analytics1.id,))

            kinds = {a.kind for a in runner._all_job_artifacts(state)}
            self.assertTrue(
                {
                    "research",
                    "idea",
                    "script",
                    "asset_request",
                    "visual_asset",
                    "voice_request",
                    "voice",
                    "media_request",
                    "media_plan",
                    "critic_decision",
                    "publish_queue_item",
                    "analytics_feedback",
                    "growth_feedback",
                }.issubset(kinds)
            )
            report = state.report_artifact.metadata
            configured_failure_stages = {
                stage
                for stage_map in config.failures_by_cycle.values()
                for stage in stage_map
            }
            self.assertEqual(
                configured_failure_stages,
                {"research", "script", "assets", "voice", "media", "critic", "queue", "analytics"},
            )
            self.assertEqual(report["cycles"], 3)
            self.assertEqual(report["cycle_transitions"], 2)
            self.assertEqual(report["critic_rejects"], 2)
            self.assertEqual(report["retries"], 8)
            self.assertEqual(report["duplicate_events_suppressed"], 3)
            self.assertEqual(len(report["render_fingerprints"]), 5)
            self.assertEqual(len(report["simulated_performance_feedback"]), 3)

            combined = [*runner._all_job_artifacts(state), state.report_artifact]
            lineage = validate_artifact_dag(combined)
            self.assertEqual(lineage.node_count, len(combined))

    def test_runner_can_be_reconstructed_before_every_stage(self):
        config = one_cycle_config()
        with tempfile.TemporaryDirectory() as td:
            seen: set[JobStage] = set()
            state = CampaignRunner(td, config).initialize()
            for _ in range(80):
                runner = CampaignRunner(td, config)
                state = runner.initialize()
                if state.status == "complete":
                    break
                job_id = state.cycle_job_ids.get("1")
                if job_id:
                    job = runner.job_store.load(job_id)
                    if job.stage is not None:
                        seen.add(job.stage)
                runner.step()
            self.assertEqual(state.status, "complete")
            self.assertEqual(seen, set(JobStage))

    def test_critic_revision_budget_is_bounded(self):
        config = one_cycle_config(rejects=5, max_revisions=2)
        with tempfile.TemporaryDirectory() as td:
            runner = CampaignRunner(td, config)
            state = runner.run_to_terminal(max_steps=100)
            self.assertEqual(state.status, "failed")
            self.assertIn("critic revision budget exhausted", state.last_error)
            job = runner.job_store.load(state.cycle_job_ids["1"])
            rejects = [
                a
                for a in job.artifacts
                if a.kind == "critic_decision" and a.metadata["decision"] == "reject"
            ]
            self.assertEqual(len(rejects), 3)

    def test_recovery_scenarios_resume_from_persisted_state(self):
        scenarios = [
            ("research", {"1": {"research": [1]}}, 0),
            ("media", {"1": {"media": [1]}}, 0),
            ("queue", {"1": {"queue": [1]}}, 0),
            ("critic-rewind", {}, 1),
        ]
        for name, failures, rejects in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                config = one_cycle_config(failures=failures, rejects=rejects)
                runner = CampaignRunner(td, config)
                runner.initialize()
                observed_recovery_point = False
                for _ in range(80):
                    state = runner.step()
                    job_id = state.cycle_job_ids.get("1")
                    if job_id:
                        job = runner.job_store.load(job_id)
                        if name != "critic-rewind" and job.state == JobState.WAITING_RETRY:
                            observed_recovery_point = True
                            break
                        if name == "critic-rewind" and state.handled_critic_ids:
                            observed_recovery_point = True
                            break
                self.assertTrue(observed_recovery_point)
                resumed = CampaignRunner(td, config).run_to_terminal()
                self.assertEqual(resumed.status, "complete")

    def test_adapter_contract_harnesses_are_idempotent_and_dry_run_only(self):
        script = Artifact(id="script-1", kind="script", uri="sim://script/1", producer="test")

        runway = FakeRunway()
        runway_adapter = RunwayAssetAdapter(runway)
        runway_context = StepContext("job", "topic", JobStage.ASSETS, "runway-key", (script,))
        first_runway = runway_adapter.execute(runway_context)
        second_runway = runway_adapter.execute(runway_context)
        self.assertEqual(first_runway.artifacts[0].id, second_runway.artifacts[0].id)
        self.assertEqual(first_runway.artifacts[0].metadata, second_runway.artifacts[0].metadata)
        self.assertEqual(len(runway.calls), 1)

        descript = FakeDescript()
        voice_adapter = DescriptVoiceAdapter(descript)
        voice_context = StepContext("job", "topic", JobStage.VOICE, "voice-key", (script,))
        first_voice = voice_adapter.execute(voice_context)
        second_voice = voice_adapter.execute(voice_context)
        self.assertEqual(first_voice.artifacts[0].id, second_voice.artifacts[0].id)
        self.assertEqual(first_voice.artifacts[0].metadata, second_voice.artifacts[0].metadata)
        self.assertEqual(len(descript.calls), 1)

        vidiq = FakeVidIQ(1)
        research = VidIQResearchAdapter(vidiq)
        analytics = VidIQAnalyticsAdapter(vidiq)
        research.execute(StepContext("job", "topic", JobStage.RESEARCH, "research-key", ()))
        research.execute(StepContext("job", "topic", JobStage.RESEARCH, "research-key", ()))
        analytics.execute(StepContext("job", "topic", JobStage.ANALYTICS, "analytics-key", ()))
        analytics.execute(StepContext("job", "topic", JobStage.ANALYTICS, "analytics-key", ()))
        self.assertEqual(len(vidiq.calls), 2)

        metricool = FakeMetricool()
        queue = MetricoolPublishQueueAdapter(metricool, dry_run=True)
        queue_context = StepContext("job", "topic", JobStage.PUBLISH_QUEUE, "queue-key", ())
        first_queue = queue.execute(queue_context)
        second_queue = queue.execute(queue_context)
        self.assertEqual(first_queue.artifacts[0].id, second_queue.artifacts[0].id)
        self.assertEqual(first_queue.artifacts[0].metadata, second_queue.artifacts[0].metadata)
        self.assertEqual(len(metricool.calls), 1)
        with self.assertRaises(RealPublishingDisabled):
            metricool.queue_post(
                manifest={"action": "queue_only"},
                idempotency_key="live",
                dry_run=False,
            )
        with self.assertRaises(RealPublishingDisabled):
            MetricoolPublishQueueAdapter(metricool, dry_run=False).execute(queue_context)

    def test_lineage_validator_detects_cycles(self):
        a = Artifact(id="a", kind="x", uri="sim://a", producer="test", parents=("b",))
        b = Artifact(id="b", kind="x", uri="sim://b", producer="test", parents=("a",))
        with self.assertRaises(LineageValidationError):
            validate_artifact_dag([a, b])

    def test_simulator_config_has_no_live_publish_escape_hatch(self):
        payload = fixture_payload()
        payload["livePublishing"] = True
        with self.assertRaises(CampaignConfigError):
            CampaignConfig.from_dict(payload)
        payload = fixture_payload()
        payload["media"]["live"] = True
        with self.assertRaises(CampaignConfigError):
            CampaignConfig.from_dict(payload)

    def test_demo_is_deterministic_and_matches_expected_fixture(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = run_demo(CAMPAIGN_FIXTURE, first)
            right = run_demo(CAMPAIGN_FIXTURE, second)
            self.assertEqual(left, right)
            expected = json.loads(EXPECTED_DEMO.read_text(encoding="utf-8"))
            self.assertEqual(left, expected)


if __name__ == "__main__":
    unittest.main()
