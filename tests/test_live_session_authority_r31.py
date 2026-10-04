from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import dynamic_live_review_loop as r28
from creator_orchestrator import editor_publish_handoff as r23
from creator_orchestrator import live_session_authority_r31 as r31
from test_exact_dynamic_e2e_r29 import build_envelope


def _selected_result(candidate_id: str, envelope, round_index: int):
    value = {
        "contract_version": r31.GROWTH_R28_AUTHORITY["selectedResultContract"],
        "result_id": "",
        "result_digest": "",
        "candidate_id": candidate_id,
        "candidate_round": round_index,
        "state": "winner",
        "render_sha256": "a" * 64,
        "render_size": 201,
        "attachment_sha256": "a" * 64,
        "attachment_size": 201,
        "handoff_digest": "b" * 64,
        "envelope_digest": "c" * 64,
        "pairwise_selection": "B",
        "review_round": round_index,
        "publish_authorized": False,
        "human_ground_truth": False,
        "human_rating_evidence": False,
        "human_parity_inferred": False,
    }
    value["result_id"] = "gr28sel1:" + r31._sha({
        "candidate_id": candidate_id,
        "envelope_digest": value["envelope_digest"],
        "review_round": round_index,
    })
    material = copy.deepcopy(value)
    material["result_digest"] = ""
    value["result_digest"] = r31._sha(material)
    return value


def build_context(root: Path, round_index: int = 0):
    source = root / "source.mp4"
    render = root / "candidate" / "final.mp4"
    export = root / "candidate" / "media.render_export.v1.json"
    render.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"r31-source-bytes")
    render.write_bytes(b"r31-reviewed-candidate")
    export.write_text('{"contract":"fixture-render-export"}\n', encoding="utf-8")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    render_sha = hashlib.sha256(render.read_bytes()).hexdigest()
    export_sha = hashlib.sha256(export.read_bytes()).hexdigest()
    candidate = {
        "candidateId": "candidate-r31",
        "roundIndex": round_index,
        "finalPath": "candidate/final.mp4",
        "renderSha256": render_sha,
        "renderSize": render.stat().st_size,
        "renderExportPath": "candidate/media.render_export.v1.json",
        "renderExportSha256": export_sha,
        "renderExportDigest": "4" * 64,
        "renderProducerSha": r31.MEDIA_R23_AUTHORITY["producerSha"],
        "editorialApplication": None,
    }
    if round_index:
        app = root / "candidate" / "media.editorial_reedit_application.v1.json"
        app.write_text('{"contract":"fixture-app"}\n', encoding="utf-8")
        candidate["editorialApplication"] = {
            "path": "candidate/media.editorial_reedit_application.v1.json",
            "fileSha256": hashlib.sha256(app.read_bytes()).hexdigest(),
            "digest": "6" * 64,
        }
    return r28.build_candidate_context(
        loop_id="loop-r31",
        brief_digest="7" * 64,
        semantic_analysis_digest="8" * 64,
        semantic_directives_digest="9" * 64,
        ledger_digest="a" * 64,
        source={
            "sourceId": "source-r31",
            "sha256": source_sha,
            "size": source.stat().st_size,
            "path": "source.mp4",
        },
        candidate=candidate,
        timeline={
            "id": "timeline-r31",
            "canvas": {"durationMs": 5000},
            "tracks": [],
        },
        export_spec={"format": "mp4"},
    )


def growth_round_for(envelope, *, terminal=False):
    round_index = envelope["review"]["review_round"]
    current = envelope["candidate"]["candidate_id"]
    other = "selected-other-candidate"
    selected = _selected_result(other, envelope, round_index)
    result = {
        "contract_version": r31.GROWTH_R28_AUTHORITY["roundResultContract"],
        "round_result_id": "",
        "round_result_digest": "",
        "session_id": "gr28s1:" + ("1" * 64),
        "review_round": round_index,
        "package": {
            "operator_manifest_sha256": "2" * 64,
            "archive_sha256": "3" * 64,
            "package_digest": envelope["review"]["package_digest"],
            "sealed_mapping_digest": envelope["review"]["sealed_mapping_digest"],
            "prompt_digest": "4" * 64,
        },
        "capture": {
            "capture_id": envelope["capture"]["capture_id"],
            "capture_digest": envelope["capture"]["capture_digest"],
            "assistant_response_digest": envelope["capture"]["assistant_response_digest"],
            "conversation": {
                "conversation_id": envelope["capture"]["conversation"]["conversation_id"],
                "request_id": envelope["capture"]["conversation"]["request_id"],
                "operation_id": "operation-r31",
            },
            "bridge_r31_wrapper": None,
        },
        "pairwise": {
            "selection": "B",
            "selected_candidate_id": other,
            "output_digest": envelope["creator_event"]["handoff"]["pairwise"]["output_digest"],
            "rationale": "fixture pairwise rationale",
            "confidence": 0.8,
            "uncertainty": "fixture only",
        },
        "outcome": "winner",
        "selected_result": selected,
        "candidate_envelopes": {
            current: {
                "envelope_digest": envelope["envelope_digest"],
                "handoff_digest": envelope["candidate"]["handoff_digest"],
                "state": envelope["candidate"]["state"],
                "candidate_round": envelope["candidate"]["candidate_round"],
                "render_sha256": envelope["candidate"]["render_sha256"],
            },
            other: {
                "envelope_digest": selected["envelope_digest"],
                "handoff_digest": selected["handoff_digest"],
                "state": "winner",
                "candidate_round": round_index,
                "render_sha256": selected["render_sha256"],
            },
        },
        "terminal_winner": terminal,
        "creator_executable_handoff_emitted": True,
        "evidence_boundary": {
            "model_evidence": True,
            "human_ground_truth": False,
            "human_rating_evidence": False,
            "human_parity_inferred": False,
            "browser_mutation": False,
            "provider_mutation": False,
        },
    }
    result["round_result_id"] = "gr28rr1:" + r31._sha({
        "session_id": result["session_id"],
        "review_round": round_index,
        "capture_digest": result["capture"]["capture_digest"],
        "package_digest": result["package"]["package_digest"],
    })
    material = copy.deepcopy(result)
    material["round_result_digest"] = ""
    result["round_result_digest"] = r31._sha(material)
    return result


def bridge_round_for(envelope, growth_round):
    context_render = envelope["candidate"]
    return {
        "contract": r31.BRIDGE_R32_AUTHORITY["roundResultContract"],
        "state": "LIVE_REVIEW_PASS",
        "sessionId": "bridge-session-r32",
        "round": growth_round["review_round"],
        "conversation": {
            "conversationId": envelope["capture"]["conversation"]["conversation_id"],
            "canonicalUrl": (
                "https://chatgpt.com/c/"
                + envelope["capture"]["conversation"]["conversation_id"]
            ),
        },
        "sourceFingerprint": "5" * 64,
        "briefLineageDigest": "7" * 64,
        "packageDigest": growth_round["package"]["package_digest"],
        "sessionPackageDigest": "6" * 64,
        "promptDigest": growth_round["package"]["prompt_digest"],
        "attachments": [
            {
                "blindLabel": "A",
                "name": "review-A.mp4",
                "size": context_render["render_size"],
                "sha256": context_render["render_sha256"],
                "mime": "video/mp4",
            },
            {
                "blindLabel": "B",
                "name": "review-B.mp4",
                "size": context_render["render_size"] + 1,
                "sha256": "a" * 64,
                "mime": "video/mp4",
            },
        ],
        "requestId": growth_round["capture"]["conversation"]["request_id"],
        "operationId": growth_round["capture"]["conversation"]["operation_id"],
        "responseDigest": growth_round["capture"]["assistant_response_digest"],
        "captureDigest": growth_round["capture"]["capture_digest"],
        "model_evidence": True,
        "human_ground_truth": False,
        "retryUploadAuthorized": False,
        "retrySendAuthorized": False,
        "terminalAt": "2026-10-02T00:00:00Z",
    }


class R31AuthorityAndContinuityTests(unittest.TestCase):
    def test_exact_authorities_and_readiness_gate(self):
        self.assertEqual(
            r31.MEDIA_R23_AUTHORITY["producerSha"],
            "78c6982a91d7e3e8c037cd9ce740ee077babdccc",
        )
        self.assertEqual(
            r31.GROWTH_R28_AUTHORITY["producerSha"],
            "629a2b9ddf59b84eee4e87b257c161dad42831dc",
        )
        self.assertEqual(
            r31.BRIDGE_R32_AUTHORITY["producerSha"],
            "805bf628d3d2844549b54db1112736fae0200fc7",
        )
        report = r31.readiness_report()
        self.assertEqual(report["state"], "WAITING_GENUINE_CAPTURE")
        self.assertTrue(report["SOURCE_READY"])
        self.assertFalse(report["REAL_REVIEW_INGESTED"])
        self.assertFalse(report["REAL_REEDIT_EXECUTED"])
        self.assertFalse(report["NEXT_REVIEW_PACKAGE_READY"])
        self.assertFalse(report["PUBLISH_HANDOFF_READY"])
        self.assertFalse(report["providerMutation"])
        self.assertFalse(report["browserMutation"])
        self.assertFalse(report["humanParityClaimed"])

    def test_media_authority_profile_drift_fails_closed(self):
        broken = copy.deepcopy(r31.MEDIA_R23_AUTHORITY)
        broken["blobs"]["schema"] = "0" * 40
        with self.assertRaises(r31.AuthorityDrift):
            r31.validate_media_authority_profile(broken)

    def test_round_result_digest_and_round_overflow_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            context = build_context(Path(td))
            envelope = build_envelope(context)
            result = growth_round_for(envelope)
            parsed = r31.validate_growth_round_result(result)
            self.assertEqual(parsed["review_round"], 0)
            broken = copy.deepcopy(result)
            broken["package"]["package_digest"] = "f" * 64
            with self.assertRaises(r31.SessionDrift):
                r31.validate_growth_round_result(broken)
            bridge = bridge_round_for(envelope, result)
            bridge["round"] = 3
            with self.assertRaises(r31.RoundOverflow):
                r31.validate_bridge_r32_round(bridge)

    def test_full_bridge_growth_envelope_candidate_continuity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = build_context(root)
            envelope = build_envelope(context)
            growth = growth_round_for(envelope)
            bridge = bridge_round_for(envelope, growth)
            parsed = r31.validate_session_continuity(
                growth_round=growth,
                bridge_round=bridge,
                envelope=envelope,
                context=context,
                candidate_root=root,
            )
            self.assertEqual(
                parsed["candidate"]["render_sha256"],
                context["candidate"]["renderSha256"],
            )
            changed = copy.deepcopy(bridge)
            changed["responseDigest"] = "9" * 64
            with self.assertRaises(r31.SessionDrift):
                r31.validate_session_continuity(
                    growth_round=growth,
                    bridge_round=changed,
                    envelope=envelope,
                    context=context,
                    candidate_root=root,
                )

    def test_package_capture_and_selected_envelope_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = build_context(root)
            envelope = build_envelope(context)
            growth = growth_round_for(envelope)
            bridge = bridge_round_for(envelope, growth)
            broken = copy.deepcopy(envelope)
            broken["review"]["package_digest"] = "9" * 64
            material = copy.deepcopy(broken)
            material["envelope_digest"] = ""
            broken["envelope_digest"] = r31._sha(material)
            with self.assertRaises(Exception):
                r31.validate_session_continuity(
                    growth_round=growth,
                    bridge_round=bridge,
                    envelope=broken,
                    context=context,
                    candidate_root=root,
                )

    def test_journal_exact_replay_is_idempotent_changed_response_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = r31.Journal(Path(td) / "journal.jsonl")
            payload = {
                "sessionId": "session-r31",
                "round": 0,
                "responseDigest": "1" * 64,
            }
            self.assertEqual(
                ledger.append_once("review:0", "review", payload),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("review:0", "review", payload),
                "duplicate",
            )
            changed = dict(payload)
            changed["responseDigest"] = "2" * 64
            with self.assertRaises(r31.ReplayConflict):
                ledger.append_once("review:0", "review", changed)

    def test_growth_session_ledger_round_gap_and_third_reedit_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = build_context(root)
            envelope = build_envelope(context)
            result = growth_round_for(envelope)
            session = root / "session"
            session.mkdir()
            (session / "growth-r28-session-ledger.json").write_text(
                json.dumps({
                    "version": "growth.multiround_review_session_ledger.r28.v1",
                    "session_id": result["session_id"],
                    "identity": {"fixture": True},
                    "rounds": {
                        "0": {"raw_fingerprint": "1" * 64, "round_result": result},
                        "2": {"raw_fingerprint": "2" * 64, "round_result": result},
                    },
                    "requests": {},
                    "closed": False,
                    "terminal_round": None,
                }),
                encoding="utf-8",
            )
            with self.assertRaises(r31.RoundOverflow):
                r31.load_growth_session_round(session, 0)
            round_two_context = build_context(root / "round-two", round_index=2)
            round_two = build_envelope(round_two_context)
            with self.assertRaises(Exception):
                # The exact R29/R26 envelope gate rejects a third re-edit before
                # Creator verifies or invokes any Media checkout.
                r31.execute_media_r23_reedit(
                    media_checkout=Path(td) / "not-a-media-checkout",
                    candidate_root=root / "round-two",
                    context=round_two_context,
                    envelope=round_two,
                )

    def test_nonwinner_publish_validator_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            context = build_context(Path(td))
            tie = build_envelope(context, state="tie")
            with self.assertRaises(r23.EditorOutcomeIneligible):
                r31._terminal_growth_validator(
                    tie,
                    expected_source_id=context["source"]["sourceId"],
                    expected_render_sha256=context["candidate"]["renderSha256"],
                )


@unittest.skipUnless(
    os.environ.get("R31_MEDIA_R23_CHECKOUT")
    and os.environ.get("R31_GROWTH_R28_CHECKOUT"),
    "exact Media R23 and Growth R28 checkouts required",
)
class R31ExactIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(os.environ["R31_MEDIA_R23_CHECKOUT"]).resolve()
        cls.growth = Path(os.environ["R31_GROWTH_R28_CHECKOUT"]).resolve()
        r31.verify_media_r23_checkout(cls.media)
        r31.verify_growth_r28_checkout(cls.growth)
        env = dict(os.environ)
        env["GITHUB_SHA"] = r31.MEDIA_R23_AUTHORITY["producerSha"]
        proc = subprocess.run(
            ["node", str(cls.media / "tools/demo-r19-editorial-reedit.mjs")],
            cwd=cls.media,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr[-6000:])
        cls.demo_root = cls.media / ".artifacts/r19-demo"
        case_root = cls.demo_root / "cases/talking-head-vertical"
        cls.request = json.loads(
            (case_root / "request.json").read_text(encoding="utf-8")
        )
        candidate = cls.request["candidate"]
        timeline = cls.request["timeline"]
        source_uri = next(
            track for track in timeline["tracks"] if track["kind"] == "video"
        )["items"][0]["source"]["uri"]
        export_path = cls.demo_root / candidate["renderExportPath"]
        export_digest = r28._media_semantic_digest(
            cls.media, export_path, "render"
        )
        cls.context = r28.build_candidate_context(
            loop_id="r31-exact-integration",
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
            export_spec=cls.request["exportSpec"],
        )

    def setUp(self):
        for name in (".creator-r28", ".creator-r31-packages", "round-1", "round-2"):
            shutil.rmtree(self.demo_root / name, ignore_errors=True)

    def test_exact_checkout_blob_profiles(self):
        self.assertEqual(
            r31.verify_media_r23_checkout(self.media)["checkoutSha"],
            r31.MEDIA_R23_AUTHORITY["producerSha"],
        )
        self.assertEqual(
            r31.verify_growth_r28_checkout(self.growth)["checkoutSha"],
            r31.GROWTH_R28_AUTHORITY["producerSha"],
        )

    def test_real_media_reedit_and_exact_r23_next_round_export(self):
        envelope = build_envelope(self.context)
        result = r31.execute_media_r23_reedit(
            media_checkout=self.media,
            candidate_root=self.demo_root,
            context=self.context,
            envelope=envelope,
        )
        self.assertEqual(result["evidence"]["logicalEffects"], 1)
        self.assertNotEqual(
            result["evidence"]["before"]["sha256"],
            result["evidence"]["after"]["sha256"],
        )
        next_context = r31.build_next_context(
            prior=self.context,
            media_result=result,
            candidate_root=self.demo_root,
        )
        growth = growth_round_for(envelope)
        package = r31.export_media_r23_next_round(
            media_checkout=self.media,
            authority_profile=r31.MEDIA_R23_AUTHORITY,
            candidate_root=self.demo_root,
            before_context=self.context,
            after_context=next_context,
            growth_round=growth,
            envelope=envelope,
            session_id=growth["session_id"],
            out_dir=self.demo_root / ".creator-r31-packages" / "integration",
        )
        self.assertEqual(
            package["package"]["contractVersion"],
            "media.review_session_package.r23.v1",
        )
        self.assertEqual(package["package"]["reviewRound"], 1)
        self.assertEqual(
            package["package"]["producer"]["sha"],
            r31.MEDIA_R23_AUTHORITY["producerSha"],
        )
        self.assertEqual(
            package["package"]["challenger"]["render"]["sha256"],
            next_context["candidate"]["renderSha256"],
        )
        self.assertEqual(
            package["evidence"]["challengerRenderSha256"],
            result["evidence"]["after"]["sha256"],
        )
        replay = r31.execute_media_r23_reedit(
            media_checkout=self.media,
            candidate_root=self.demo_root,
            context=self.context,
            envelope=envelope,
        )
        self.assertTrue(replay["evidence"]["replayed"])
        self.assertEqual(replay["evidence"]["logicalEffects"], 0)
        self.assertEqual(
            replay["evidence"]["after"]["sha256"],
            result["evidence"]["after"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
