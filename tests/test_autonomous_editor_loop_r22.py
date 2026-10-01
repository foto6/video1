from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import autonomous_editor_loop as r22


class R22AutonomousEditorLoopTests(unittest.TestCase):
    def test_exact_external_pins_and_media_fail_closed_blocker(self):
        self.assertEqual(
            r22.GROWTH_CRITIC_PIN["producerSha"],
            "cb50a3d78a18e6db1ebef1be69fdf11ff2e27385",
        )
        self.assertEqual(
            r22.GROWTH_CRITIC_PIN["contractVersion"],
            "growth.critic_export.v1",
        )
        self.assertFalse(
            r22.MEDIA_RENDER_EXPORT_OBSERVED[
                "contractPresentAtObservedHead"
            ]
        )
        self.assertIn(
            "no media.render_export.v1",
            r22.MEDIA_RENDER_EXPORT_OBSERVED["missingProducerPin"],
        )

    def test_initial_candidate_ids_and_order_are_stable(self):
        analysis, style, directives = r22.synthetic_semantic_context()
        first = r22.build_initial_plans(
            loop_id="loop-r22-stable",
            semantic_analysis=analysis,
            style_decision=style,
            directives=directives,
            count=4,
        )
        second = r22.build_initial_plans(
            loop_id="loop-r22-stable",
            semantic_analysis=analysis,
            style_decision=style,
            directives=directives,
            count=4,
        )
        self.assertEqual(first, second)
        self.assertEqual(len({x["candidateId"] for x in first}), 4)
        self.assertEqual([x["ordinal"] for x in first], [0, 1, 2, 3])

    def test_render_and_critic_validation_bind_exact_lineage(self):
        analysis, style, directives = r22.synthetic_semantic_context()
        source = {
            "sourceId": "src",
            "sha256": analysis["source"]["sha256"],
            "durationMs": analysis["source"]["durationMs"],
        }
        plan = r22.build_initial_plans(
            loop_id="loop",
            semantic_analysis=analysis,
            style_decision=style,
            directives=directives,
            count=2,
        )[0]
        media = r22.SyntheticMediaRenderAdapter()
        render = media.submit(
            idempotency_key="render:" + plan["candidateId"],
            source=source,
            plan=plan,
        )
        valid = r22.validate_media_render_export(
            render,
            expected_source_id="src",
            expected_source_sha256=source["sha256"],
            expected_candidate_id=plan["candidateId"],
            expected_plan_digest=plan["planDigest"],
            allow_synthetic=True,
        )
        critic_adapter = r22.SyntheticGrowthCriticAdapter()
        critic = critic_adapter.submit(
            idempotency_key="critic:" + plan["candidateId"],
            source=source,
            render_export=valid,
            semantic_analysis=analysis,
        )
        r22.validate_growth_critic_export(
            critic,
            expected_source_id="src",
            expected_render_sha256=valid["render_sha256"],
            allow_synthetic=True,
        )
        broken = dict(render)
        broken["source_sha256"] = "f" * 64
        with self.assertRaises(r22.EditorLoopError):
            r22.validate_media_render_export(
                broken,
                expected_source_id="src",
                expected_source_sha256=source["sha256"],
                expected_candidate_id=plan["candidateId"],
                expected_plan_digest=plan["planDigest"],
                allow_synthetic=True,
            )
        broken_critic = dict(critic)
        broken_critic["render_sha256"] = "e" * 64
        with self.assertRaises(r22.EditorLoopError):
            r22.validate_growth_critic_export(
                broken_critic,
                expected_source_id="src",
                expected_render_sha256=valid["render_sha256"],
                allow_synthetic=True,
            )

    def test_targeted_reedit_deltas_are_concrete(self):
        analysis, style, directives = r22.synthetic_semantic_context()
        source = {
            "sourceId": "src",
            "sha256": analysis["source"]["sha256"],
            "durationMs": analysis["source"]["durationMs"],
        }
        plan = r22.build_initial_plans(
            loop_id="loop",
            semantic_analysis=analysis,
            style_decision=style,
            directives=directives,
            count=2,
        )[0]
        media = r22.SyntheticMediaRenderAdapter()
        render = media.submit(
            idempotency_key="r",
            source=source,
            plan=plan,
        )
        critic = r22.SyntheticGrowthCriticAdapter().submit(
            idempotency_key="c",
            source=source,
            render_export=render,
            semantic_analysis=analysis,
        )
        revised = r22.build_reedit_plan(
            parent_plan=plan,
            critic=critic,
            round_index=1,
        )
        self.assertTrue(revised["targetedDeltas"])
        for delta in revised["targetedDeltas"]:
            self.assertIn("operation", delta)
            self.assertIn("target", delta)
            self.assertIsInstance(delta["target"], dict)
            self.assertTrue(delta["target"])

    def test_rehearsal_survives_lost_ack_and_uses_two_reedit_rounds(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r22.run_synthetic_rehearsal(temp)
            self.assertEqual(report["state"], "SYNTHETIC_REHEARSAL_GREEN")
            self.assertEqual(report["terminalState"], "final_bundle")
            self.assertEqual(report["terminalRoundIndex"], 2)
            self.assertEqual(report["restartCount"], 2)
            self.assertEqual(report["mediaAcceptedEffects"], 8)
            self.assertEqual(report["mediaSubmitCalls"], 8)
            self.assertEqual(report["criticAcceptedEffects"], 8)
            self.assertEqual(report["criticSubmitCalls"], 8)
            self.assertFalse(report["productionMediaRenderExportReady"])
            self.assertFalse(report["humanLevelQualityClaimed"])
            ledger = [
                json.loads(line)
                for line in (Path(temp) / "editor-loop.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            rounds = sorted({
                item["payload"]["plan"]["roundIndex"]
                for item in ledger
                if item["eventType"] == "candidate_planned"
            })
            self.assertEqual(rounds, [0, 1, 2])

    def test_rehearsal_is_hash_and_order_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            one = r22.run_synthetic_rehearsal(a, inject_lost_ack=False)
            two = r22.run_synthetic_rehearsal(b, inject_lost_ack=False)
            self.assertEqual(one["winnerCandidateId"], two["winnerCandidateId"])
            self.assertEqual(one["terminalDigest"], two["terminalDigest"])
            self.assertEqual(one["ledgerDigest"], two["ledgerDigest"])

    def test_insufficient_evidence_fails_to_human_review(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r22.run_synthetic_rehearsal(
                temp,
                scenario="insufficient",
                inject_lost_ack=False,
            )
            self.assertEqual(report["terminalState"], "human_review")
            terminal = json.loads(
                (Path(temp) / "terminal-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                terminal["decisionState"],
                "insufficient_evidence",
            )
            self.assertTrue(terminal["humanReviewRequired"])

    def test_contradictory_evidence_fails_to_human_review(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r22.run_synthetic_rehearsal(
                temp,
                scenario="contradictory",
                inject_lost_ack=False,
            )
            self.assertEqual(report["terminalState"], "human_review")
            terminal = json.loads(
                (Path(temp) / "terminal-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("contradictory", terminal["reason"])
            self.assertTrue(terminal["humanReviewRequired"])

    def test_duplicate_durable_event_is_idempotent_and_conflict_fails(self):
        analysis, _, directives = r22.synthetic_semantic_context()
        source = {
            "sourceId": "duplicate-source",
            "sha256": analysis["source"]["sha256"],
            "durationMs": analysis["source"]["durationMs"],
        }
        with tempfile.TemporaryDirectory() as temp:
            ledger = r22.LoopLedger(
                Path(temp) / "loop.jsonl",
                loop_id="duplicate-loop",
                source=source,
                brief_digest=analysis["briefDigest"],
                semantic_digest=analysis["analysisDigest"],
                directives_digest=directives["directivesDigest"],
                config=r22.LoopConfig(),
            )
            payload = {"value": "same"}
            self.assertEqual(
                ledger.append_once("duplicate:key", "test_event", payload),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("duplicate:key", "test_event", payload),
                "duplicate",
            )
            with self.assertRaises(r22.EditorLoopConflict):
                ledger.append_once(
                    "duplicate:key",
                    "test_event",
                    {"value": "changed"},
                )

    def test_config_enforces_bounds(self):
        with self.assertRaises(r22.EditorLoopError):
            r22.LoopConfig(candidate_count=1).validate()
        with self.assertRaises(r22.EditorLoopError):
            r22.LoopConfig(candidate_count=5).validate()
        with self.assertRaises(r22.EditorLoopError):
            r22.LoopConfig(max_rounds=3).validate()


if __name__ == "__main__":
    unittest.main()
