from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import coordinator_continuation_r30 as r30
from creator_orchestrator import dynamic_live_review_loop as r28
from creator_orchestrator import editor_publish_handoff as r23
from creator_orchestrator import exact_dynamic_e2e_r29 as r29

from test_exact_dynamic_e2e_r29 import (
    build_envelope,
    redigest_envelope,
    unit_context,
)


def _candidate_row(envelope, *, file_name=None):
    c = envelope["candidate"]
    return {
        "envelope_file": file_name or "selected-envelope.json",
        "envelope_digest": envelope["envelope_digest"],
        "handoff_digest": c["handoff_digest"],
        "state": c["state"],
        "candidate_round": c["candidate_round"],
        "source_id": c["source_id"],
        "source_sha256": c["source_sha256"],
        "render_sha256": c["render_sha256"],
        "render_size": c["render_size"],
        "attachment_sha256": c["attachment_sha256"],
        "attachment_size": c["attachment_size"],
        "attachment_mime_type": c["attachment_mime_type"],
        "creator_r29_ready": True,
    }


def build_index(context, envelope=None, *, waiting=False, response_digest=None):
    context = r28.validate_candidate_context(context)
    if waiting:
        state = "BLOCKED_WAITING_GENUINE_CAPTURE"
        capture = None
        pairwise = None
        candidates = {}
        selected_result = None
        package_digest = "b" * 64
        sealed_digest = "c" * 64
        review_round = context["candidate"]["roundIndex"]
    else:
        state = "LIVE_REVIEW_INGESTED"
        package_digest = envelope["review"]["package_digest"]
        sealed_digest = envelope["review"]["sealed_mapping_digest"]
        review_round = envelope["review"]["review_round"]
        response = response_digest or envelope["capture"]["assistant_response_digest"]
        wrapper = {
            "contract": r30.BRIDGE_R31_AUTHORITY["resultContract"],
            "producer_sha": r30.BRIDGE_R31_AUTHORITY["producerSha"],
            "ci_run_id": r30.BRIDGE_R31_AUTHORITY["ciRunId"],
            "result_file_sha256": "7" * 64,
            "state": "LIVE_REVIEW_PASS",
            "capture_digest": envelope["capture"]["capture_digest"],
            "response_digest": response,
            "operator_manifest_digest": "8" * 64,
            "preflight_digest": "9" * 64,
            "request_id": "request-r30",
            "operation_id": "operation-r30",
        }
        capture = {
            "capture_id": envelope["capture"]["capture_id"],
            "capture_digest": envelope["capture"]["capture_digest"],
            "assistant_response_digest": response,
            "conversation": envelope["capture"]["conversation"],
            "bridge_r31_result": wrapper,
        }
        pairwise = {
            "model_facing_selection": envelope["review"]["model_facing_selection"],
            "selected_candidate_id": envelope["review"]["selected_candidate_id"],
            "pairwise_output_digest": envelope["creator_event"]["handoff"]["pairwise"]["output_digest"],
            "pairwise_comparison_id": "comparison-r30",
            "rationale": "fixture pairwise rationale",
            "confidence": 0.9,
            "uncertainty": "fixture only",
        }
        reviewed_id = envelope["candidate"]["candidate_id"]
        reviewed = _candidate_row(envelope)
        candidates = {reviewed_id: reviewed}
        selected_id = envelope["review"]["selected_candidate_id"]
        if selected_id is not None and selected_id != reviewed_id:
            other = copy.deepcopy(reviewed)
            other.update({
                "envelope_file": "other-envelope.json",
                "envelope_digest": "a" * 64,
                "handoff_digest": "1" * 64,
                "state": "winner",
                "render_sha256": "e" * 64,
                "render_size": reviewed["render_size"] + 1,
                "attachment_sha256": "e" * 64,
                "attachment_size": reviewed["attachment_size"] + 1,
            })
            candidates[selected_id] = other
        selected_result = (
            None
            if selected_id is None
            else {"candidate_id": selected_id, **candidates[selected_id]}
        )

    index = {
        "contract_version": r30.GROWTH_R27_AUTHORITY["indexContract"],
        "index_id": "",
        "index_digest": "",
        "state": state,
        "live_capture_gate": (
            "LIVE_REVIEW_PASS" if not waiting else "BLOCKED_WAITING_GENUINE_CAPTURE"
        ),
        "new_ingest_effect": not waiting,
        "growth_r27": {
            "repository": r30.GROWTH_R27_AUTHORITY["repository"],
            "producer_sha": r30.GROWTH_R27_AUTHORITY["producerSha"],
            "ci_run_id": r30.GROWTH_R27_AUTHORITY["ciRunId"],
            "starting_r26_sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
            "operator_contract": r30.GROWTH_R27_AUTHORITY["operatorContract"],
            "authority_profile_digest": r30.GROWTH_R27_AUTHORITY["authorityProfileDigest"],
            "canonical_creator_envelope_authority": {
                "producer_sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
                "ci_run_id": r29.GROWTH_R26_AUTHORITY["ciRunId"],
                "contract": r29.GROWTH_R26_AUTHORITY["creatorEnvelopeContract"],
            },
        },
        "media_r21": {
            "producer_sha": r29.MEDIA_R21_AUTHORITY["producerSha"],
            "ci_run_id": r29.MEDIA_R21_AUTHORITY["ciRunId"],
            "bundle_key": f"fixture-round-{review_round}",
            "package_digest": package_digest,
            "bundle_file_sha256": "2" * 64,
            "sealed_mapping_digest": sealed_digest,
            "prompt_digest": "3" * 64,
            "review_round": review_round,
            "round_lineage_digest": "4" * 64,
            "source": {
                "source_id": context["source"]["sourceId"],
                "sha256": context["source"]["sha256"],
                "size": context["source"]["size"],
            },
        },
        "bridge_r30": {
            "producer_sha": r29.BRIDGE_R30_AUTHORITY["producerSha"],
            "ci_run_id": r29.BRIDGE_R30_AUTHORITY["ciRunId"],
            "capture_contract": r29.BRIDGE_R30_AUTHORITY["captureContract"],
            "bridge_r31_wrapper": (
                None
                if waiting
                else {
                    "producer_sha": r30.BRIDGE_R31_AUTHORITY["producerSha"],
                    "ci_run_id": r30.BRIDGE_R31_AUTHORITY["ciRunId"],
                    "result_contract": r30.BRIDGE_R31_AUTHORITY["resultContract"],
                    "result_file_sha256": "7" * 64,
                }
            ),
        },
        "capture": capture,
        "pairwise": pairwise,
        "selected_result": selected_result,
        "candidates": candidates,
        "rejection_reason": None,
        "evidence_boundary": {
            "model_evidence": not waiting,
            "human_ground_truth": False,
            "human_rating_evidence": False,
            "human_parity_inferred": False,
            "fixture_promoted": False,
            "provider_mutation": False,
            "browser_mutation": False,
            "creator_mutation": False,
            "media_mutation": False,
        },
    }
    index["index_id"] = "gr27idx1:" + r30._sha({
        "growth_sha": index["growth_r27"]["producer_sha"],
        "authority_digest": index["growth_r27"]["authority_profile_digest"],
        "media_package_digest": index["media_r21"]["package_digest"],
        "capture_digest": None if capture is None else capture["capture_digest"],
        "state": state,
    })
    material = copy.deepcopy(index)
    material["index_digest"] = ""
    index["index_digest"] = r30._sha(material)
    return index


def redigest_index(value):
    value["index_id"] = "gr27idx1:" + r30._sha({
        "growth_sha": value["growth_r27"]["producer_sha"],
        "authority_digest": value["growth_r27"]["authority_profile_digest"],
        "media_package_digest": value["media_r21"]["package_digest"],
        "capture_digest": None if value["capture"] is None else value["capture"]["capture_digest"],
        "state": value["state"],
    })
    material = copy.deepcopy(value)
    material["index_digest"] = ""
    value["index_digest"] = r30._sha(material)
    return value


class R30AuthorityAndBoundaryTests(unittest.TestCase):
    def test_exact_authorities_and_waiting_readiness(self):
        self.assertEqual(
            r30.MEDIA_R22_AUTHORITY["producerSha"],
            "e82a7ac04f3758d0e3e21ea3d05265dbc2822132",
        )
        self.assertEqual(
            r30.GROWTH_R27_AUTHORITY["producerSha"],
            "d80592ad660b7b73ad13298880918a5944411c38",
        )
        self.assertEqual(
            r30.BRIDGE_R31_AUTHORITY["producerSha"],
            "104281e49122233f251c692abba726ae31cee0d5",
        )
        report = r30.readiness_report()
        self.assertEqual(report["state"], "WAITING_GENUINE_CAPTURE")
        self.assertTrue(report["SOURCE_READY"])
        self.assertEqual(report["maxReeditRounds"], 2)
        self.assertEqual(report["maxReviewRounds"], 3)
        self.assertFalse(report["genuineCapturePresentInRepository"])
        self.assertFalse(report["modelEvidenceSynthesizedByCreator"])

    def test_stale_growth_r27_producer_and_authority_digest_fail_closed(self):
        context = unit_context()
        envelope = build_envelope(context)
        index = build_index(context, envelope)
        broken = copy.deepcopy(index)
        broken["growth_r27"]["producer_sha"] = "0" * 40
        redigest_index(broken)
        with self.assertRaises(r30.AuthorityDrift):
            r30.validate_growth_r27_index(broken)
        broken = copy.deepcopy(index)
        broken["growth_r27"]["authority_profile_digest"] = "0" * 64
        redigest_index(broken)
        with self.assertRaises(r30.AuthorityDrift):
            r30.validate_growth_r27_index(broken)

    def test_stale_bridge_r31_capture_and_changed_response_fail_closed(self):
        context = unit_context()
        envelope = build_envelope(context)
        index = build_index(context, envelope)
        broken = copy.deepcopy(index)
        broken["capture"]["bridge_r31_result"]["producer_sha"] = "0" * 40
        redigest_index(broken)
        with self.assertRaises(r30.AuthorityDrift):
            r30.validate_growth_r27_index(broken)
        broken = copy.deepcopy(index)
        broken["capture"]["assistant_response_digest"] = "a" * 64
        redigest_index(broken)
        with self.assertRaises(r30.IndexDrift):
            r30.validate_growth_r27_index(broken)

    def test_selected_envelope_binds_index_package_capture_candidate_and_file(self):
        context = unit_context()
        envelope = build_envelope(context)
        index = build_index(context, envelope)
        parsed = r30.validate_selected_envelope(
            index=index,
            envelope=envelope,
            envelope_path=Path("selected-envelope.json"),
        )
        self.assertEqual(
            parsed["candidate"]["render_sha256"],
            context["candidate"]["renderSha256"],
        )
        self.assertEqual(
            parsed["review"]["package_digest"],
            index["media_r21"]["package_digest"],
        )
        self.assertEqual(
            parsed["capture"]["capture_digest"],
            index["capture"]["capture_digest"],
        )

    def test_package_mapping_and_candidate_drift_fail_closed(self):
        context = unit_context()
        envelope = build_envelope(context)
        index = build_index(context, envelope)
        broken = copy.deepcopy(index)
        broken["media_r21"]["sealed_mapping_digest"] = "0" * 64
        redigest_index(broken)
        with self.assertRaises(r30.LineageDrift):
            r30.validate_selected_envelope(index=broken, envelope=envelope)
        broken = copy.deepcopy(index)
        cid = envelope["candidate"]["candidate_id"]
        broken["candidates"][cid]["render_sha256"] = "0" * 64
        redigest_index(broken)
        with self.assertRaises(r30.LineageDrift):
            r30.validate_selected_envelope(index=broken, envelope=envelope)

    def test_journal_exact_replay_is_idempotent_changed_response_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            journal = r30.Journal(Path(td) / "journal.jsonl")
            payload = {
                "indexDigest": "1" * 64,
                "assistantResponseDigest": "2" * 64,
            }
            self.assertEqual(
                journal.append_once("review:0", "growth_r27_review_accepted", payload),
                "committed",
            )
            self.assertEqual(
                journal.append_once("review:0", "growth_r27_review_accepted", payload),
                "duplicate",
            )
            changed = dict(payload)
            changed["assistantResponseDigest"] = "3" * 64
            with self.assertRaises(r30.ReplayConflict):
                journal.append_once(
                    "review:0", "growth_r27_review_accepted", changed
                )

    def test_round_regression_and_third_reedit_fail_closed(self):
        context = unit_context(round_index=2)
        envelope = build_envelope(context, state="targeted_reedit")
        with self.assertRaises(r29.RoundLimit):
            r30.validate_selected_envelope(
                index=build_index(context, envelope),
                envelope=envelope,
            )
        with tempfile.TemporaryDirectory() as td:
            journal = r30.Journal(Path(td) / "journal.jsonl")
            journal.append_once("review:1", "growth_r27_review_accepted", {"x": 1})
            self.assertEqual(journal.seen_rounds(), [1])

    def test_nonwinner_never_passes_publish_boundary(self):
        for state in ("tie", "insufficient_evidence", "human_review"):
            envelope = build_envelope(unit_context(), state=state)
            with self.assertRaises(r23.EditorOutcomeIneligible):
                r30._terminal_growth_validator(
                    envelope,
                    expected_source_id="source-r29",
                    expected_render_sha256="2" * 64,
                )

    def test_waiting_index_contains_no_fabricated_live_evidence(self):
        context = unit_context()
        index = r30.validate_growth_r27_index(
            build_index(context, waiting=True)
        )
        self.assertEqual(index["state"], "BLOCKED_WAITING_GENUINE_CAPTURE")
        self.assertIsNone(index["capture"])
        self.assertFalse(index["evidence_boundary"]["model_evidence"])


@unittest.skipUnless(
    os.environ.get("R30_MEDIA_R22_CHECKOUT")
    and os.environ.get("R30_MEDIA_R21_CHECKOUT")
    and os.environ.get("R30_GROWTH_R27_CHECKOUT")
    and os.environ.get("R30_BRIDGE_R31_CHECKOUT"),
    "exact R30 dependency checkouts required",
)
class R30ExactRealMp4IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media22 = Path(os.environ["R30_MEDIA_R22_CHECKOUT"]).resolve()
        cls.media21 = Path(os.environ["R30_MEDIA_R21_CHECKOUT"]).resolve()
        cls.growth27 = Path(os.environ["R30_GROWTH_R27_CHECKOUT"]).resolve()
        cls.bridge31 = Path(os.environ["R30_BRIDGE_R31_CHECKOUT"]).resolve()
        r30.verify_media_r22_checkout(cls.media22)
        r29.verify_media_checkout(cls.media21)
        r30.verify_growth_r27_checkout(cls.growth27)
        r30.verify_bridge_r31_checkout(cls.bridge31)

        env = dict(os.environ)
        env["GITHUB_SHA"] = r29.MEDIA_R21_AUTHORITY["producerSha"]
        result = subprocess.run(
            ["node", str(cls.media21 / "tools/demo-r19-editorial-reedit.mjs")],
            cwd=cls.media21,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr[-6000:])
        cls.demo_root = cls.media21 / ".artifacts/r19-demo"
        case_root = cls.demo_root / "cases/talking-head-vertical"
        request = json.loads((case_root / "request.json").read_text(encoding="utf-8"))
        candidate = request["candidate"]
        timeline = request["timeline"]
        source_uri = next(
            track for track in timeline["tracks"] if track["kind"] == "video"
        )["items"][0]["source"]["uri"]
        export_path = cls.demo_root / candidate["renderExportPath"]
        export_digest = r28._media_semantic_digest(
            cls.media21, export_path, "render"
        )
        cls.context = r28.build_candidate_context(
            loop_id="r30-real-mp4-rehearsal",
            brief_digest="a" * 64,
            semantic_analysis_digest="b" * 64,
            semantic_directives_digest="c" * 64,
            ledger_digest="d" * 64,
            source={
                "sourceId": candidate["source"]["sourceId"],
                "sha256": candidate["source"]["sha256"],
                "size": candidate["source"]["size"],
                "path": source_uri,
            },
            candidate={
                "candidateId": candidate["candidateId"],
                "roundIndex": 0,
                "finalPath": candidate["finalPath"],
                "renderSha256": candidate["renderSha256"],
                "renderSize": candidate["renderSize"],
                "renderExportPath": candidate["renderExportPath"],
                "renderExportSha256": candidate["renderExportSha256"],
                "renderExportDigest": export_digest,
                "renderProducerSha": candidate["renderProducerSha"],
                "editorialApplication": None,
            },
            timeline=timeline,
            export_spec=request["exportSpec"],
        )

    def setUp(self):
        for name in (
            ".creator-r28",
            ".creator-r30-packages",
            "round-1",
            "round-2",
        ):
            shutil.rmtree(self.demo_root / name, ignore_errors=True)

    def test_exact_dependency_checkouts(self):
        self.assertEqual(
            r30.verify_media_r22_checkout(self.media22)["checkoutSha"],
            r30.MEDIA_R22_AUTHORITY["producerSha"],
        )
        self.assertEqual(
            r30.verify_growth_r27_checkout(self.growth27)["checkoutSha"],
            r30.GROWTH_R27_AUTHORITY["producerSha"],
        )
        self.assertEqual(
            r30.verify_bridge_r31_checkout(self.bridge31)["checkoutSha"],
            r30.BRIDGE_R31_AUTHORITY["producerSha"],
        )

    def test_real_mp4_reedit_then_r21_package_then_r22_materializer(self):
        envelope = build_envelope(self.context)
        media = r30.execute_media_r22_reedit(
            media_r22_checkout=self.media22,
            candidate_root=self.demo_root,
            context=self.context,
            envelope=envelope,
            out_dir=self.demo_root,
        )
        self.assertEqual(media["evidence"]["logicalEffects"], 1)
        self.assertNotEqual(
            media["evidence"]["before"]["sha256"],
            media["evidence"]["after"]["sha256"],
        )
        self.assertEqual(
            media["application"]["producer"]["sha"],
            r30.MEDIA_R22_AUTHORITY["producerSha"],
        )
        next_context = r30.build_next_context(
            prior=self.context,
            media_result=media,
            candidate_root=self.demo_root,
        )
        materialized = r30.materialize_next_review(
            media_r21_checkout=self.media21,
            media_r22_checkout=self.media22,
            candidate_root=self.demo_root,
            before_context=self.context,
            after_context=next_context,
            envelope=envelope,
            work_dir=self.demo_root / ".creator-r30-packages" / "case",
        )
        evidence = materialized["evidence"]
        self.assertEqual(evidence["reviewRound"], 1)
        self.assertEqual(
            evidence["mediaR22ProducerSha"],
            r30.MEDIA_R22_AUTHORITY["producerSha"],
        )
        self.assertEqual(
            evidence["sourceMediaR21ProducerSha"],
            r29.MEDIA_R21_AUTHORITY["producerSha"],
        )
        self.assertTrue(Path(materialized["operatorManifestPath"]).is_file())
        self.assertTrue(Path(materialized["operatorDir"], "media-r22-live-package.tar").is_file())
        self.assertFalse(evidence["providerMutation"])
        self.assertFalse(evidence["browserMutation"])
        self.assertFalse(evidence["humanLevelQualityClaimed"])

        replay_media = r30.execute_media_r22_reedit(
            media_r22_checkout=self.media22,
            candidate_root=self.demo_root,
            context=self.context,
            envelope=envelope,
            out_dir=self.demo_root,
        )
        self.assertTrue(replay_media["evidence"]["replayed"])
        self.assertEqual(replay_media["evidence"]["logicalEffects"], 0)
        replay_package = r30.materialize_next_review(
            media_r21_checkout=self.media21,
            media_r22_checkout=self.media22,
            candidate_root=self.demo_root,
            before_context=self.context,
            after_context=next_context,
            envelope=envelope,
            work_dir=self.demo_root / ".creator-r30-packages" / "case",
        )
        self.assertEqual(
            replay_package["evidence"]["operatorManifestSha256"],
            evidence["operatorManifestSha256"],
        )
        self.assertEqual(
            replay_package["evidence"]["archiveSha256"],
            evidence["archiveSha256"],
        )


class R30SourceReadyRealMp4RehearsalTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_rehearsal_stops_at_external_review_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            report = r30.run_real_mp4_rehearsal(Path(td))
            self.assertEqual(report["state"], "WAITING_GENUINE_CAPTURE")
            self.assertTrue(report["externalReviewBoundaryReached"])
            self.assertGreater(report["sourceReadyMp4"]["size"], 0)
            self.assertEqual(report["sourceReadyMp4"]["width"], 360)
            self.assertEqual(report["sourceReadyMp4"]["height"], 640)
            self.assertFalse(report["modelEvidenceSynthesized"])
            self.assertFalse(report["providerMutation"])
            self.assertFalse(report["humanLevelQualityClaimed"])


if __name__ == "__main__":
    unittest.main()
