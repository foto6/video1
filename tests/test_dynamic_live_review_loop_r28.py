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
from creator_orchestrator import publish_execution as r21


def _bridge_target():
    return {
        "managedChatId": "managed-r28-test",
        "profileId": "profile-r28-test",
        "conversationId": "conversation-r28-test",
        "titleHint": "Dynamic video review",
        "expectedAccountMarkerHash": "a" * 64,
    }


def _unit_context(round_index: int = 0):
    candidate = {
        "candidateId": f"candidate-r28-r{round_index}",
        "roundIndex": round_index,
        "finalPath": "candidate/final.mp4",
        "renderSha256": "2" * 64,
        "renderSize": 200,
        "renderExportPath": "candidate/media.render_export.v1.json",
        "renderExportSha256": "3" * 64,
        "renderExportDigest": "4" * 64,
        "renderProducerSha": r28.MEDIA_R20_AUTHORITY["producerSha"],
        "editorialApplication": None,
    }
    if round_index > 0:
        candidate["editorialApplication"] = {
            "path": "candidate/media.editorial_reedit_application.v1.json",
            "fileSha256": "5" * 64,
            "digest": "6" * 64,
        }
    return r28.build_candidate_context(
        loop_id="loop-r28",
        brief_digest="7" * 64,
        semantic_analysis_digest="8" * 64,
        semantic_directives_digest="9" * 64,
        ledger_digest="a" * 64,
        source={
            "sourceId": "source-r28",
            "sha256": "1" * 64,
            "size": 100,
            "path": "source.mp4",
        },
        candidate=candidate,
        timeline={"id": "timeline-r28"},
        export_spec={"format": "mp4"},
    )


class R28AuthorityAndBoundaryTests(unittest.TestCase):
    def test_exact_authority_profiles_pin_supplied_green_heads(self):
        growth = r28.validate_growth_authority(
            r28.GROWTH_R25_AUTHORITY
        )
        media = r28.validate_media_authority(
            r28.MEDIA_R20_AUTHORITY
        )
        self.assertEqual(
            growth["producerSha"],
            "2c441ebaa017c7da72461316401aeaf445e3d6e5",
        )
        self.assertEqual(growth["ciRunId"], 36988158233)
        self.assertEqual(
            media["producerSha"],
            "b22174db3c772a49a21fb9f8b1d40828bf258005",
        )
        self.assertEqual(media["ciRunId"], 36988788032)
        self.assertFalse(growth["testFixture"])
        self.assertFalse(media["testFixture"])

    def test_authority_profiles_reject_malformed_sha_and_blob(self):
        growth = copy.deepcopy(r28.GROWTH_R25_AUTHORITY)
        growth["producerSha"] = "not-a-git-sha"
        with self.assertRaises(r28.R28Error):
            r28.validate_growth_authority(growth)

        media = copy.deepcopy(r28.MEDIA_R20_AUTHORITY)
        media["dynamicSchemaBlobSha1"] = "not-a-blob"
        with self.assertRaises(r28.R28Error):
            r28.validate_media_authority(media)

    def test_native_growth_envelope_binds_exact_authority(self):
        context = _unit_context()
        fixture_profile = {
            **r28.GROWTH_R25_AUTHORITY,
            "testFixture": True,
        }
        envelope = r28.build_test_growth_envelope(
            context=context,
            growth_profile=fixture_profile,
        )
        parsed = r28.validate_growth_external_review(
            envelope,
            growth_profile=fixture_profile,
        )
        self.assertEqual(
            parsed["growth_r25"]["producer_sha"],
            fixture_profile["producerSha"],
        )
        stale = copy.deepcopy(envelope)
        stale["growth_r25"]["producer_sha"] = "0" * 40
        material = copy.deepcopy(stale)
        material["envelope_digest"] = ""
        stale["envelope_digest"] = r28._sha(material)
        with self.assertRaises(r28.AuthorityDrift):
            r28.validate_growth_external_review(
                stale,
                growth_profile=fixture_profile,
            )

    def test_round_regression_and_max_round_fail_closed(self):
        context = _unit_context(round_index=1)
        profile = {
            **r28.GROWTH_R25_AUTHORITY,
            "testFixture": True,
        }
        envelope = r28.build_test_growth_envelope(
            context=context,
            growth_profile=profile,
        )
        review = r28.normalize_review(envelope)
        review["roundIndex"] = 0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "source.mp4").write_bytes(b"s")
            (root / "candidate").mkdir()
            (root / "candidate/final.mp4").write_bytes(b"x" * 200)
            (root / "candidate/media.render_export.v1.json").write_text("{}")
            with self.assertRaises(r28.RoundRegression):
                r28.validate_review_against_context(
                    review,
                    context,
                    candidate_root=root,
                )
        round_two = _unit_context(round_index=2)
        envelope_two = r28.build_test_growth_envelope(
            context=round_two,
            growth_profile=profile,
        )
        self.assertEqual(
            envelope_two["creator_event"]["handoff"]["state"],
            "targeted_reedit",
        )
        self.assertEqual(
            envelope_two["creator_event"]["handoff"]["reedit_round"],
            2,
        )

    def test_missing_media_application_evidence_fails_closed(self):
        context = _unit_context(round_index=1)
        broken = copy.deepcopy(context)
        broken["candidate"]["editorialApplication"] = None
        material = dict(broken)
        material.pop("contextDigest")
        broken["contextDigest"] = r28._sha(material)
        with self.assertRaises(r28.MissingMediaApplicationEvidence):
            r28.validate_candidate_context(broken)

    def test_duplicate_review_idempotent_conflict_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = r28.Ledger(Path(td) / "ledger.jsonl")
            payload = {
                "envelopeDigest": "a" * 64,
                "renderSha256": "b" * 64,
            }
            self.assertEqual(
                ledger.append_once("review:0", "review", payload),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("review:0", "review", payload),
                "duplicate",
            )
            with self.assertRaises(r28.ReviewReplayConflict):
                ledger.append_once(
                    "review:0",
                    "review",
                    {
                        "envelopeDigest": "c" * 64,
                        "renderSha256": "b" * 64,
                    },
                )

    def test_readiness_exposes_dynamic_capture_blocker(self):
        report = r28.readiness_report()
        self.assertTrue(report["SOURCE_READY"])
        self.assertFalse(report["REAL_REVIEW_INGESTED"])
        self.assertFalse(report["REAL_REEDIT_EXECUTED"])
        self.assertFalse(report["NEXT_REVIEW_PACKAGE_READY"])
        self.assertFalse(report["PUBLISH_HANDOFF_READY"])
        self.assertEqual(
            report["state"],
            "BLOCKED_WAITING_DYNAMIC_REVIEW_CAPTURE",
        )
        self.assertFalse(
            report["missingDynamicAuthority"]["growthR26"]["available"]
        )
        self.assertFalse(
            report["missingDynamicAuthority"]["bridgeR30"]["available"]
        )


@unittest.skipUnless(
    os.environ.get("R28_MEDIA_R20_CHECKOUT")
    and os.environ.get("R28_GROWTH_R25_CHECKOUT"),
    "exact Media R20 and Growth R25 checkouts required",
)
class R28ExactDynamicIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(
            os.environ["R28_MEDIA_R20_CHECKOUT"]
        ).resolve()
        cls.growth = Path(
            os.environ["R28_GROWTH_R25_CHECKOUT"]
        ).resolve()
        r28.verify_media_checkout(cls.media, r28.MEDIA_R20_AUTHORITY)
        r28.verify_growth_checkout(cls.growth, r28.GROWTH_R25_AUTHORITY)
        env = dict(os.environ)
        env["GITHUB_SHA"] = r28.MEDIA_R20_AUTHORITY["producerSha"]
        result = subprocess.run(
            [
                "node",
                str(cls.media / "tools/demo-r19-editorial-reedit.mjs"),
            ],
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
        cls.request = json.loads(
            (cls.case_root / "request.json").read_text(encoding="utf-8")
        )
        candidate = cls.request["candidate"]
        timeline = cls.request["timeline"]
        source_uri = (
            next(
                track for track in timeline["tracks"]
                if track["kind"] == "video"
            )["items"][0]["source"]["uri"]
        )
        export_path = cls.demo_root / candidate["renderExportPath"]
        export_digest = r28._media_semantic_digest(
            cls.media,
            export_path,
            "render",
        )
        cls.context = r28.build_candidate_context(
            loop_id="r28-exact-integration",
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
        cls.fixture_growth_profile = {
            **r28.GROWTH_R25_AUTHORITY,
            "testFixture": True,
        }
        cls.envelope = r28.build_test_growth_envelope(
            context=cls.context,
            growth_profile=cls.fixture_growth_profile,
        )

    def test_stale_exact_producer_and_schema_blob_fail_checkout_verification(self):
        stale_growth = copy.deepcopy(r28.GROWTH_R25_AUTHORITY)
        stale_growth["producerSha"] = "0" * 40
        with self.assertRaises(r28.AuthorityDrift):
            r28.verify_growth_checkout(self.growth, stale_growth)

        stale_media = copy.deepcopy(r28.MEDIA_R20_AUTHORITY)
        stale_media["dynamicSchemaBlobSha1"] = "0" * 40
        with self.assertRaises(r28.AuthorityDrift):
            r28.verify_media_checkout(self.media, stale_media)

    def _write_inputs(self, root: Path, envelope=None):
        context_path = root / "context.json"
        review_path = root / "review.json"
        media_auth = root / "media-authority.json"
        growth_auth = root / "growth-authority.json"
        target = root / "bridge-target.json"
        context_path.write_text(
            json.dumps(self.context), encoding="utf-8"
        )
        review_path.write_text(
            json.dumps(envelope or self.envelope), encoding="utf-8"
        )
        media_auth.write_text(
            json.dumps(r28.MEDIA_R20_AUTHORITY), encoding="utf-8"
        )
        growth_auth.write_text(
            json.dumps(self.fixture_growth_profile), encoding="utf-8"
        )
        target.write_text(
            json.dumps(_bridge_target()), encoding="utf-8"
        )
        return context_path, review_path, media_auth, growth_auth, target

    def test_exact_reedit_dynamic_package_restart_and_lost_ack(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_path, review_path, _, _, _ = self._write_inputs(root)
            out = self.demo_root / ".creator-r28-integration"
            shutil.rmtree(out, ignore_errors=True)
            with self.assertRaises(r28.InjectedLostAck):
                r28.run_dynamic_review(
                    media_checkout=self.media,
                    growth_checkout=self.growth,
                    media_authority=r28.MEDIA_R20_AUTHORITY,
                    growth_authority=self.fixture_growth_profile,
                    candidate_root=self.demo_root,
                    candidate_context_path=context_path,
                    review_envelope_path=review_path,
                    out_dir=out,
                    bridge_target=_bridge_target(),
                    inject_lost_ack_after_media=True,
                )
            recovered = r28.run_dynamic_review(
                media_checkout=self.media,
                growth_checkout=self.growth,
                media_authority=r28.MEDIA_R20_AUTHORITY,
                growth_authority=self.fixture_growth_profile,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=review_path,
                out_dir=out,
                bridge_target=_bridge_target(),
            )
            self.assertEqual(
                recovered["state"],
                "BLOCKED_WAITING_DYNAMIC_REVIEW_CAPTURE",
            )
            self.assertFalse(recovered["REAL_REVIEW_INGESTED"])
            self.assertFalse(recovered["REAL_REEDIT_EXECUTED"])
            self.assertTrue(recovered["NEXT_REVIEW_PACKAGE_READY"])
            self.assertFalse(recovered["PUBLISH_HANDOFF_READY"])
            self.assertTrue(recovered["mediaReplay"])
            self.assertNotEqual(
                recovered["beforeRenderSha256"],
                recovered["afterRenderSha256"],
            )
            self.assertEqual(recovered["nextRoundIndex"], 1)

            duplicate = r28.run_dynamic_review(
                media_checkout=self.media,
                growth_checkout=self.growth,
                media_authority=r28.MEDIA_R20_AUTHORITY,
                growth_authority=self.fixture_growth_profile,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=review_path,
                out_dir=out,
                bridge_target=_bridge_target(),
            )
            self.assertTrue(duplicate["reviewReplay"])
            self.assertTrue(duplicate["mediaReplay"])
            self.assertEqual(
                duplicate["nextPackageDigest"],
                recovered["nextPackageDigest"],
            )
            self.assertEqual(
                duplicate["afterRenderSha256"],
                recovered["afterRenderSha256"],
            )

    def test_conflicting_review_same_round_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_path, review_path, _, _, _ = self._write_inputs(root)
            out = self.demo_root / ".creator-r28-conflict"
            shutil.rmtree(out, ignore_errors=True)
            r28.run_dynamic_review(
                media_checkout=self.media,
                growth_checkout=self.growth,
                media_authority=r28.MEDIA_R20_AUTHORITY,
                growth_authority=self.fixture_growth_profile,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=review_path,
                out_dir=out,
                bridge_target=_bridge_target(),
            )
            changed = copy.deepcopy(self.envelope)
            changed["capture"]["capture_digest"] = "e" * 64
            changed["envelope_id"] = "gr25ce1:" + r28._sha(
                {
                    "growth_producer_sha": self.fixture_growth_profile[
                        "producerSha"
                    ],
                    "capture_digest": changed["capture"]["capture_digest"],
                    "handoff_digest": changed["handoff"]["handoff_digest"],
                    "reedit_round": changed["handoff"]["reedit_round"],
                }
            )
            material = copy.deepcopy(changed)
            material["envelope_digest"] = ""
            changed["envelope_digest"] = r28._sha(material)
            changed_path = root / "changed-review.json"
            changed_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(r28.ReviewReplayConflict):
                r28.run_dynamic_review(
                    media_checkout=self.media,
                    growth_checkout=self.growth,
                    media_authority=r28.MEDIA_R20_AUTHORITY,
                    growth_authority=self.fixture_growth_profile,
                    candidate_root=self.demo_root,
                    candidate_context_path=context_path,
                    review_envelope_path=changed_path,
                    out_dir=out,
                    bridge_target=_bridge_target(),
                )

    def test_package_digest_drift_is_detected_on_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_path, review_path, _, _, _ = self._write_inputs(root)
            out = self.demo_root / ".creator-r28-package-drift"
            shutil.rmtree(out, ignore_errors=True)
            first = r28.run_dynamic_review(
                media_checkout=self.media,
                growth_checkout=self.growth,
                media_authority=r28.MEDIA_R20_AUTHORITY,
                growth_authority=self.fixture_growth_profile,
                candidate_root=self.demo_root,
                candidate_context_path=context_path,
                review_envelope_path=review_path,
                out_dir=out,
                bridge_target=_bridge_target(),
            )
            self.assertTrue(first["NEXT_REVIEW_PACKAGE_READY"])
            package = Path(first["nextPackagePath"])
            self.assertTrue(package.is_file())
            original = package.read_text(encoding="utf-8")
            package.write_text(original + "\n", encoding="utf-8")
            with self.assertRaises(r28.MediaR20Error):
                r28.run_dynamic_review(
                    media_checkout=self.media,
                    growth_checkout=self.growth,
                    media_authority=r28.MEDIA_R20_AUTHORITY,
                    growth_authority=self.fixture_growth_profile,
                    candidate_root=self.demo_root,
                    candidate_context_path=context_path,
                    review_envelope_path=review_path,
                    out_dir=out,
                    bridge_target=_bridge_target(),
                )

    def test_winner_only_publish_handoff_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_path = root / "final.mp4"
            ffmpeg = shutil.which("ffmpeg")
            self.assertIsNotNone(ffmpeg)
            result = subprocess.run(
                [
                    ffmpeg, "-hide_banner", "-nostdin", "-y",
                    "-f", "lavfi",
                    "-i", "color=c=blue:s=360x640:r=30:d=15.2",
                    "-threads", "1", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(media_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            asset = r21.probe_media(media_path)
            context = r28.build_candidate_context(
                loop_id="winner-loop",
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
                    "candidateId": "winner-candidate",
                    "roundIndex": 0,
                    "finalPath": "final.mp4",
                    "renderSha256": asset.sha256,
                    "renderSize": asset.size_bytes,
                    "renderExportPath": "render.json",
                    "renderExportSha256": "2" * 64,
                    "renderExportDigest": "3" * 64,
                    "renderProducerSha": r28.MEDIA_R20_AUTHORITY[
                        "producerSha"
                    ],
                    "editorialApplication": None,
                },
                timeline={"id": "winner-timeline"},
                export_spec={"format": "mp4"},
            )
            winner = r28.build_test_growth_envelope(
                context=context,
                state="winner",
                growth_profile=self.fixture_growth_profile,
            )
            ledger = r28.Ledger(root / "winner-ledger.jsonl")
            bundle = r28.build_final_bundle(
                context=context,
                envelope=winner,
                ledger=ledger,
                growth_profile=self.fixture_growth_profile,
                media_profile=r28.MEDIA_R20_AUTHORITY,
            )
            auth = r23.synthetic_release_authorization(
                bundle=bundle,
                platform="tiktok",
                destination="privacy:SELF_ONLY",
            )
            handoff = r28.materialize_publish_handoff(
                context=context,
                envelope=winner,
                bundle=bundle,
                final_path=media_path,
                release_authorization=auth,
                platform="tiktok",
                account_id="account-r28",
                destination="privacy:SELF_ONLY",
                credential_ref="vault-ref://r28/tiktok",
                authorization_ref="oauth-grant-ref://r28/tiktok",
                caption="R28 winner boundary",
                cta="Learn more",
                growth_profile=self.fixture_growth_profile,
            )
            self.assertEqual(
                handoff["editor"]["renderSha256"],
                asset.sha256,
            )
            tie = r28.build_test_growth_envelope(
                context=context,
                state="tie",
                growth_profile=self.fixture_growth_profile,
            )
            with self.assertRaises(r23.EditorOutcomeIneligible):
                r28.materialize_publish_handoff(
                    context=context,
                    envelope=tie,
                    bundle=bundle,
                    final_path=media_path,
                    release_authorization=auth,
                    platform="tiktok",
                    account_id="account-r28",
                    destination="privacy:SELF_ONLY",
                    credential_ref="vault-ref://r28/tiktok",
                    authorization_ref="oauth-grant-ref://r28/tiktok",
                    caption="R28 tie",
                    cta="Learn more",
                    growth_profile=self.fixture_growth_profile,
                )


if __name__ == "__main__":
    unittest.main()
