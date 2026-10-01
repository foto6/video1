from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import autonomous_editor_loop as r22
from creator_orchestrator import autonomous_reels as reels
from creator_orchestrator import editor_publish_handoff as r23
from creator_orchestrator import publish_execution as r21
from creator_orchestrator import publish_providers as r12


def make_asset(root: Path, *, name: str = "final.mp4", data: bytes = b"r23-final"):
    path = root / name
    path.write_bytes(data)
    return r21.MediaAsset(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        duration_seconds=30.0,
        width=1080,
        height=1920,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
    )


def build_fixture(root: Path, platform: str = "tiktok"):
    asset = make_asset(root)
    bundle = r23.synthetic_editor_bundle_for_asset(asset)
    destination = (
        "privacy:SELF_ONLY"
        if platform == "tiktok"
        else (
            "privacy:private"
            if platform == "youtube_shorts"
            else "profile:account-r23"
        )
    )
    account = "account-r23"
    auth = r23.synthetic_release_authorization(
        bundle=bundle,
        platform=platform,
        destination=destination,
    )
    handoff = r23.build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=asset,
        release_authorization=auth,
        platform=platform,
        account_id=account,
        destination=destination,
        credential_ref=f"vault-ref://{platform}/r23",
        authorization_ref=f"oauth-grant-ref://{platform}/r23",
        caption="R23 synthetic handoff",
        cta="Learn more",
        allow_synthetic_editor=True,
    )
    return asset, bundle, auth, handoff


def rehash_handoff(value):
    value = json.loads(reels.canonical_json(value))
    identity = {
        key: item
        for key, item in value.items()
        if key not in {"handoffId", "handoffDigest"}
    }
    value["handoffId"] = "eph1:" + reels.sha256_json(identity)
    material = dict(value)
    material.pop("handoffDigest")
    value["handoffDigest"] = reels.sha256_json(material)
    return value


class R23EditorPublishHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_contract_binds_source_render_decision_auth_and_target(self):
        asset, bundle, auth, handoff = build_fixture(self.root)
        validated = r23.validate_editor_publish_handoff(
            handoff,
            allow_synthetic_editor=True,
        )
        self.assertEqual(
            validated["contractVersion"],
            "creator.editor_publish_handoff.v1",
        )
        self.assertEqual(
            validated["source"]["sourceSha256"],
            bundle["lineage"]["sourceSha256"],
        )
        self.assertEqual(
            validated["editor"]["renderSha256"],
            asset.sha256,
        )
        self.assertEqual(
            validated["editor"]["decisionDigest"],
            bundle["decision"]["decisionDigest"],
        )
        self.assertEqual(
            validated["releaseAuthorization"],
            auth,
        )
        self.assertEqual(
            validated["target"]["accountId"],
            "account-r23",
        )

    def test_noneligible_editor_states_fail_closed(self):
        _, bundle, _, _ = build_fixture(self.root)
        for state in (
            "tie",
            "insufficient_evidence",
            "human_review_required",
            "objective_render_failure",
        ):
            with self.subTest(state=state):
                broken = json.loads(reels.canonical_json(bundle))
                broken["decision"]["state"] = state
                with self.assertRaises(r23.EditorOutcomeIneligible):
                    r23.validate_terminal_editor_bundle(
                        broken,
                        allow_synthetic_editor=True,
                    )
        review = {
            "contractVersion": r22.HUMAN_REVIEW_VERSION,
            "state": "human_review",
            "humanReviewRequired": True,
        }
        with self.assertRaises(r23.EditorOutcomeIneligible):
            r23.validate_terminal_editor_bundle(
                review,
                allow_synthetic_editor=True,
            )

    def test_wrong_or_stale_final_artifact_sha_rejected(self):
        asset, bundle, auth, _ = build_fixture(self.root)
        stale = make_asset(
            self.root,
            name="stale.mp4",
            data=b"wrong-candidate-bytes",
        )
        with self.assertRaises(r23.ArtifactLineageMismatch):
            r23.build_editor_publish_handoff(
                editor_bundle=bundle,
                media_asset=stale,
                release_authorization=auth,
                platform="tiktok",
                account_id="account-r23",
                destination="privacy:SELF_ONLY",
                credential_ref="vault-ref://tiktok/r23",
                authorization_ref="oauth-grant-ref://tiktok/r23",
                caption="wrong",
                cta="Learn more",
                allow_synthetic_editor=True,
            )
        self.assertNotEqual(asset.sha256, stale.sha256)

    def test_release_authorization_must_bind_winner_and_editor_bundle(self):
        _, bundle, auth, _ = build_fixture(self.root)
        asset = make_asset(self.root, data=b"r23-final")
        wrong_candidate = dict(auth)
        wrong_candidate["candidateId"] = "candidate22r:" + ("9" * 64)
        with self.assertRaises(reels.PublishGateError):
            r23.build_editor_publish_handoff(
                editor_bundle=bundle,
                media_asset=asset,
                release_authorization=wrong_candidate,
                platform="tiktok",
                account_id="account-r23",
                destination="privacy:SELF_ONLY",
                credential_ref="vault-ref://tiktok/r23",
                authorization_ref="oauth-grant-ref://tiktok/r23",
                caption="test",
                cta="Learn more",
                allow_synthetic_editor=True,
            )
        wrong_lineage = dict(auth)
        wrong_lineage["lineageHash"] = "sha256:" + ("8" * 64)
        with self.assertRaises(reels.PublishGateError):
            r23.build_editor_publish_handoff(
                editor_bundle=bundle,
                media_asset=asset,
                release_authorization=wrong_lineage,
                platform="tiktok",
                account_id="account-r23",
                destination="privacy:SELF_ONLY",
                credential_ref="vault-ref://tiktok/r23",
                authorization_ref="oauth-grant-ref://tiktok/r23",
                caption="test",
                cta="Learn more",
                allow_synthetic_editor=True,
            )

    def test_target_account_mismatch_fails_closed(self):
        _, _, _, handoff = build_fixture(self.root)
        broken = json.loads(reels.canonical_json(handoff))
        broken["target"]["accountId"] = "different-account"
        broken = rehash_handoff(broken)
        with self.assertRaises(r23.EditorPublishHandoffError):
            r23.validate_editor_publish_handoff(
                broken,
                allow_synthetic_editor=True,
            )

    def test_publish_intent_precedes_provider_effect_and_lost_ack_recovers(self):
        _, _, _, handoff = build_fixture(self.root)
        ledger_path = self.root / "handoff-ledger.jsonl"
        publish_path = self.root / "publish-ledger.jsonl"
        ledger = r23.HandoffLedger(
            ledger_path,
            handoff,
            allow_synthetic_editor=True,
        )
        provider = r12.TikTokMockProvider(
            crash_after_effect_once=True,
            polls_before_publish=1,
        )
        coordinator = r23.EditorPublishCoordinator(
            handoff_ledger=ledger,
            publish_ledger_path=publish_path,
            allow_synthetic=True,
        )
        with self.assertRaises(reels.InjectedCrash):
            coordinator.drive(
                provider,
                now="2026-10-01T00:00:00Z",
            )
        self.assertTrue(ledger.has_publish_intent())
        intent_seq = ledger.by_key["publish:intent"]["sequence"]
        self.assertGreater(provider.accepted_effects, 0)
        self.assertLess(
            intent_seq,
            ledger.events[-1]["sequence"] + 1,
        )

        restarted_ledger = r23.HandoffLedger(
            ledger_path,
            handoff,
            allow_synthetic_editor=True,
        )
        restarted = r23.EditorPublishCoordinator(
            handoff_ledger=restarted_ledger,
            publish_ledger_path=publish_path,
            allow_synthetic=True,
        )
        outcome = restarted.drive(
            provider,
            now="2026-10-01T00:00:01Z",
        )
        if outcome["state"] != "published":
            outcome = restarted.drive(
                provider,
                now="2026-10-01T00:00:02Z",
            )
        self.assertEqual(outcome["state"], "published")
        self.assertEqual(provider.accepted_effects, 1)
        self.assertEqual(provider.submit_calls, 1)
        self.assertFalse(
            outcome["growthHandoff"]["livePerformanceClaimEligible"]
        )

    def test_duplicate_handoff_is_idempotent_and_conflict_rejected(self):
        _, _, _, handoff = build_fixture(self.root)
        path = self.root / "dup-ledger.jsonl"
        first = r23.HandoffLedger(
            path,
            handoff,
            allow_synthetic_editor=True,
        )
        self.assertEqual(
            first.append_once(
                "publish:intent",
                "publish_intent_committed",
                {"same": True},
            ),
            "committed",
        )
        self.assertEqual(
            first.append_once(
                "publish:intent",
                "publish_intent_committed",
                {"same": True},
            ),
            "duplicate",
        )
        with self.assertRaises(r23.HandoffConflict):
            first.append_once(
                "publish:intent",
                "publish_intent_committed",
                {"same": False},
            )
        second = r23.HandoffLedger(
            path,
            handoff,
            allow_synthetic_editor=True,
        )
        self.assertTrue(second.has_publish_intent())

    def test_provider_timeout_and_auth_required_remain_non_mutating_or_recoverable(self):
        _, _, _, handoff = build_fixture(self.root)
        timeout_provider = r12.TikTokMockProvider(
            recovery_unknown_once=True,
        )
        timeout_ledger = r23.HandoffLedger(
            self.root / "timeout-handoff.jsonl",
            handoff,
            allow_synthetic_editor=True,
        )
        timeout_coordinator = r23.EditorPublishCoordinator(
            handoff_ledger=timeout_ledger,
            publish_ledger_path=self.root / "timeout-publish.jsonl",
            allow_synthetic=True,
        )
        outcome = timeout_coordinator.drive(
            timeout_provider,
            now="2026-10-01T00:00:00Z",
        )
        self.assertEqual(outcome["state"], "recoverable_unknown")
        self.assertEqual(timeout_provider.accepted_effects, 0)

        auth_provider = r12.TikTokMockProvider(
            credentials_available=False,
        )
        auth_ledger = r23.HandoffLedger(
            self.root / "auth-handoff.jsonl",
            handoff,
            allow_synthetic_editor=True,
        )
        auth_coordinator = r23.EditorPublishCoordinator(
            handoff_ledger=auth_ledger,
            publish_ledger_path=self.root / "auth-publish.jsonl",
            allow_synthetic=True,
        )
        auth = auth_coordinator.drive(
            auth_provider,
            now="2026-10-01T00:00:00Z",
        )
        self.assertEqual(auth["state"], "waiting_for_credentials")
        self.assertEqual(auth_provider.accepted_effects, 0)

    def test_provider_account_block_fails_before_submit(self):
        _, _, _, handoff = build_fixture(self.root)
        provider = r12.TikTokMockProvider(
            blocked_accounts=("account-r23",),
        )
        ledger = r23.HandoffLedger(
            self.root / "account-handoff.jsonl",
            handoff,
            allow_synthetic_editor=True,
        )
        coordinator = r23.EditorPublishCoordinator(
            handoff_ledger=ledger,
            publish_ledger_path=self.root / "account-publish.jsonl",
            allow_synthetic=True,
        )
        outcome = coordinator.drive(
            provider,
            now="2026-10-01T00:00:00Z",
        )
        self.assertEqual(outcome["state"], "failed_terminal")
        self.assertEqual(provider.submit_calls, 0)
        self.assertEqual(provider.accepted_effects, 0)


class R23SyntheticE2ETests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "ffmpeg/ffprobe required",
    )
    def test_one_command_real_mp4_editor_bundle_to_growth_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "final.mp4"
            result = subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner", "-nostdin", "-y",
                    "-f", "lavfi",
                    "-i", "color=c=purple:s=360x640:r=30:d=15.2",
                    "-threads", "1",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    str(media),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            asset = r21.probe_media(media)
            bundle = r23.synthetic_editor_bundle_for_asset(asset)
            auth = r23.synthetic_release_authorization(
                bundle=bundle,
                platform="tiktok",
                destination="privacy:SELF_ONLY",
            )
            bundle_path = root / "editor-bundle.json"
            auth_path = root / "release.authorization.v1.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            auth_path.write_text(json.dumps(auth), encoding="utf-8")
            out = root / "out"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = r23.main(
                    [
                        "--media", str(media),
                        "--editor-bundle", str(bundle_path),
                        "--authorization", str(auth_path),
                        "--platform", "tiktok",
                        "--account-id", "account-r23",
                        "--destination", "privacy:SELF_ONLY",
                        "--credential-ref", "vault-ref://tiktok/r23",
                        "--authorization-ref",
                        "oauth-grant-ref://tiktok/r23",
                        "--caption", "R23 one-command synthetic",
                        "--cta", "Learn more",
                        "--out", str(out),
                    ]
                )
            self.assertEqual(code, 0, stdout.getvalue())
            report = json.loads(
                (out / "handoff-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["state"], "published")
            self.assertEqual(report["providerAcceptedEffects"], 1)
            self.assertEqual(report["providerSubmitCalls"], 1)
            self.assertFalse(report["growthLivePerformanceClaimEligible"])
            self.assertFalse(report["livePublishingExecuted"])
            self.assertFalse(report["credentialsPersisted"])
            self.assertEqual(report["finalRenderSha256"], asset.sha256)
            self.assertTrue((out / "editor-publish-handoff.json").is_file())
            self.assertTrue((out / "provider-receipt.json").is_file())
            self.assertTrue((out / "growth-handoff.json").is_file())
            durable = "\n".join(
                p.read_text(encoding="utf-8")
                for p in out.iterdir()
                if p.suffix in {".json", ".jsonl"}
            ).lower()
            self.assertNotIn("bearer ", durable)
            self.assertNotIn("access_token", durable)
            self.assertNotIn("refresh_token", durable)


if __name__ == "__main__":
    unittest.main()
