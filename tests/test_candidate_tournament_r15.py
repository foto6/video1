from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import batch_campaign as r14
from creator_orchestrator import candidate_tournament as r15


class CandidateTournamentR15Tests(unittest.TestCase):
    def creative_item(self):
        return {
            "campaignId": "campaign-r15-test",
            "itemId": "item-r15-test",
            "platform": "instagram_reels",
            "conceptDigest": "1" * 64,
            "scriptDigest": "2" * 64,
            "assetPlanDigest": "3" * 64,
            "growthAdvisoryDigest": "4" * 64,
        }

    def ledger(
        self,
        path: Path,
        *,
        config=None,
        allow_synthetic=True,
    ):
        return r15.CandidateTournamentLedger(
            path,
            tournament_id="tournament-r15-test",
            creative_item=self.creative_item(),
            config=config or r15.default_config(),
            media_pin=None,
            allow_synthetic_fixture=allow_synthetic,
        )

    def make_batch(self, root: Path, *, render_budget=180.0):
        config = r14.BatchCampaignConfig(
            batch_size=1,
            platform_mix={
                "instagram_reels": 1,
                "tiktok": 0,
                "youtube_shorts": 0,
            },
            max_concurrency={
                "generation": 2,
                "media": 2,
                "provider": 1,
            },
            budget={
                "generation_units": 20.0,
                "render_seconds": render_budget,
                "provider_actions": 20.0,
            },
            publish_window_start="2026-10-01T00:00:00Z",
            publish_window_end="2026-10-01T00:10:00Z",
            stagger_seconds=1.0,
        ).validate()
        ledger = r14.BatchCampaignLedger(
            root / "batch.jsonl",
            campaign_id="batch-r15-test",
            brief={
                "goal": "Run an edit tournament",
                "topic": "candidate editing",
                "audience": "creators",
            },
            config=config,
        )
        runner = r14.BatchCampaignRunner(
            ledger=ledger,
            work_dir=root,
            media_pin=None,
            allow_synthetic_media=True,
        )
        synth = r14.DeterministicBatchSynthesizer()
        item = runner.plan_concepts(
            synth,
            candidate_count=1,
        )[0]
        runner.generate_script_and_assets(item["itemId"], synth)
        return runner, synth, item["itemId"]

    def test_media_r13_production_gate_accepts_exact_green_compat_bundle(self):
        readiness = r15.media_r13_readiness()
        self.assertEqual(readiness["state"], "READY_MEDIA_R13")
        self.assertTrue(readiness["productionMediaReady"])
        self.assertEqual(
            readiness["acceptedPin"]["producerSha"],
            "ad4e0ba487a3cabc84dd339d412e19a0db0f9add",
        )
        self.assertEqual(readiness["ciRunId"], "36801556474")
        self.assertEqual(readiness["ciConclusion"], "success")
        self.assertEqual(
            readiness["acceptedPin"]["compatibilityManifestBlobSha"],
            "b750b347f6c6a7a2398e47e53e166f5fb1c72781",
        )
        self.assertTrue(readiness["oldFailedMediaR12Rejected"])
        self.assertEqual(
            readiness["oldFailedMediaR12Sha"],
            "98f298b88faaef106fb412712d6c9824e2b926d9",
        )
        self.assertFalse(readiness["livePublishingEnabled"])

    def test_variant_count_and_media_concurrency_are_hard_bounded(self):
        with self.assertRaises(r15.CandidateTournamentError):
            r15.TournamentConfig(
                variant_count=9,
                max_variants=9,
                max_concurrency=1,
                render_budget_seconds=270,
                media_action_budget=9,
            ).validate()

        config = r15.TournamentConfig(
            variant_count=2,
            max_variants=2,
            max_concurrency=1,
            render_budget_seconds=60,
            media_action_budget=2,
            estimated_render_seconds=30,
            min_valid_candidates=1,
        ).validate()
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(
                Path(temp) / "tournament.jsonl",
                config=config,
            )
            candidates = ledger.plan_candidates(
                r15.default_four_variants()[:2]
            )
            ledger.reserve_candidate_budget(candidates[0]["candidateId"])
            ledger.begin_media(candidates[0]["candidateId"])
            ledger.reserve_candidate_budget(candidates[1]["candidateId"])
            with self.assertRaises(r15.TournamentConcurrencyExceeded):
                ledger.begin_media(candidates[1]["candidateId"])
            self.assertEqual(ledger.max_observed_concurrency, 1)

    def test_four_candidate_fixture_has_required_gate_outcomes_and_winner(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r15.run_deterministic_replay(temp)
        self.assertEqual(report["state"], "SYNTHETIC_REPLAY_GREEN")
        self.assertEqual(report["candidateCount"], 4)
        self.assertEqual(report["technicalQaFailures"], 1)
        self.assertEqual(report["guardrailFailures"], 1)
        self.assertEqual(report["validCandidates"], 2)
        self.assertEqual(report["winnerOrdinal"], 3)
        self.assertFalse(report["productionReadinessClaim"])
        self.assertEqual(report["lostAcknowledgementRestarts"], 1)
        self.assertEqual(report["mediaLogicalEffects"], 4)
        self.assertEqual(report["mediaSubmitCalls"], 4)

    def test_technical_qa_failure_is_rejected_before_creative_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "tournament.jsonl")
            candidates = ledger.plan_candidates(r15.default_four_variants())
            provider = r15.MockMediaR12TournamentProvider()
            runner = r15.CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            evaluation = runner.process_candidate(
                candidates[0]["candidateId"]
            )
        self.assertEqual(evaluation["state"], "rejected_technical")
        self.assertFalse(evaluation["creativeComparisonPerformed"])
        self.assertIsNone(evaluation["preferenceScore"])
        self.assertFalse(evaluation["technicalQaPassed"])

    def test_over_editing_guardrail_rejects_before_heuristic_scoring(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "tournament.jsonl")
            candidates = ledger.plan_candidates(r15.default_four_variants())
            provider = r15.MockMediaR12TournamentProvider()
            runner = r15.CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            evaluation = runner.process_candidate(
                candidates[1]["candidateId"]
            )
        self.assertEqual(evaluation["state"], "rejected_guardrail")
        self.assertTrue(evaluation["technicalQaPassed"])
        self.assertFalse(evaluation["hardGuardrailsPassed"])
        self.assertIn(
            "cutRatePerSecond",
            evaluation["hardGateFailures"],
        )
        self.assertFalse(evaluation["creativeComparisonPerformed"])
        self.assertIsNone(evaluation["preferenceScore"])

    def test_valid_scores_are_source_bound_heuristics_not_quality_certainty(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "tournament.jsonl")
            candidates = ledger.plan_candidates(r15.default_four_variants())
            provider = r15.MockMediaR12TournamentProvider()
            runner = r15.CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            third = runner.process_candidate(candidates[2]["candidateId"])
            fourth = runner.process_candidate(candidates[3]["candidateId"])
        self.assertEqual(third["state"], "valid")
        self.assertEqual(fourth["state"], "valid")
        self.assertTrue(third["evidenceSufficient"])
        self.assertTrue(third["creativeComparisonPerformed"])
        self.assertFalse(third["qualityCertaintyClaimed"])
        self.assertGreater(
            fourth["preferenceScore"],
            third["preferenceScore"],
        )
        self.assertIn(
            "not a claim of objective creative quality",
            third["heuristicInterpretation"],
        )

    def test_tie_can_be_resolved_by_human_override_with_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "tournament.jsonl")
            candidates = ledger.plan_candidates(r15.default_four_variants())
            provider = r15.MockMediaR12TournamentProvider(
                scenario="tie"
            )
            runner = r15.CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            runner.process_all()
            decision = ledger.select_winner()
            self.assertEqual(decision["state"], "tie")
            override = ledger.human_override(
                candidate_id=candidates[2]["candidateId"],
                actor_ref="human-reviewer-ref:r15",
                reason="manual preference after reviewing tied valid edits",
            )
            selection = ledger.selected_artifact()
        self.assertEqual(override["state"], "human_override")
        self.assertEqual(
            override["priorDecisionDigest"],
            decision["decisionDigest"],
        )
        self.assertEqual(
            selection["candidateId"],
            candidates[2]["candidateId"],
        )

    def test_insufficient_evidence_state_allows_only_hard_gate_passing_override(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "tournament.jsonl")
            candidates = ledger.plan_candidates(r15.default_four_variants())
            provider = r15.MockMediaR12TournamentProvider(
                scenario="insufficient"
            )
            runner = r15.CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            runner.process_all()
            decision = ledger.select_winner()
            self.assertEqual(decision["state"], "insufficient_evidence")
            with self.assertRaises(r15.CandidateTournamentError):
                ledger.human_override(
                    candidate_id=candidates[0]["candidateId"],
                    actor_ref="human-reviewer-ref:r15",
                    reason="cannot bypass technical QA",
                )
            override = ledger.human_override(
                candidate_id=candidates[3]["candidateId"],
                actor_ref="human-reviewer-ref:r15",
                reason="only hard-gate-passing candidate accepted manually",
            )
        self.assertEqual(override["state"], "human_override")
        self.assertFalse(override["qualityCertaintyClaimed"])

    def test_duplicate_media_result_is_exactly_once_and_conflict_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.ledger(Path(temp) / "tournament.jsonl")
            candidate = ledger.plan_candidates(
                r15.default_four_variants()
            )[2]
            provider = r15.MockMediaR12TournamentProvider()
            request = r15.build_candidate_request(
                ledger=ledger,
                candidate=candidate,
            )
            result = provider.submit(request)
            self.assertEqual(
                ledger.record_media_result(candidate["candidateId"], result),
                "committed",
            )
            self.assertEqual(
                ledger.record_media_result(candidate["candidateId"], result),
                "duplicate",
            )
            altered = dict(result)
            altered["artifact"] = dict(result["artifact"])
            altered["artifact"]["contentSizeBytes"] += 1
            altered["resultDigest"] = r15.reels.sha256_json({
                key: value
                for key, value in altered.items()
                if key != "resultDigest"
            })
            with self.assertRaises(r15.TournamentConflict):
                ledger.record_media_result(
                    candidate["candidateId"],
                    altered,
                )

    def test_partial_completion_and_lost_ack_recover_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tournament.jsonl"
            ledger = self.ledger(path)
            candidates = ledger.plan_candidates(r15.default_four_variants())
            provider = r15.MockMediaR12TournamentProvider(
                crash_after_effect_ordinal=3
            )
            runner = r15.CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            runner.process_candidate(candidates[0]["candidateId"])
            runner.process_candidate(candidates[1]["candidateId"])

            restarted = self.ledger(path)
            runner = r15.CandidateTournamentRunner(
                ledger=restarted,
                provider=provider,
            )
            runner.process_candidate(candidates[2]["candidateId"])
            with self.assertRaises(r15.InjectedTournamentCrash):
                runner.process_candidate(candidates[3]["candidateId"])

            recovered = self.ledger(path)
            runner = r15.CandidateTournamentRunner(
                ledger=recovered,
                provider=provider,
            )
            runner.process_candidate(candidates[3]["candidateId"])
            decision = recovered.select_winner()

        self.assertEqual(decision["state"], "selected")
        self.assertEqual(provider.accepted_effects, 4)
        self.assertEqual(provider.submit_calls, 4)
        self.assertGreaterEqual(provider.recover_calls, 5)
        self.assertEqual(
            recovered.candidates[candidates[3]["candidateId"]]["status"],
            "valid",
        )

    def test_r14_batch_item_tournament_respects_outer_budget_and_enters_release_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch, _synth, item_id = self.make_batch(
                root,
                render_budget=120.0,
            )
            provider = r15.MockMediaR12TournamentProvider()
            outcome = batch.run_tournament(
                item_id,
                config=r15.default_config(),
                provider=provider,
                allow_synthetic_fixture=True,
            )
            self.assertEqual(
                outcome["decision"]["state"],
                "selected",
            )
            self.assertEqual(
                batch.ledger._item(item_id)["state"],
                "awaiting_release",
            )
            selection = outcome["selection"]
            self.assertEqual(selection["candidateId"], outcome["decision"]["winnerCandidateId"])
            batch.authorize_item(item_id)
            request = batch._publish_request(item_id)
            self.assertEqual(
                request["media"]["contentSha256"],
                selection["contentSha256"],
            )
            self.assertEqual(
                request["releaseAuthorization"]["artifactId"],
                selection["contentId"],
            )
            self.assertEqual(provider.accepted_effects, 4)
            self.assertEqual(
                batch.ledger.budget_spent["render_seconds"],
                120.0,
            )

    def test_r14_outer_budget_stops_tournament_before_excess_media_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch, _synth, item_id = self.make_batch(
                root,
                render_budget=90.0,
            )
            provider = r15.MockMediaR12TournamentProvider()
            with self.assertRaises(r14.BudgetExceeded):
                batch.run_tournament(
                    item_id,
                    config=r15.default_config(),
                    provider=provider,
                    allow_synthetic_fixture=True,
                )
            self.assertEqual(provider.accepted_effects, 3)
            self.assertEqual(provider.submit_calls, 3)
            self.assertEqual(
                batch.ledger.budget_spent["render_seconds"],
                90.0,
            )

    def test_r14_tournament_lost_ack_restart_preserves_one_effect_per_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch, _synth, item_id = self.make_batch(
                root,
                render_budget=120.0,
            )
            provider = r15.MockMediaR12TournamentProvider(
                crash_after_effect_ordinal=3
            )
            with self.assertRaises(r15.InjectedTournamentCrash):
                batch.run_tournament(
                    item_id,
                    config=r15.default_config(),
                    provider=provider,
                    allow_synthetic_fixture=True,
                )

            reopened_ledger = r14.BatchCampaignLedger(
                root / "batch.jsonl",
                campaign_id="batch-r15-test",
                brief={
                    "goal": "Run an edit tournament",
                    "topic": "candidate editing",
                    "audience": "creators",
                },
                config=batch.ledger.config,
            )
            restarted = r14.BatchCampaignRunner(
                ledger=reopened_ledger,
                work_dir=root,
                media_pin=None,
                allow_synthetic_media=True,
            )
            outcome = restarted.run_tournament(
                item_id,
                config=r15.default_config(),
                provider=provider,
                allow_synthetic_fixture=True,
            )
        self.assertEqual(outcome["decision"]["state"], "selected")
        self.assertEqual(provider.accepted_effects, 4)
        self.assertEqual(provider.submit_calls, 4)
        self.assertEqual(
            reopened_ledger.budget_spent["render_seconds"],
            120.0,
        )
        self.assertEqual(
            reopened_ledger._item(item_id)["state"],
            "awaiting_release",
        )


if __name__ == "__main__":
    unittest.main()
