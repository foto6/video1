import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import real_review_closed_loop as r26


def make_review(required: dict, *, state: str, operation: str | None = None) -> dict:
    source = required["source"]
    candidate = required["candidate"]
    critic_input_digest = r26._sha({
        "kind": "r26-test-external-input",
        "candidate": candidate,
        "round": required["roundIndex"],
    })
    critic_output_digest = r26._sha({
        "kind": "r26-test-external-output",
        "candidate": candidate,
        "round": required["roundIndex"],
        "state": state,
        "operation": operation,
    })
    binding = {
        "source_id": source["sourceId"],
        "source_sha256": source["sha256"],
        "source_size": source["sizeBytes"],
        "media_repository": candidate["mediaRepository"],
        "media_producer_sha": candidate["mediaProducerSha"],
        "candidate_id": candidate["candidateId"],
        "render_sha256": candidate["renderSha256"],
        "render_size": candidate["renderSizeBytes"],
        "render_export_sha256": candidate["renderExportSha256"],
        "attachment_sha256": candidate["renderSha256"],
        "attachment_size": candidate["renderSizeBytes"],
        "attachment_identity": "r26-test-attachment:" + candidate["renderSha256"][:24],
        "review_bundle_digest": r26._sha({
            "kind": "r26-test-review-bundle",
            "candidate": candidate["candidateId"],
            "render": candidate["renderSha256"],
        }),
        "critic_input_digest": critic_input_digest,
        "critic_output_digest": critic_output_digest,
    }
    directives = []
    if state == "targeted_reedit":
        if operation is None:
            operation = "crop_scale_reframe"
        row = {
            "operation": operation,
            "start_ms": 900,
            "end_ms": 2600,
            "defect_category": (
                "subject_framing_crop_quality"
                if operation == "crop_scale_reframe"
                else "awkward_dead_moment"
            ),
            "severity": "major",
            "source_observation_id": "r26-test-observation:" + str(required["roundIndex"]),
            "evidence": "test-only external fixture bound to exact rendered candidate bytes",
            "confidence": 0.91,
            "uncertainty": "test-only fixture; no live-review claim",
            "upstream_proposed_edit": "test fixture proposed edit",
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(binding),
            "directive_id": "",
        }
        row["directive_id"] = "gcrd1:" + r26._sha({
            k: v for k, v in row.items() if k != "directive_id"
        })
        directives = [row]
    handoff = {
        "contract_version": r26.GROWTH_HANDOFF_VERSION,
        "adapter_version": r26.GROWTH_ADAPTER_VERSION,
        "handoff_id": "",
        "handoff_digest": "",
        "state": state,
        "reedit_round": required["roundIndex"],
        "max_reedit_rounds": 2,
        "binding": binding,
        "pairwise": {
            "selection": None,
            "mapped_candidate_id": None,
            "output_digest": None,
        },
        "coverage": {
            "method": "attached_video_review",
            "inspected_ranges": [{"start_ms": 0, "end_ms": 5000}],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": "test fixture preserves review coverage uncertainty",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": "test fixture only; not genuine live model evidence",
        "directives": directives,
        "bridge_r26_authority": copy.deepcopy(r26.BRIDGE_R26_AUTHORITY),
        "media_r18_authority": copy.deepcopy(r26.MEDIA_R18_AUTHORITY),
        "evidence_boundary": {
            "model_review_only": True,
            "human_ground_truth": False,
            "human_label": False,
            "live_platform_evidence": False,
            "live_video_review_fabricated": False,
        },
        "authority": {
            "advisory_only": True,
            "creator_mutation": False,
            "media_mutation": False,
            "provider_mutation": False,
            "upload_performed": False,
            "publish_authorized": False,
            "release_authorized": False,
        },
    }
    handoff["handoff_id"] = "gcrh1:" + r26._sha({
        "critic_output_digest": binding["critic_output_digest"],
        "pairwise_output_digest": None,
        "reedit_round": required["roundIndex"],
    })
    material = copy.deepcopy(handoff)
    material["handoff_digest"] = ""
    handoff["handoff_digest"] = r26._sha(material)
    event = {
        "contractVersion": r26.REVIEW_EVENT_VERSION,
        "producer": r26._growth_producer_descriptor(),
        "captureMode": "test_fixture",
        "reviewIdentity": handoff["handoff_id"],
        "handoff": handoff,
    }
    r26.parse_review_event(event, allow_test_fixture=True)
    return event


class R26RealMediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(os.environ["R26_MEDIA_CHECKOUT"])
        cls.growth = Path(os.environ["R26_GROWTH_R23_CHECKOUT"])
        cls.source = Path(os.environ["R26_SOURCE_VIDEO"])

    def test_targeted_reedit_lost_ack_restart_then_winner(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "loop"
            first = r26.run_real_review_closed_loop(
                source_path=self.source,
                brief="Use the real Media runtime, then wait for external review.",
                media_checkout=self.media,
                growth_r23_checkout=self.growth,
                out_dir=out,
            )
            self.assertEqual(first["state"], "WAITING_FOR_REAL_REVIEW")
            self.assertEqual(first["realMediaRenderEffects"], 1)
            self.assertEqual(first["realReviewExecutionStatus"], "BLOCKED_OR_TEST_ONLY")

            required0 = json.loads((out / "review-request-r0.json").read_text())
            review0 = make_review(
                required0,
                state="targeted_reedit",
                operation="crop_scale_reframe",
            )
            review0_path = out / "external-review-r0.json"
            review0_path.write_text(json.dumps(review0, indent=2, sort_keys=True) + "\n")

            with self.assertRaises(r26.InjectedLostAck):
                r26.run_real_review_closed_loop(
                    source_path=self.source,
                    brief="Use the real Media runtime, then wait for external review.",
                    media_checkout=self.media,
                    growth_r23_checkout=self.growth,
                    out_dir=out,
                    review_paths=[review0_path],
                    allow_test_fixture=True,
                    inject_lost_ack_after_render={1},
                )

            resumed = r26.run_real_review_closed_loop(
                source_path=self.source,
                brief="Use the real Media runtime, then wait for external review.",
                media_checkout=self.media,
                growth_r23_checkout=self.growth,
                out_dir=out,
                review_paths=[review0_path],
                allow_test_fixture=True,
            )
            self.assertEqual(resumed["state"], "WAITING_FOR_REAL_REVIEW")
            self.assertEqual(resumed["reeditRounds"], 1)
            self.assertEqual(resumed["realMediaRenderEffects"], 0)

            required1 = json.loads((out / "review-request-r1.json").read_text())
            self.assertNotEqual(
                required0["candidate"]["renderSha256"],
                required1["candidate"]["renderSha256"],
            )
            review1 = make_review(required1, state="winner")
            review1_path = out / "external-review-r1.json"
            review1_path.write_text(json.dumps(review1, indent=2, sort_keys=True) + "\n")

            winner = r26.run_real_review_closed_loop(
                source_path=self.source,
                brief="Use the real Media runtime, then wait for external review.",
                media_checkout=self.media,
                growth_r23_checkout=self.growth,
                out_dir=out,
                review_paths=[review0_path, review1_path],
                allow_test_fixture=True,
            )
            self.assertEqual(winner["state"], "publish_handoff_ready")
            self.assertEqual(winner["reeditRounds"], 1)
            self.assertEqual(winner["realMediaRenderEffects"], 0)
            self.assertEqual(winner["publishHandoffEffects"], 1)
            self.assertEqual(winner["realReviewExecutionStatus"], "BLOCKED_OR_TEST_ONLY")
            self.assertTrue((out / "final.mp4").stat().st_size > 0)
            self.assertTrue((out / "editor-final-bundle.json").exists())
            self.assertTrue((out / "editor-publish-handoff.json").exists())

            replay = r26.run_real_review_closed_loop(
                source_path=self.source,
                brief="Use the real Media runtime, then wait for external review.",
                media_checkout=self.media,
                growth_r23_checkout=self.growth,
                out_dir=out,
                review_paths=[review0_path, review1_path],
                allow_test_fixture=True,
            )
            self.assertEqual(replay["state"], "publish_handoff_ready")
            self.assertEqual(replay["realMediaRenderEffects"], 0)
            self.assertEqual(replay["publishHandoffEffects"], 0)
            self.assertEqual(replay["finalRenderSha256"], winner["finalRenderSha256"])
            self.assertEqual(replay["finalBundleDigest"], winner["finalBundleDigest"])
            self.assertEqual(
                replay["publishHandoffDigest"],
                winner["publishHandoffDigest"],
            )

    def test_tie_is_nonpublishable(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "tie"
            waiting = r26.run_real_review_closed_loop(
                source_path=self.source,
                brief="Do not publish a nonwinner.",
                media_checkout=self.media,
                growth_r23_checkout=self.growth,
                out_dir=out,
            )
            required = waiting["requiredReview"]
            tie = make_review(required, state="tie")
            tie_path = out / "tie-review.json"
            tie_path.write_text(json.dumps(tie, indent=2, sort_keys=True) + "\n")
            result = r26.run_real_review_closed_loop(
                source_path=self.source,
                brief="Do not publish a nonwinner.",
                media_checkout=self.media,
                growth_r23_checkout=self.growth,
                out_dir=out,
                review_paths=[tie_path],
                allow_test_fixture=True,
            )
            self.assertEqual(result["state"], "tie")
            self.assertEqual(result["publishHandoffEffects"], 0)
            self.assertFalse((out / "editor-publish-handoff.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
