from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import live_review_execution as r27


def _fixture_handoff(*, state="targeted_reedit", round_index=0):
    binding = {
        "source_id": "source-r27",
        "source_sha256": "1" * 64,
        "source_size": 100,
        "media_repository": "foto6/video2",
        "media_producer_sha": r27.MEDIA_R19["sha"],
        "candidate_id": "candidate-r27",
        "render_sha256": "2" * 64,
        "render_size": 200,
        "render_export_sha256": "3" * 64,
        "attachment_sha256": "2" * 64,
        "attachment_size": 200,
        "attachment_identity": "attachment-r27",
        "review_bundle_digest": "4" * 64,
        "critic_input_digest": "5" * 64,
        "critic_output_digest": "6" * 64,
    }
    directives = []
    if state == "targeted_reedit":
        body = {
            "operation": "trim",
            "start_ms": 100,
            "end_ms": 300,
            "defect_category": "awkward_dead_moment",
            "severity": "major",
            "source_observation_id": "obs-r27",
            "evidence": "fixture evidence only",
            "confidence": 0.9,
            "uncertainty": "fixture uncertainty",
            "upstream_proposed_edit": "remove pause",
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(binding),
        }
        body["directive_id"] = "gcrd1:" + r27._sha(body)
        directives = [body]
    handoff = {
        "contract_version": "growth.creator_reedit_handoff.v1",
        "adapter_version": "growth.web_video_critic_reedit_adapter.v1",
        "handoff_id": "",
        "handoff_digest": "",
        "state": state,
        "reedit_round": round_index,
        "max_reedit_rounds": 2,
        "binding": binding,
        "pairwise": {
            "selection": None,
            "mapped_candidate_id": (
                "candidate-r27" if state == "winner" else None
            ),
            "output_digest": None,
        },
        "coverage": {
            "method": "fixture",
            "inspected_ranges": [{"start_ms": 0, "end_ms": 5000}],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": "fixture only",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": "fixture only",
        "directives": directives,
        "bridge_r26_authority": copy.deepcopy(
            r27.r26.BRIDGE_R26_AUTHORITY
        ),
        "media_r18_authority": copy.deepcopy(
            r27.r26.MEDIA_R18_AUTHORITY
        ),
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
    handoff["handoff_id"] = "gcrh1:" + r27._sha(
        {
            "critic_output_digest": binding["critic_output_digest"],
            "pairwise_output_digest": None,
            "reedit_round": round_index,
        }
    )
    material = copy.deepcopy(handoff)
    material["handoff_digest"] = ""
    handoff["handoff_digest"] = r27._sha(material)
    return handoff


def _context():
    return r27.build_candidate_context(
        loop_id="loop-r27",
        brief_digest="a" * 64,
        semantic_analysis_digest="b" * 64,
        semantic_directives_digest="c" * 64,
        ledger_digest="d" * 64,
        source={
            "sourceId": "source-r27",
            "sha256": "1" * 64,
            "size": 100,
        },
        candidate={
            "candidateId": "candidate-r27",
            "roundIndex": 0,
            "finalPath": "candidate/final.mp4",
            "renderSha256": "2" * 64,
            "renderSize": 200,
            "renderExportPath": "candidate/media.render_export.v1.json",
            "renderExportSha256": "3" * 64,
            "renderProducerSha": r27.MEDIA_R19["sha"],
        },
        timeline={"id": "timeline-r27"},
        export_spec={"format": "mp4"},
    )


class R27BoundaryTests(unittest.TestCase):
    def test_readiness_separates_all_required_stages(self):
        report = r27.readiness_report()
        self.assertTrue(report["SOURCE_READY"])
        self.assertFalse(report["REAL_REVIEW_INGESTED"])
        self.assertFalse(report["REAL_REEDIT_EXECUTED"])
        self.assertFalse(report["PUBLISH_HANDOFF_READY"])
        self.assertEqual(report["state"], "BLOCKED_WAITING_REAL_CAPTURE")
        codes = {row["code"] for row in report["blockers"]}
        self.assertIn(
            "GROWTH_R25_CREATOR_READY_ENVELOPE_UNAVAILABLE",
            codes,
        )
        self.assertIn(
            "MEDIA_R20_DYNAMIC_REVIEW_PACKAGE_UNAVAILABLE",
            codes,
        )

    def test_exact_media_r19_pin_is_frozen(self):
        self.assertEqual(
            r27.MEDIA_R19["sha"],
            "31409de4bef473417a33a8c698507f7cfb1905e1",
        )
        self.assertEqual(
            r27.MEDIA_R19["applicationSchemaBlobSha1"],
            "7cabf91f08ae11b68cc4a7eec88d358a46730289",
        )
        self.assertEqual(
            r27.MEDIA_R19["runnerBlobSha1"],
            "7dbec612621aa42baaf2946cdac61d070e3ff41f",
        )

    def test_fixture_envelope_is_never_accepted_as_real_capture(self):
        envelope = r27.build_fixture_envelope(_fixture_handoff())
        with self.assertRaises(r27.DependencyUnavailable):
            r27.validate_growth_r25_envelope(
                envelope,
                allow_test_fixture=False,
            )
        parsed = r27.validate_growth_r25_envelope(
            envelope,
            allow_test_fixture=True,
        )
        self.assertTrue(parsed["evidenceBoundary"]["fixture"])
        self.assertFalse(
            parsed["evidenceBoundary"]["realExternalCapture"]
        )

    def test_stale_source_render_and_attachment_fail_closed(self):
        base = r27.build_fixture_envelope(_fixture_handoff())
        variants = []
        source = copy.deepcopy(base)
        source["review"]["source"]["sha256"] = "9" * 64
        source["review"]["handoff"]["binding"]["source_sha256"] = "9" * 64
        variants.append(source)

        render = copy.deepcopy(base)
        render["review"]["candidate"]["renderSha256"] = "8" * 64
        variants.append(render)

        attachment = copy.deepcopy(base)
        attachment["review"]["candidate"]["attachmentSha256"] = "7" * 64
        variants.append(attachment)

        for value in variants:
            material = copy.deepcopy(value)
            material["envelopeDigest"] = ""
            value["envelopeDigest"] = r27._sha(
                {k: v for k, v in material.items() if k != "envelopeDigest"}
            )
            with self.assertRaises(r27.ReviewLineageError):
                r27.validate_growth_r25_envelope(
                    value,
                    allow_test_fixture=True,
                )

    def test_round_two_targeted_reedit_is_rejected(self):
        envelope = r27.build_fixture_envelope(
            _fixture_handoff(round_index=2)
        )
        self.assertEqual(envelope["review"]["roundIndex"], 2)
        self.assertEqual(envelope["review"]["state"], "targeted_reedit")
        if envelope["review"]["roundIndex"] >= r27.MAX_REEDIT_ROUNDS:
            with self.assertRaises(r27.RoundLimitError):
                raise r27.RoundLimitError("cannot execute third re-edit")

    def test_duplicate_review_is_idempotent_but_conflict_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = r27.Ledger(Path(td) / "ledger.jsonl")
            payload = {
                "envelopeDigest": "a" * 64,
                "state": "winner",
            }
            self.assertEqual(
                ledger.append_once("review:0", "review", payload),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("review:0", "review", payload),
                "duplicate",
            )
            with self.assertRaises(r27.ReviewReplayConflict):
                ledger.append_once(
                    "review:0",
                    "review",
                    {
                        "envelopeDigest": "b" * 64,
                        "state": "winner",
                    },
                )

    def test_winner_and_nonwinner_publishability(self):
        winner = r27.build_fixture_envelope(
            _fixture_handoff(state="winner")
        )
        self.assertEqual(winner["review"]["state"], "winner")
        for state in ("tie", "insufficient_evidence", "human_review"):
            envelope = r27.build_fixture_envelope(
                _fixture_handoff(state=state)
            )
            self.assertNotEqual(envelope["review"]["state"], "winner")
            with self.assertRaises(r27.r23.EditorOutcomeIneligible):
                r27.materialize_publish_handoff(
                    context=_context(),
                    envelope=envelope,
                    bundle={},
                    final_path=Path("missing.mp4"),
                    release_authorization={},
                    platform="tiktok",
                    account_id="no-live",
                    destination="privacy:SELF_ONLY",
                    credential_ref="opaque-ref",
                    authorization_ref="opaque-auth",
                    caption="x",
                    cta="x",
                )

    def test_next_review_boundary_is_blocked_without_media_r20(self):
        envelope = r27.build_fixture_envelope(_fixture_handoff())
        context = _context()
        result = {
            "evidence": {
                "after": {
                    "sha256": "e" * 64,
                    "size": 123,
                    "renderExportSha256": "f" * 64,
                },
                "resultDigest": "1" * 64,
            }
        }
        boundary = r27.build_next_review_boundary(
            source=context["source"],
            prior_context=context,
            envelope=envelope,
            media_result=result,
        )
        self.assertEqual(
            boundary["state"],
            "BLOCKED_MEDIA_R20_DYNAMIC_PACKAGE_UNAVAILABLE",
        )
        self.assertEqual(boundary["roundIndex"], 1)


@unittest.skipUnless(
    os.environ.get("R27_MEDIA_R19_CHECKOUT")
    and os.environ.get("R27_GROWTH_R25_CHECKOUT"),
    "exact Media R19 and observed Growth R25 checkouts required",
)
class R27ExactMediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(os.environ["R27_MEDIA_R19_CHECKOUT"]).resolve()
        cls.growth = Path(os.environ["R27_GROWTH_R25_CHECKOUT"]).resolve()
        env = dict(os.environ)
        env["GITHUB_SHA"] = r27.MEDIA_R19["sha"]
        result = subprocess.run(
            [
                "node",
                str(cls.media / "tools" / "demo-r19-editorial-reedit.mjs"),
            ],
            cwd=cls.media,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=240,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr[-5000:])
        cls.demo_root = cls.media / ".artifacts" / "r19-demo"
        cls.request_path = (
            cls.demo_root
            / "cases"
            / "talking-head-vertical"
            / "request.json"
        )
        cls.request = json.loads(
            cls.request_path.read_text(encoding="utf-8")
        )

    def setUp(self):
        shutil.rmtree(
            self.demo_root / ".creator-r27",
            ignore_errors=True,
        )

    def _context_and_envelope(self, root: Path):
        request = self.request
        candidate = request["candidate"]
        context = r27.build_candidate_context(
            loop_id="r27-integration-loop",
            brief_digest="a" * 64,
            semantic_analysis_digest="b" * 64,
            semantic_directives_digest="c" * 64,
            ledger_digest="d" * 64,
            source=copy.deepcopy(candidate["source"]),
            candidate={
                "candidateId": candidate["candidateId"],
                "roundIndex": 0,
                "finalPath": candidate["finalPath"],
                "renderSha256": candidate["renderSha256"],
                "renderSize": candidate["renderSize"],
                "renderExportPath": candidate["renderExportPath"],
                "renderExportSha256": candidate[
                    "renderExportSha256"
                ],
                "renderProducerSha": candidate["renderProducerSha"],
            },
            timeline=request["timeline"],
            export_spec=request["exportSpec"],
        )
        envelope = r27.build_fixture_envelope(request["handoff"])
        context_path = root / "context.json"
        envelope_path = root / "review.json"
        context_path.write_text(json.dumps(context), encoding="utf-8")
        envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
        return context_path, envelope_path, context, envelope

    def test_exact_media_r19_real_reedit_and_restart_replay(self):
        r27.verify_media_r19_checkout(self.media)
        observed = r27.observe_growth_r25_checkout(self.growth)
        self.assertFalse(observed["creatorReadyEnvelopeAvailable"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_path, envelope_path, context, _ = (
                self._context_and_envelope(root)
            )
            out = root / "out"
            first = r27.run_review_execution(
                media_checkout=self.media,
                growth_r25_checkout=self.growth,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=envelope_path,
                out_dir=out,
                allow_test_fixture=True,
            )
            self.assertEqual(first["mediaR19LogicalEffects"], 1)
            self.assertFalse(first["mediaR19Replay"])
            self.assertNotEqual(
                first["beforeRenderSha256"],
                first["afterRenderSha256"],
            )
            self.assertFalse(first["REAL_REVIEW_INGESTED"])
            self.assertFalse(first["REAL_REEDIT_EXECUTED"])
            self.assertEqual(
                first["state"],
                "BLOCKED_MEDIA_R20_DYNAMIC_PACKAGE_UNAVAILABLE",
            )

            second = r27.run_review_execution(
                media_checkout=self.media,
                growth_r25_checkout=self.growth,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=envelope_path,
                out_dir=out,
                allow_test_fixture=True,
            )
            self.assertEqual(second["mediaR19LogicalEffects"], 0)
            self.assertTrue(second["mediaR19Replay"])
            self.assertTrue(second["reviewReplay"])
            self.assertEqual(
                second["afterRenderSha256"],
                first["afterRenderSha256"],
            )

    def test_lost_ack_recovery_does_not_duplicate_media_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_path, envelope_path, _, _ = (
                self._context_and_envelope(root)
            )
            out = root / "out"
            with self.assertRaises(r27.InjectedLostAck):
                r27.run_review_execution(
                    media_checkout=self.media,
                    growth_r25_checkout=self.growth,
                    candidate_root=self.demo_root,
                    candidate_context_path=context_path,
                    review_envelope_path=envelope_path,
                    out_dir=out,
                    allow_test_fixture=True,
                    inject_lost_ack_after_media=True,
                )
            recovered = r27.run_review_execution(
                media_checkout=self.media,
                growth_r25_checkout=self.growth,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=envelope_path,
                out_dir=out,
                allow_test_fixture=True,
            )
            self.assertEqual(recovered["mediaR19LogicalEffects"], 0)
            self.assertTrue(recovered["mediaR19Replay"])


if __name__ == "__main__":
    unittest.main()
