from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from creator_orchestrator import exact_pin_closed_loop as r24


class R24ClosedLoopUnitTests(unittest.TestCase):
    def test_dependency_constants_are_exact(self):
        self.assertEqual(
            r24.MEDIA_SHA,
            "a17f782da8144d1e890ac83195396a3192df93c2",
        )
        self.assertEqual(r24.MEDIA_CI, "36860193113")
        self.assertEqual(
            r24.GROWTH_SHA,
            "2d3bf275c5b456d53384073fb7ec1ed992e6b996",
        )
        self.assertEqual(r24.GROWTH_CI, "36859378847")

    def test_candidate_bound_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            for count in (1, 5):
                with self.subTest(count=count), self.assertRaises(r24.ClosedLoopError):
                    r24.run_closed_loop(
                        source_path=Path(td) / "x.mp4",
                        brief="x",
                        media_checkout=Path(td),
                        growth_checkout=Path(td),
                        out_dir=Path(td) / "out",
                        candidates=count,
                    )

    def test_duplicate_ledger_event_is_idempotent_conflict_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = r24.Ledger(Path(td) / "ledger.jsonl")
            self.assertEqual(
                ledger.append_once("k", "event", {"value": 1}),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("k", "event", {"value": 1}),
                "duplicate",
            )
            with self.assertRaises(r24.ClosedLoopError):
                ledger.append_once("k", "event", {"value": 2})

    def test_out_of_order_growth_decision_fails(self):
        source = {"sourceId": "s", "sha256": "a" * 64}
        record = {
            "candidateId": "c1",
            "plan": {"ordinal": 0},
            "render": {"render_sha256": "b" * 64},
        }
        result = {
            "contractVersion": "creator.growth_r18_decision_result.r24.v1",
            "producerSha": r24.GROWTH_SHA,
            "decision": {
                "contract_version": "growth.candidate_decision.v1",
                "source_sha256": "a" * 64,
                "decision_revision": 1,
                "expected_candidate_ids": ["c1"],
            },
            "criticExports": {},
        }
        with self.assertRaises(r24.OutOfOrderDecision):
            r24._validate_growth_result(
                result,
                source=source,
                records=[record],
                previous_revision=1,
            )

    def test_stale_media_artifact_hash_fails_before_r22_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            final_path = Path(td) / "final.mp4"
            final_path.write_bytes(b"actual")
            result = {
                "contractVersion": "creator.media_r15_render_result.r24.v1",
                "actualMediaProducerInvoked": True,
                "renderExport": {
                    "contractVersion": "media.render_export.v1",
                    "producer": {"repository": "foto6/video2", "sha": r24.MEDIA_SHA},
                    "artifact": {
                        "sha256": "f" * 64,
                        "artifactManifestDigest": "e" * 64,
                    },
                    "qa": {
                        "technical": {"passed": True, "sha256": "d" * 64, "value": {"checks": []}},
                        "creative": {"passed": True},
                    },
                    "provenance": {"timelineDigest": "c" * 64},
                },
                "finalPath": str(final_path),
                "renderExportDigest": "b" * 64,
            }
            with self.assertRaises(r24.StaleArtifact):
                r24._adapt_media_export(
                    result,
                    source={"sourceId": "s", "sha256": "a" * 64},
                    plan={
                        "candidateId": "c",
                        "roundIndex": 0,
                        "planDigest": "1" * 64,
                        "ordinal": 0,
                    },
                )

    def test_wrong_media_producer_sha_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            final_path = Path(td) / "final.mp4"
            final_path.write_bytes(b"x")
            sha = __import__("hashlib").sha256(b"x").hexdigest()
            result = {
                "contractVersion": "creator.media_r15_render_result.r24.v1",
                "actualMediaProducerInvoked": True,
                "renderExport": {
                    "contractVersion": "media.render_export.v1",
                    "producer": {"repository": "foto6/video2", "sha": "0" * 40},
                    "artifact": {"sha256": sha, "artifactManifestDigest": "e" * 64},
                    "qa": {
                        "technical": {"passed": True, "sha256": "d" * 64, "value": {"checks": []}},
                        "creative": {"passed": True},
                    },
                    "provenance": {"timelineDigest": "c" * 64},
                },
                "finalPath": str(final_path),
                "renderExportDigest": "b" * 64,
            }
            with self.assertRaises(r24.PinMismatch):
                r24._adapt_media_export(
                    result,
                    source={"sourceId": "s", "sha256": "a" * 64},
                    plan={"candidateId": "c", "roundIndex": 0, "planDigest": "1" * 64, "ordinal": 0},
                )


@unittest.skipUnless(
    os.environ.get("R24_MEDIA_CHECKOUT")
    and os.environ.get("R24_GROWTH_CHECKOUT"),
    "exact sibling checkouts not configured",
)
class R24ClosedLoopIntegrationTests(unittest.TestCase):
    def test_exact_pin_real_artifact_winner_and_resume(self):
        media = Path(os.environ["R24_MEDIA_CHECKOUT"])
        growth = Path(os.environ["R24_GROWTH_CHECKOUT"])
        source = Path(os.environ["R24_SOURCE_VIDEO"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "run"
            foreign_cwd = root / "foreign-cwd"
            foreign_cwd.mkdir()
            with contextlib.chdir(foreign_cwd):
                first = r24.run_closed_loop(
                    source_path=source,
                    brief="Make the proof concise.",
                    media_checkout=media,
                    growth_checkout=growth,
                    out_dir=out,
                    candidates=2,
                    scenario="winner",
                )
            self.assertEqual(first["state"], "publish_handoff_ready")
            self.assertGreaterEqual(first["realMediaRenderEffects"], 1)
            self.assertLessEqual(first["reeditRounds"], 2)
            self.assertFalse(first["providerInvoked"])
            self.assertFalse(first["liveProviderMutation"])
            self.assertTrue((out / "final.mp4").is_file())
            self.assertTrue((out / "editor-publish-handoff.json").is_file())
            with contextlib.chdir(foreign_cwd):
                second = r24.run_closed_loop(
                    source_path=source,
                    brief="Make the proof concise.",
                    media_checkout=media,
                    growth_checkout=growth,
                    out_dir=out,
                    candidates=2,
                    scenario="winner",
                )
            self.assertEqual(second["state"], "publish_handoff_ready")
            self.assertEqual(second["realMediaRenderEffects"], 0)
            self.assertEqual(
                second["finalRenderSha256"], first["finalRenderSha256"]
            )

    def _assert_terminal_nonwinner(self, scenario, expected):
        media = Path(os.environ["R24_MEDIA_CHECKOUT"])
        growth = Path(os.environ["R24_GROWTH_CHECKOUT"])
        source = Path(os.environ["R24_SOURCE_VIDEO"])
        with tempfile.TemporaryDirectory() as td:
            report = r24.run_closed_loop(
                source_path=source,
                brief="Bounded branch test",
                media_checkout=media,
                growth_checkout=growth,
                out_dir=Path(td),
                candidates=2,
                scenario=scenario,
            )
            self.assertEqual(report["state"], expected)
            self.assertIsNone(report["publishHandoffDigest"])
            self.assertFalse(report["liveProviderMutation"])

    def test_tie_never_prepares_publish(self):
        self._assert_terminal_nonwinner("tie", "tie")

    def test_insufficient_evidence_never_prepares_publish(self):
        self._assert_terminal_nonwinner(
            "insufficient_evidence",
            "insufficient_evidence",
        )

    def test_human_review_required_never_prepares_publish(self):
        self._assert_terminal_nonwinner(
            "human_review_required",
            "human_review_required",
        )


if __name__ == "__main__":
    unittest.main()
