from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import dynamic_live_review_loop as r28
from creator_orchestrator import editor_publish_handoff as r23
from creator_orchestrator import live_e2e_consumer as r29
from creator_orchestrator import publish_execution as publish_exec


def unit_context(*, round_index: int = 0, render_sha: str = "2" * 64):
    candidate = {
        "candidateId": f"candidate-r29-r{round_index}",
        "roundIndex": round_index,
        "finalPath": "candidate/final.mp4",
        "renderSha256": render_sha,
        "renderSize": 200,
        "renderExportPath": "candidate/media.render_export.v1.json",
        "renderExportSha256": "3" * 64,
        "renderExportDigest": "4" * 64,
        "renderProducerSha": r29.MEDIA_R21["producerSha"],
        "editorialApplication": None,
    }
    if round_index:
        candidate["editorialApplication"] = {
            "path": "candidate/media.editorial_reedit_application.v1.json",
            "fileSha256": "5" * 64,
            "digest": "6" * 64,
        }
    return r28.build_candidate_context(
        loop_id="loop-r29",
        brief_digest="7" * 64,
        semantic_analysis_digest="8" * 64,
        semantic_directives_digest="9" * 64,
        ledger_digest="a" * 64,
        source={
            "sourceId": "source-r29",
            "sha256": "1" * 64,
            "size": 100,
            "path": "source.mp4",
        },
        candidate=candidate,
        timeline={"id": "timeline-r29"},
        export_spec={"format": "mp4"},
    )


class R29AuthorityEnvelopeTests(unittest.TestCase):
    def test_readiness_is_source_ready_but_waiting_for_live_growth(self):
        report = r29.readiness_report()
        self.assertEqual(report["state"], "BLOCKED_WAITING_LIVE_GROWTH_OUTPUT")
        self.assertTrue(report["SOURCE_READY"])
        self.assertFalse(report["REAL_REVIEW_INGESTED"])
        self.assertFalse(report["REAL_REEDIT_EXECUTED"])
        self.assertFalse(report["NEXT_REVIEW_PACKAGE_READY"])
        self.assertFalse(report["PUBLISH_HANDOFF_READY"])
        self.assertFalse(report["fabricatedLiveEvidence"])
        self.assertEqual(
            report["mediaR21"]["producerSha"],
            "d753e9e4c1f4448386608a1425232dbc1dba87ea",
        )
        self.assertEqual(
            report["growthR26"]["producerSha"],
            "e844ed2daaaca9e9694fe1e0fb6b8b7bfac69cbc",
        )
        self.assertEqual(
            report["bridgeR30"]["producerSha"],
            "ceaee873231a8552c5b7324083baa800eec566a8",
        )

    def test_fixture_envelope_uses_exact_current_authorities(self):
        context = unit_context()
        envelope = r29.build_test_envelope(context=context)
        parsed = r29.validate_growth_r26_envelope(envelope)
        self.assertEqual(
            parsed["contract_version"],
            "growth.dynamic_creator_external_review_envelope.r26.v1",
        )
        self.assertEqual(
            parsed["growth_r26"]["producer_sha"],
            r29.GROWTH_R26["producerSha"],
        )
        self.assertEqual(
            parsed["bridge_authority"],
            r29._expected_bridge_authority(),
        )
        self.assertEqual(
            parsed["media_authority"]["producer_sha"],
            r29.MEDIA_R21["producerSha"],
        )
        self.assertEqual(
            parsed["media_authority"]["package_contract"],
            "media.dynamic_review_package.r21.v1",
        )

    def test_stale_growth_sha_fails_closed(self):
        envelope = r29.build_test_envelope(context=unit_context())
        stale = copy.deepcopy(envelope)
        stale["growth_r26"]["producer_sha"] = "0" * 40
        material = copy.deepcopy(stale)
        material["envelope_digest"] = ""
        stale["envelope_digest"] = r29._sha(material)
        with self.assertRaises(r29.AuthorityDrift):
            r29.validate_growth_r26_envelope(stale)

    def test_stale_bridge_r30_authority_fails_closed(self):
        envelope = r29.build_test_envelope(context=unit_context())
        changed = copy.deepcopy(envelope)
        changed["bridge_authority"]["producer_sha"] = "0" * 40
        material = copy.deepcopy(changed)
        material["envelope_digest"] = ""
        changed["envelope_digest"] = r29._sha(material)
        with self.assertRaises(r29.AuthorityDrift):
            r29.validate_growth_r26_envelope(changed)

    def test_wrong_sealed_mapping_fails_closed(self):
        envelope = r29.build_test_envelope(context=unit_context())
        changed = copy.deepcopy(envelope)
        changed["review"]["sealed_mapping_digest"] = "0" * 64
        material = copy.deepcopy(changed)
        material["envelope_digest"] = ""
        changed["envelope_digest"] = r29._sha(material)
        with self.assertRaisesRegex(
            r29.EnvelopeDrift,
            "package/sealed-mapping/round",
        ):
            r29.validate_growth_r26_envelope(changed)

    def test_selected_candidate_identity_drift_fails_closed(self):
        envelope = r29.build_test_envelope(
            context=unit_context(),
            state="winner",
        )
        changed = copy.deepcopy(envelope)
        changed["review"]["selected_candidate_id"] = "wrong-candidate"
        material = copy.deepcopy(changed)
        material["envelope_digest"] = ""
        changed["envelope_digest"] = r29._sha(material)
        with self.assertRaisesRegex(r29.EnvelopeDrift, "pairwise selected"):
            r29.validate_growth_r26_envelope(changed)

    def test_review_round_drift_fails_before_media(self):
        context = unit_context()
        review = r29.normalize_review(
            r29.build_test_envelope(context=context)
        )
        review["roundIndex"] = 1
        with self.assertRaises(r29.RoundError):
            r29.validate_review_context(
                review,
                context,
                candidate_root=Path("."),
            )

    def test_max_round_targeted_reedit_is_rejected(self):
        context = unit_context(round_index=2)
        envelope = r29.build_test_envelope(context=context)
        review = r29.normalize_review(envelope)
        self.assertEqual(review["state"], "targeted_reedit")
        self.assertEqual(review["roundIndex"], 2)
        with self.assertRaises(r29.RoundError):
            r29._require_targeted_round(review)

    def test_compat_adapter_preserves_allowlisted_directives(self):
        envelope = r29.build_test_envelope(context=unit_context())
        review = r29.normalize_review(envelope)
        compat = r29._compat_review(review)
        upstream = review["handoff"]["directives"]
        adapted = compat["handoff"]["directives"]
        self.assertEqual(len(upstream), len(adapted))
        for left, right in zip(upstream, adapted):
            for key in (
                "operation", "start_ms", "end_ms", "defect_category",
                "severity", "evidence", "confidence", "uncertainty",
                "source_observation_id",
            ):
                self.assertEqual(left[key], right[key])
            self.assertFalse(right["upstream_proposed_edit_executable"])
        self.assertEqual(
            compat["handoff"]["reedit_round"],
            review["roundIndex"],
        )

    def test_duplicate_review_is_idempotent_conflict_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = r29.Ledger(Path(td) / "ledger.jsonl")
            payload = {
                "envelopeDigest": "a" * 64,
                "renderSha256": "b" * 64,
            }
            self.assertEqual(
                ledger.append_once("review:0", "growth_r26_live_review", payload),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("review:0", "growth_r26_live_review", payload),
                "duplicate",
            )
            with self.assertRaises(r29.ReviewConflict):
                ledger.append_once(
                    "review:0",
                    "growth_r26_live_review",
                    {
                        "envelopeDigest": "c" * 64,
                        "renderSha256": "b" * 64,
                    },
                )


class R29WinnerBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_winner_only_publish_handoff_uses_strict_r29_validators(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            final = root / "final.mp4"
            proc = subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-nostdin", "-y",
                    "-f", "lavfi",
                    "-i", "color=c=blue:s=360x640:r=30:d=15.2",
                    "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(final),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=90,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
            asset = publish_exec.probe_media(final)
            context = r28.build_candidate_context(
                loop_id="winner-r29",
                brief_digest="a" * 64,
                semantic_analysis_digest="b" * 64,
                semantic_directives_digest="c" * 64,
                ledger_digest="d" * 64,
                source={
                    "sourceId": "winner-source",
                    "sha256": "1" * 64,
                    "size": 100,
                    "path": "source.mp4",
                },
                candidate={
                    "candidateId": "winner-candidate-r29",
                    "roundIndex": 0,
                    "finalPath": "final.mp4",
                    "renderSha256": asset.sha256,
                    "renderSize": asset.size_bytes,
                    "renderExportPath": "render.json",
                    "renderExportSha256": "2" * 64,
                    "renderExportDigest": "3" * 64,
                    "renderProducerSha": r29.MEDIA_R21["producerSha"],
                    "editorialApplication": None,
                },
                timeline={"id": "winner-r29-timeline"},
                export_spec={"format": "mp4"},
            )
            envelope = r29.build_test_envelope(
                context=context,
                state="winner",
            )
            ledger = r29.Ledger(root / "winner-ledger.jsonl")
            bundle = r29._winner_bundle(
                context=context,
                envelope=envelope,
                ledger=ledger,
            )
            auth = r23.synthetic_release_authorization(
                bundle=bundle,
                platform="tiktok",
                destination="privacy:SELF_ONLY",
            )
            target = {
                "platform": "tiktok",
                "accountId": "account-r29",
                "destination": "privacy:SELF_ONLY",
                "credentialRef": "vault-ref://r29/tiktok",
                "authorizationRef": "oauth-grant-ref://r29/tiktok",
                "caption": "R29 winner boundary",
                "cta": "Learn more",
            }
            handoff = r29.materialize_publish_handoff(
                context=context,
                envelope=envelope,
                bundle=bundle,
                final_path=final,
                release_authorization=auth,
                publish_target=target,
            )
            self.assertEqual(
                handoff["editor"]["renderSha256"],
                asset.sha256,
            )
            self.assertFalse(handoff["livePublishingExecuted"])

            for state in ("tie", "insufficient_evidence", "human_review"):
                with self.subTest(state=state):
                    nonwinner = r29.build_test_envelope(
                        context=context,
                        state=state,
                    )
                    with self.assertRaises(r23.EditorOutcomeIneligible):
                        r29.materialize_publish_handoff(
                            context=context,
                            envelope=nonwinner,
                            bundle=bundle,
                            final_path=final,
                            release_authorization=auth,
                            publish_target=target,
                        )


@unittest.skipUnless(
    os.environ.get("R29_MEDIA_R21_CHECKOUT")
    and os.environ.get("R29_GROWTH_R26_CHECKOUT"),
    "exact Media R21 and Growth R26 checkouts required",
)
class R29ExactAuthorityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(os.environ["R29_MEDIA_R21_CHECKOUT"]).resolve()
        cls.growth = Path(os.environ["R29_GROWTH_R26_CHECKOUT"]).resolve()
        cls.bridge = (
            None
            if not os.environ.get("R29_BRIDGE_R30_CHECKOUT")
            else Path(os.environ["R29_BRIDGE_R30_CHECKOUT"]).resolve()
        )
        r29.verify_media_r21_checkout(cls.media)
        r29.verify_growth_r26_checkout(cls.growth)
        if cls.bridge is not None:
            r29.verify_bridge_r30_checkout(cls.bridge)

        env = dict(os.environ)
        env["GITHUB_SHA"] = r29.MEDIA_R21["producerSha"]
        result = subprocess.run(
            ["node", str(cls.media / "tools/demo-r19-editorial-reedit.mjs")],
            cwd=cls.media,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr[-6000:])
        cls.demo_root = cls.media / ".artifacts/r19-demo"
        cls.case_root = cls.demo_root / "cases/talking-head-vertical"
        request = json.loads(
            (cls.case_root / "request.json").read_text(encoding="utf-8")
        )
        candidate = request["candidate"]
        timeline = request["timeline"]
        source_uri = next(
            track for track in timeline["tracks"] if track["kind"] == "video"
        )["items"][0]["source"]["uri"]
        export_path = cls.demo_root / candidate["renderExportPath"]
        export_digest = r28._media_semantic_digest(
            cls.media, export_path, "render"
        )
        cls.context = r28.build_candidate_context(
            loop_id="r29-exact-integration",
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
        cls.envelope = r29.build_test_envelope(context=cls.context)

    def setUp(self):
        for name in (
            ".creator-r28",
            ".creator-r29-r21-packages",
            "round-1",
            "round-2",
        ):
            shutil.rmtree(self.demo_root / name, ignore_errors=True)

    def test_exact_checkout_sha_and_blob_drift_fail_closed(self):
        self.assertEqual(
            r29.verify_media_r21_checkout(self.media)["checkoutSha"],
            r29.MEDIA_R21["producerSha"],
        )
        self.assertEqual(
            r29.verify_growth_r26_checkout(self.growth)["checkoutSha"],
            r29.GROWTH_R26["producerSha"],
        )
        if self.bridge is not None:
            self.assertEqual(
                r29.verify_bridge_r30_checkout(self.bridge)["checkoutSha"],
                r29.BRIDGE_R30["producerSha"],
            )

        original = r29.MEDIA_R21["reviewRoundSchemaBlobSha1"]
        try:
            r29.MEDIA_R21["reviewRoundSchemaBlobSha1"] = "0" * 40
            with self.assertRaises(r29.AuthorityDrift):
                r29.verify_media_r21_checkout(self.media)
        finally:
            r29.MEDIA_R21["reviewRoundSchemaBlobSha1"] = original

    def test_exact_media_reedit_and_r21_next_round_package(self):
        review = r29.normalize_review(self.envelope)
        compat = r29._compat_review(review)
        result = r28.execute_media_reedit(
            media_checkout=self.media,
            media_profile=r29.MEDIA_R21_COMPAT,
            candidate_root=self.demo_root,
            context=self.context,
            review=compat,
            out_dir=self.demo_root,
        )
        self.assertEqual(result["evidence"]["logicalEffects"], 1)
        self.assertNotEqual(
            result["evidence"]["before"]["sha256"],
            result["evidence"]["after"]["sha256"],
        )
        self.assertEqual(
            result["application"]["contractVersion"],
            "media.editorial_reedit_application.v1",
        )
        self.assertEqual(
            result["application"]["producer"]["sha"],
            r29.MEDIA_R21["producerSha"],
        )
        self.assertEqual(
            result["renderExport"]["producer"]["sha"],
            r29.MEDIA_R21["producerSha"],
        )

        replay = r28.execute_media_reedit(
            media_checkout=self.media,
            media_profile=r29.MEDIA_R21_COMPAT,
            candidate_root=self.demo_root,
            context=self.context,
            review=compat,
            out_dir=self.demo_root,
        )
        self.assertEqual(replay["evidence"]["logicalEffects"], 0)
        self.assertTrue(replay["evidence"]["replayed"])
        self.assertEqual(
            replay["evidence"]["resultDigest"],
            result["evidence"]["resultDigest"],
        )

        challenger = r29._next_context(
            prior=self.context,
            media_result=result,
            candidate_root=self.demo_root,
        )
        package = r29.build_media_r21_round_bundle(
            media_checkout=self.media,
            candidate_root=self.demo_root,
            baseline=self.context,
            challenger=challenger,
            envelope=self.envelope,
            out_dir=self.demo_root / ".creator-r29-r21-packages/test",
        )
        self.assertTrue(Path(package["bundlePath"]).is_file())
        self.assertEqual(package["reviewRound"], 1)
        self.assertEqual(
            package["dynamicGrowthHandoffDigest"],
            self.envelope["candidate"]["handoff_digest"],
        )
        self.assertNotEqual(
            package["dynamicGrowthHandoffDigest"],
            package["mediaCompatibilityHandoffDigest"],
        )
        bundle = json.loads(Path(package["bundlePath"]).read_text(encoding="utf-8"))
        self.assertEqual(
            bundle["producer"]["sha"],
            r29.MEDIA_R21["producerSha"],
        )
        self.assertFalse(bundle["modelReviewPerformed"])
        self.assertFalse(bundle["providerPublish"])
        self.assertFalse(bundle["humanQuality"])

    def test_wrong_render_bytes_fail_before_media_effect(self):
        context = copy.deepcopy(self.context)
        original = self.demo_root / context["candidate"]["finalPath"]
        backup = original.read_bytes()
        try:
            original.write_bytes(backup + b"tamper")
            review = r29.normalize_review(self.envelope)
            with self.assertRaises(r29.EnvelopeDrift):
                r29.validate_review_context(
                    review,
                    context,
                    candidate_root=self.demo_root,
                )
        finally:
            original.write_bytes(backup)


if __name__ == "__main__":
    unittest.main()
