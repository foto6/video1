from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import batch_campaign as r14
from creator_orchestrator import integration_acceptance as r13
from creator_orchestrator import publish_providers as r12


class BatchCampaignR14Tests(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "batch_size": 3,
            "platform_mix": {
                "instagram_reels": 1,
                "tiktok": 1,
                "youtube_shorts": 1,
            },
            "max_concurrency": {
                "generation": 2,
                "media": 1,
                "provider": 1,
            },
            "budget": {
                "generation_units": 20.0,
                "render_seconds": 120.0,
                "provider_actions": 20.0,
            },
            "publish_window_start": "2026-10-01T00:00:00Z",
            "publish_window_end": "2026-10-01T00:10:00Z",
            "stagger_seconds": 1.0,
        }
        values.update(overrides)
        return r14.BatchCampaignConfig(**values).validate()

    def brief(self):
        return {
            "goal": "Produce a distinct short-form batch",
            "topic": "editing systems",
            "audience": "creators",
        }

    def ledger(self, path: Path, *, config=None, advisory=None):
        return r14.BatchCampaignLedger(
            path,
            campaign_id="batch-test",
            brief=self.brief(),
            config=config or self.config(),
            growth_advisory=advisory,
        )

    def test_r13_and_growth_pins_remain_exact(self):
        self.assertEqual(
            r14.CREATOR_R13_BASE_SHA,
            "e8bc2ed365d6ca4c512079ff9cccd7543575f052",
        )
        source = r13.growth_r11_source_pin()
        self.assertEqual(
            source["producerSha"],
            "c4ed94d3e76b75d36bf8cc8280f6937f455133a6",
        )
        self.assertEqual(
            source["manifestBlobSha"],
            "8b47817cb344c4a1670d338fca351c1056e8ba6f",
        )

    def test_config_enforces_batch_mix_schedule_and_hard_limits(self):
        with self.assertRaises(r14.BatchCampaignError):
            self.config(platform_mix={"instagram_reels": 2})
        with self.assertRaises(r14.BatchCampaignError):
            self.config(
                publish_window_end="2026-10-01T00:00:01Z",
                stagger_seconds=1.0,
            )
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(max_concurrency={"generation": 1, "media": 1, "provider": 1})
            ledger = self.ledger(Path(temp) / "campaign.jsonl", config=config)
            ledger.begin_operation(item_id=None, kind="generation", operation_key="g1")
            with self.assertRaises(r14.ConcurrencyLimitExceeded):
                ledger.begin_operation(item_id=None, kind="generation", operation_key="g2")
            ledger.finish_operation(operation_key="g1", outcome="done")
            ledger.begin_operation(item_id=None, kind="generation", operation_key="g2")
            self.assertEqual(ledger.max_observed_concurrency["generation"], 1)

    def test_semantic_concept_script_dedup_and_hook_diversity(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "campaign.jsonl")
            synth = r14.DeterministicBatchSynthesizer()
            runner = r14.BatchCampaignRunner(
                ledger=ledger,
                work_dir=temp,
                media_pin=r14.synthetic_media_pin(),
                allow_synthetic_media=True,
            )
            items = runner.plan_concepts(synth, candidate_count=3, inject_duplicates=True)
            self.assertEqual(len(items), 3)
            self.assertGreaterEqual(ledger.summary()["rejectedCandidateCount"], 1)
            signatures = {item["concept"]["hookSignature"] for item in items}
            self.assertEqual(len(signatures), 3)

            runner.generate_script_and_assets(items[0]["itemId"], synth)
            duplicate_script = dict(ledger._item(items[0]["itemId"])["script"])
            with self.assertRaises(r14.SemanticDuplicate):
                ledger.record_script(items[1]["itemId"], duplicate_script)

    def test_pause_resume_cancel_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "campaign.jsonl"
            ledger = self.ledger(path)
            ledger.pause()
            reopened = self.ledger(path)
            self.assertEqual(reopened.control_state, "paused")
            with self.assertRaises(r14.CampaignPaused):
                reopened.reserve_budget(
                    "generation_units",
                    1,
                    operation_key="paused-work",
                    detail="must-not-run",
                )
            reopened.resume()
            reopened.reserve_budget(
                "generation_units",
                1,
                operation_key="resumed-work",
                detail="allowed",
            )
            reopened.cancel()
            canceled = self.ledger(path)
            self.assertEqual(canceled.control_state, "canceled")
            with self.assertRaises(r14.CampaignCanceled):
                canceled.begin_operation(
                    item_id=None,
                    kind="generation",
                    operation_key="after-cancel",
                )
            with self.assertRaises(r14.CampaignCanceled):
                canceled.resume()

    def test_budget_is_reserved_durably_before_work_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(
                budget={
                    "generation_units": 1.0,
                    "render_seconds": 30.0,
                    "provider_actions": 1.0,
                }
            )
            path = Path(temp) / "campaign.jsonl"
            ledger = self.ledger(path, config=config)
            self.assertEqual(
                ledger.reserve_budget(
                    "generation_units",
                    1,
                    operation_key="g1",
                    detail="first",
                ),
                "committed",
            )
            self.assertEqual(
                ledger.reserve_budget(
                    "generation_units",
                    1,
                    operation_key="g1",
                    detail="first",
                ),
                "duplicate",
            )
            with self.assertRaises(r14.BudgetExceeded):
                ledger.reserve_budget(
                    "generation_units",
                    0.01,
                    operation_key="g2",
                    detail="would-overrun",
                )
            reopened = self.ledger(path, config=config)
            self.assertEqual(reopened.budget_spent["generation_units"], 1.0)

    def test_missing_media_pin_blocks_before_render_budget_or_side_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "campaign.jsonl")
            synth = r14.DeterministicBatchSynthesizer()
            runner = r14.BatchCampaignRunner(
                ledger=ledger,
                work_dir=temp,
                media_pin=None,
            )
            items = runner.plan_concepts(synth, candidate_count=3)
            runner.generate_script_and_assets(items[0]["itemId"], synth)
            provider = r14.TerminalMediaFailureProvider()
            state = runner.render_item(
                items[0]["itemId"],
                media_provider=provider,
                synthesizer=synth,
            )
            self.assertEqual(state, "blocked_media")
            self.assertEqual(provider.submit_calls, 0)
            self.assertEqual(ledger.budget_spent["render_seconds"], 0.0)
            self.assertIn(
                "BLOCKED_MEDIA",
                ledger._item(items[0]["itemId"])["media"]["reason"],
            )

    def test_growth_seed_is_advisory_and_cannot_authorize_publish(self):
        advisory = {
            "contract_version": "growth.reels_next_cycle_seed.v1",
            "source_class": "platform_export",
            "recommendations": [{"action": "use a faster hook"}],
            "authority": {
                "publish_authorized": True,
                "release_authorized": True,
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "campaign.jsonl", advisory=advisory)
            self.assertFalse(ledger.growth_advisory["publicationAuthorityAccepted"])
            self.assertTrue(ledger.growth_advisory["publicationAuthorityIgnored"])
            synth = r14.DeterministicBatchSynthesizer()
            runner = r14.BatchCampaignRunner(
                ledger=ledger,
                work_dir=temp,
                media_pin=r14.synthetic_media_pin(),
                allow_synthetic_media=True,
            )
            items = runner.plan_concepts(synth, candidate_count=3)
            item_id = items[0]["itemId"]
            runner.generate_script_and_assets(item_id, synth)
            media = r13.MockMediaAcceptanceProvider(r14.synthetic_media_pin())
            runner.render_item(item_id, media_provider=media, synthesizer=synth)
            runner.qa_item(item_id, passed=True)
            self.assertEqual(ledger._item(item_id)["state"], "awaiting_release")
            with self.assertRaises(r14.ReleaseRequired):
                runner.publish_item(
                    item_id,
                    provider=r12.InstagramReelsMockProvider(),
                    now=ledger._item(item_id)["schedule"]["plannedAt"],
                )

    def test_publish_window_blocks_early_or_outside_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "campaign.jsonl")
            synth = r14.DeterministicBatchSynthesizer()
            runner = r14.BatchCampaignRunner(
                ledger=ledger,
                work_dir=temp,
                media_pin=r14.synthetic_media_pin(),
                allow_synthetic_media=True,
            )
            items = runner.plan_concepts(synth, candidate_count=3)
            second = items[1]
            with self.assertRaises(r14.PublishWindowBlocked):
                ledger.assert_publish_window(
                    second["itemId"],
                    now="2026-10-01T00:00:00Z",
                )
            with self.assertRaises(r14.PublishWindowBlocked):
                ledger.assert_publish_window(
                    second["itemId"],
                    now="2026-10-01T00:11:00Z",
                )
            ledger.assert_publish_window(
                second["itemId"],
                now=second["schedule"]["plannedAt"],
            )

    def test_lost_publish_ack_restarts_without_second_logical_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "campaign.jsonl"
            ledger = self.ledger(path)
            pin = r14.synthetic_media_pin()
            synth = r14.DeterministicBatchSynthesizer()
            runner = r14.BatchCampaignRunner(
                ledger=ledger,
                work_dir=temp,
                media_pin=pin,
                allow_synthetic_media=True,
            )
            items = runner.plan_concepts(synth, candidate_count=3)
            item = items[0]
            item_id = item["itemId"]
            runner.generate_script_and_assets(item_id, synth)
            runner.render_item(
                item_id,
                media_provider=r13.MockMediaAcceptanceProvider(pin),
                synthesizer=synth,
            )
            runner.qa_item(item_id, passed=True)
            runner.authorize_item(item_id)
            provider = r12.InstagramReelsMockProvider(crash_after_effect_once=True)
            with self.assertRaises(Exception) as caught:
                runner.publish_item(
                    item_id,
                    provider=provider,
                    now=item["schedule"]["plannedAt"],
                )
            self.assertEqual(
                caught.exception.__class__.__name__,
                "InjectedCrash",
            )

            restarted_ledger = self.ledger(path)
            restarted = r14.BatchCampaignRunner(
                ledger=restarted_ledger,
                work_dir=temp,
                media_pin=pin,
                allow_synthetic_media=True,
            )
            result = restarted.publish_item(
                item_id,
                provider=provider,
                now=item["schedule"]["plannedAt"],
            )
            self.assertEqual(result["state"], "published")
            self.assertEqual(provider.accepted_effects, 1)
            self.assertEqual(provider.submit_calls, 1)
            self.assertEqual(
                restarted_ledger._item(item_id)["state"],
                "analytics_pending",
            )

    def test_deterministic_12_reel_campaign_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r14.run_synthetic_12_campaign(temp)
        self.assertEqual(report["contractVersion"], r14.BATCH_REPORT_VERSION)
        self.assertEqual(report["batchSize"], 12)
        self.assertEqual(report["itemCount"], 12)
        self.assertEqual(
            report["states"],
            {
                "ready": 1,
                "blocked_media": 1,
                "qa_failed": 1,
                "awaiting_release": 1,
                "published": 7,
                "analytics_pending": 1,
            },
        )
        replay = report["syntheticReplay"]
        self.assertEqual(replay["candidateCountWithInjectedDuplicates"], 14)
        self.assertEqual(replay["duplicateCandidatesRejected"], 2)
        self.assertEqual(replay["mediaTerminalFailures"], 1)
        self.assertEqual(replay["qaFailures"], 1)
        self.assertEqual(replay["lostPublishAcknowledgementRestarts"], 1)
        self.assertEqual(replay["publishLogicalEffects"], 8)
        self.assertEqual(replay["publishSubmitCalls"], 8)
        self.assertEqual(replay["mediaLogicalEffects"], 12)
        self.assertFalse(report["growthAdvisory"]["publicationAuthorityAccepted"])
        self.assertTrue(report["growthAdvisory"]["publicationAuthorityIgnored"])
        self.assertFalse(report["livePublishing"])
        self.assertFalse(report["credentialsPresent"])
        self.assertLessEqual(report["maxObservedConcurrency"]["generation"], 3)
        self.assertLessEqual(report["maxObservedConcurrency"]["media"], 2)
        self.assertLessEqual(report["maxObservedConcurrency"]["provider"], 2)
        for category, values in report["budget"].items():
            with self.subTest(category=category):
                self.assertLessEqual(values["spent"], values["ceiling"])


if __name__ == "__main__":
    unittest.main()
