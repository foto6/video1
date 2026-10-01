from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import full_lifecycle_rehearsal as r24


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg/ffprobe required",
)
class R24FullLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.source = root / "source.mp4"
        proc = subprocess.run(
            [
                shutil.which("ffmpeg"),
                "-hide_banner", "-nostdin", "-y",
                "-f", "lavfi",
                "-i", "color=c=green:s=360x640:r=30:d=15.2",
                "-threads", "1",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                str(cls.source),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-3000:])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_case(self, scenario="winner", inject=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return r24.run_rehearsal(
            source_path=self.source,
            brief="Make the proof concise and test the hook.",
            out_dir=Path(tmp.name),
            scenario=scenario,
            inject_violation=inject,
        ), Path(tmp.name)

    def test_exact_pinned_contract_blobs_validate(self):
        evidence = r24.verify_pinned_contracts()
        self.assertEqual(
            evidence["mediaR15"]["manifestBlobSha"],
            r24.PINS["mediaR15"]["manifestBlobSha"],
        )
        self.assertEqual(
            evidence["growthR18"]["schemaBlobSha"],
            r24.PINS["growthR18"]["schemaBlobSha"],
        )
        self.assertEqual(
            evidence["growthR19"]["manifestBlobSha"],
            r24.PINS["growthR19"]["manifestBlobSha"],
        )

    def test_winner_full_lifecycle_is_source_bound_and_synthetic(self):
        report, out = self.run_case("winner")
        self.assertEqual(report["state"], "completed")
        self.assertEqual(report["reeditRounds"], 2)
        self.assertEqual(report["restartCount"], 1)
        self.assertEqual(report["providerAcceptedEffects"], 1)
        self.assertEqual(report["providerSubmitCalls"], 1)
        self.assertFalse(report["livePublishingExecuted"])
        self.assertFalse(report["liveMetricsUsed"])
        self.assertFalse(report["credentialsPersisted"])
        self.assertFalse(report["humanLevelQualityClaimed"])
        bundle = json.loads((out / "editor-final-bundle.json").read_text())
        learning = json.loads((out / "growth-r19-learning.json").read_text())
        seed = json.loads((out / "next-cycle-brief-seed.json").read_text())
        self.assertEqual(
            bundle["render"]["render_sha256"],
            report["finalRenderSha256"],
        )
        self.assertEqual(
            learning["lineage"]["media_render_sha256"],
            report["finalRenderSha256"],
        )
        self.assertFalse(learning["live_performance_claim_allowed"])
        self.assertFalse(seed["creator_cycle_eligible"])
        self.assertTrue(learning["speculative_hypotheses"])
        self.assertTrue(all(
            h["causal_claim"] is False
            for h in learning["speculative_hypotheses"]
        ))

    def test_tie_branch_stops_before_publish(self):
        report, _ = self.run_case("tie")
        self.assertEqual(report["state"], "tie")
        self.assertIsNone(report["publishReceiptDigest"])

    def test_insufficient_evidence_branch_stops_before_publish(self):
        report, _ = self.run_case("insufficient_evidence")
        self.assertEqual(report["state"], "insufficient_evidence")
        self.assertEqual(report["reeditRounds"], 0)
        self.assertIsNone(report["finalRenderSha256"])

    def test_human_review_required_after_bounded_rounds(self):
        report, _ = self.run_case("human_review_required")
        self.assertEqual(report["state"], "human_review_required")
        self.assertLessEqual(report["reeditRounds"], 2)
        self.assertIsNone(report["publishReceiptDigest"])

    def test_provider_auth_required_stops_without_side_effect(self):
        report, _ = self.run_case("provider_auth_required")
        self.assertEqual(report["state"], "provider_auth_required")
        self.assertEqual(report["providerAcceptedEffects"], 0)
        self.assertEqual(report["providerSubmitCalls"], 0)
        self.assertIsNone(report["publishReceiptDigest"])

    def test_duplicate_lifecycle_event_is_idempotent_and_conflict_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = r24.LifecycleLedger(Path(td) / "ledger.jsonl")
            self.assertEqual(
                ledger.append_once("k", "event", {"value": 1}),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("k", "event", {"value": 1}),
                "duplicate",
            )
            with self.assertRaises(r24.LifecycleError):
                ledger.append_once("k", "event", {"value": 2})

    def test_out_of_order_metrics_rejected(self):
        report, out = self.run_case("winner")
        publish = json.loads((out / "growth-publish-result.json").read_text())
        first = r24.build_synthetic_metric_snapshot(
            publish,
            window_start="2026-10-01T00:00:02Z",
            window_end="2026-10-01T02:00:00Z",
        )
        older = r24.build_synthetic_metric_snapshot(
            publish,
            window_start="2026-10-01T00:00:02Z",
            window_end="2026-10-01T01:00:00Z",
        )
        with self.assertRaises(r24.OutOfOrderMetrics):
            r24.validate_metric_snapshot(older, previous=first)

    def test_hash_mismatch_injections_fail_closed(self):
        for kind in (
            "render_hash_mismatch",
            "decision_source_hash_mismatch",
            "metrics_hash_mismatch",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                with self.assertRaises(r24.LifecycleError):
                    r24.run_rehearsal(
                        source_path=self.source,
                        brief="Invariant test",
                        out_dir=Path(td),
                        scenario="winner",
                        inject_violation=kind,
                    )

    def test_cli_exits_nonzero_on_injected_invariant_violation(self):
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = r24.main([
                    "--source", str(self.source),
                    "--brief", "Invariant CLI test",
                    "--out", td,
                    "--inject-violation", "render_hash_mismatch",
                ])
            self.assertEqual(code, 2)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["state"], "BLOCKED_INVARIANT")
            self.assertFalse(payload["livePublishingExecuted"])
            self.assertFalse(payload["liveMetricsUsed"])

    def test_learning_and_seed_fail_closed_on_causal_or_eligibility_drift(self):
        report, out = self.run_case("winner")
        learning = json.loads((out / "growth-r19-learning.json").read_text())
        learning["speculative_hypotheses"][0]["causal_claim"] = True
        with self.assertRaises(r24.LifecycleError):
            r24.validate_growth_r19_learning(learning)
        seed = json.loads((out / "next-cycle-brief-seed.json").read_text())
        seed["creator_cycle_eligible"] = True
        with self.assertRaises(r24.LifecycleError):
            r24.validate_brief_seed(seed)


if __name__ == "__main__":
    unittest.main()
