from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from creator_orchestrator import autonomous_reels as reels
from creator_orchestrator import publish_execution as r21
from creator_orchestrator import publish_providers as r12


NOW = "2026-10-01T00:00:00Z"
EXPIRES = "2026-10-02T00:00:00Z"


@dataclass
class StaticMediaResolver:
    asset: r21.MediaAsset

    def resolve(self, request):
        if self.asset.sha256 != request["media"]["contentSha256"]:
            raise r21.ProviderRejected("test media SHA mismatch")
        if self.asset.size_bytes != request["media"]["sizeBytes"]:
            raise r21.ProviderRejected("test media size mismatch")
        return self.asset


def credential(platform: str, account_id: str, **overrides):
    value = {
        "access_token": "secret-token-never-persist",
        "subject_id": account_id,
        "scopes": tuple(r21.REQUIRED_SCOPES[platform]),
        "expires_at": EXPIRES,
        "revoked": False,
        "interactive_required": False,
    }
    value.update(overrides)
    return r21.CredentialMaterial(**value)


def release_authorization(platform, destination, sha):
    return {
        "contractVersion": reels.RELEASE_AUTHORIZATION_VERSION,
        "decisionId": "r21-decision",
        "idempotencyKey": "r21-release-key",
        "requestId": "r21-release-request",
        "campaignId": "r21-campaign",
        "candidateId": "r21-candidate",
        "artifactId": "sha256:" + sha,
        "artifactHash": "sha256:" + sha,
        "lineageHash": "sha256:" + ("b" * 64),
        "destinationScope": {
            "provider": platform,
            "destination": destination,
            "action": "release",
        },
        "decision": "approved",
        "authorizationId": "r21-authorization",
        "expiresAt": EXPIRES,
        "decidedAt": NOW,
        "decisionSource": "external",
        "approverRef": "human-operator-r21",
    }


def publish_request(
    platform,
    account_id,
    destination,
    asset,
    *,
    source_class="provider",
):
    ref = f"vault-ref://{platform}/operator-account"
    return r12.build_publish_request(
        platform=platform,
        account_id=account_id,
        destination=destination,
        credential_ref=ref,
        authorization_lineage={
            "credentialRef": ref,
            "authorizationRef": f"oauth-grant-ref://{platform}/operator",
        },
        media={
            "sourceClass": source_class,
            "contentId": "sha256:" + asset.sha256,
            "contentSha256": asset.sha256,
            "sizeBytes": asset.size_bytes,
            "contentType": "video/mp4",
            "durationSeconds": asset.duration_seconds,
            "aspectRatio": "9:16",
            "manifestDigest": "c" * 64,
        },
        caption="Production publish transport test",
        cta="Learn more",
        release_authorization=release_authorization(
            platform, destination, asset.sha256
        ),
        allow_synthetic_fixture=(source_class == "synthetic_fixture"),
    )


class R21ProductionAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        path = root / "final.mp4"
        path.write_bytes(b"r21-production-media-bytes")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.asset = r21.MediaAsset(
            path=path,
            sha256=sha,
            size_bytes=path.stat().st_size,
            duration_seconds=30.0,
            width=1080,
            height=1920,
            fps=30.0,
            video_codec="h264",
            audio_codec="aac",
            public_url="https://media.example.test/final.mp4",
        )
        self.root = root
        self.sleeps = []

    def provider(
        self,
        platform,
        account_id,
        responses,
        *,
        credential_value=None,
        retry_attempts=1,
    ):
        ref = f"vault-ref://{platform}/operator-account"
        resolver = r21.StaticCredentialResolver(
            {
                ref: credential_value
                or credential(platform, account_id)
            }
        )
        config = r21.RuntimeConfig(
            timeout_seconds=1,
            retry_attempts=retry_attempts,
            initial_backoff_seconds=1,
            max_backoff_seconds=4,
            instagram_graph_version="v24.0",
        )
        transport = r21.FakeHttpTransport(responses)
        provider = r21.production_provider(
            platform,
            credential_resolver=resolver,
            media_resolver=StaticMediaResolver(self.asset),
            transport=transport,
            journal_path=self.root / f"{platform}-ops.jsonl",
            config=config,
            sleep_fn=self.sleeps.append,
            now_fn=lambda: NOW,
        )
        return provider, transport

    def drive_to_terminal(self, request, provider, ledger):
        coordinator = r12.DurablePublishCoordinator(
            ledger, request
        )
        outcome = coordinator.drive(provider, now=NOW)
        self.assertEqual(
            outcome["state"],
            "waiting_for_provider_processing",
        )
        outcome = coordinator.drive(provider, now=NOW)
        self.assertEqual(outcome["state"], "published")
        return outcome

    def test_instagram_direct_graph_transport_to_receipt(self):
        account = "ig-user-1"
        destination = "profile:" + account
        request = publish_request(
            "instagram_reels", account, destination, self.asset
        )
        responses = [
            r21.HttpResponse(200, {}, {"id": account, "username": "creator"}),
            r21.HttpResponse(200, {}, {"id": "container-1"}),
            r21.HttpResponse(200, {}, {"id": account, "username": "creator"}),
            r21.HttpResponse(
                200,
                {},
                {"id": "container-1", "status_code": "FINISHED"},
            ),
            r21.HttpResponse(200, {}, {"id": "ig-media-1"}),
            r21.HttpResponse(
                200,
                {},
                {"permalink": "https://www.instagram.com/reel/example/"},
            ),
        ]
        provider, transport = self.provider(
            "instagram_reels", account, responses
        )
        outcome = self.drive_to_terminal(
            request, provider, self.root / "ig-ledger.jsonl"
        )
        receipt = outcome["receipt"]
        self.assertEqual(receipt["postId"], "ig-media-1")
        self.assertEqual(
            receipt["mediaContentSha256"],
            self.asset.sha256,
        )
        terminal = provider.journal.latest(
            request["idempotencyKey"], "terminal_status"
        )
        self.assertEqual(
            terminal["postUrl"],
            "https://www.instagram.com/reel/example/",
        )
        serialized = (
            json.dumps(transport.calls)
            + provider.journal.path.read_text(encoding="utf-8")
        )
        self.assertNotIn("secret-token-never-persist", serialized)
        self.assertNotIn("Authorization", provider.journal.path.read_text())

    def test_tiktok_direct_post_transport_to_receipt(self):
        account = "tt-open-id-1"
        destination = "privacy:SELF_ONLY"
        request = publish_request(
            "tiktok", account, destination, self.asset
        )
        creator = {
            "data": {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 300,
            },
            "error": {"code": "ok"},
        }
        responses = [
            r21.HttpResponse(200, {}, creator),
            r21.HttpResponse(
                200,
                {},
                {"data": {"publish_id": "tt-publish-1"}, "error": {"code": "ok"}},
            ),
            r21.HttpResponse(200, {}, creator),
            r21.HttpResponse(
                200,
                {},
                {
                    "data": {
                        "status": "PUBLISH_COMPLETE",
                        "publicaly_available_post_id": ["tt-post-1"],
                    },
                    "error": {"code": "ok"},
                },
            ),
        ]
        provider, transport = self.provider(
            "tiktok", account, responses
        )
        outcome = self.drive_to_terminal(
            request, provider, self.root / "tt-ledger.jsonl"
        )
        self.assertEqual(outcome["receipt"]["postId"], "tt-post-1")
        init_calls = [
            call for call in transport.calls
            if call["url"].endswith("/v2/post/publish/video/init/")
        ]
        self.assertEqual(len(init_calls), 1)
        self.assertTrue(init_calls[0]["authorizationPresent"])

    def test_youtube_resumable_transport_to_receipt_and_url(self):
        account = "yt-channel-1"
        destination = "privacy:private"
        request = publish_request(
            "youtube_shorts", account, destination, self.asset
        )
        responses = [
            r21.HttpResponse(200, {}, {"items": [{"id": account}]}),
            r21.HttpResponse(
                200,
                {
                    "Location": (
                        "https://upload.youtube.test/session?"
                        "upload_id=provider-operation-1"
                    )
                },
                {},
            ),
            r21.HttpResponse(200, {}, {"id": "yt-video-1"}),
            r21.HttpResponse(200, {}, {"items": [{"id": account}]}),
            r21.HttpResponse(
                200,
                {},
                {
                    "items": [
                        {
                            "id": "yt-video-1",
                            "processingDetails": {
                                "processingStatus": "succeeded"
                            },
                        }
                    ]
                },
            ),
        ]
        provider, _ = self.provider(
            "youtube_shorts", account, responses
        )
        outcome = self.drive_to_terminal(
            request, provider, self.root / "yt-ledger.jsonl"
        )
        self.assertEqual(outcome["receipt"]["postId"], "yt-video-1")
        terminal = provider.journal.latest(
            request["idempotencyKey"], "terminal_status"
        )
        self.assertEqual(
            terminal["postUrl"],
            "https://www.youtube.com/watch?v=yt-video-1",
        )

    def test_lost_ack_after_provider_accept_is_never_blindly_replayed(self):
        account = "tt-open-id-lost-ack"
        request = publish_request(
            "tiktok", account, "privacy:SELF_ONLY", self.asset
        )
        creator = {
            "data": {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 300,
            },
            "error": {"code": "ok"},
        }
        provider, transport = self.provider(
            "tiktok",
            account,
            [
                r21.HttpResponse(200, {}, creator),
                r21.ProviderTimeout("accepted but acknowledgement lost"),
                r21.HttpResponse(200, {}, creator),
            ],
        )
        ledger = self.root / "lost-ack-ledger.jsonl"
        first = r12.DurablePublishCoordinator(ledger, request).drive(
            provider, now=NOW
        )
        self.assertEqual(first["state"], "recoverable_unknown")
        restarted = r12.DurablePublishCoordinator(ledger, request)
        restarted_provider = r21.production_provider(
            "tiktok",
            credential_resolver=provider.credential_resolver,
            media_resolver=provider.media_resolver,
            transport=transport,
            journal_path=provider.journal.path,
            config=provider.config,
            sleep_fn=self.sleeps.append,
            now_fn=lambda: NOW,
        )
        second = restarted.drive(restarted_provider, now=NOW)
        self.assertEqual(second["state"], "recoverable_unknown")
        init_calls = [
            call for call in transport.calls
            if call["url"].endswith("/v2/post/publish/video/init/")
        ]
        self.assertEqual(len(init_calls), 1)
        self.assertTrue(
            restarted_provider.journal.unresolved_intent(
                request["idempotencyKey"]
            )
        )

    def test_processing_timeout_becomes_recoverable_unknown(self):
        account = "tt-open-id-timeout"
        request = publish_request(
            "tiktok", account, "privacy:SELF_ONLY", self.asset
        )
        creator = {
            "data": {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 300,
            },
            "error": {"code": "ok"},
        }
        provider, _ = self.provider(
            "tiktok",
            account,
            [
                r21.HttpResponse(200, {}, creator),
                r21.HttpResponse(
                    200, {}, {"data": {"publish_id": "tt-timeout"}}
                ),
                r21.HttpResponse(200, {}, creator),
                r21.ProviderTimeout("status timeout"),
            ],
        )
        coordinator = r12.DurablePublishCoordinator(
            self.root / "timeout-ledger.jsonl", request
        )
        self.assertEqual(
            coordinator.drive(provider, now=NOW)["state"],
            "waiting_for_provider_processing",
        )
        self.assertEqual(
            coordinator.drive(provider, now=NOW)["state"],
            "recoverable_unknown",
        )

    def test_429_uses_bounded_retry_after_backoff(self):
        account = "tt-open-id-rate"
        request = publish_request(
            "tiktok", account, "privacy:SELF_ONLY", self.asset
        )
        creator = {
            "data": {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 300,
            },
            "error": {"code": "ok"},
        }
        provider, _ = self.provider(
            "tiktok",
            account,
            [
                r21.HttpResponse(429, {"Retry-After": "2"}, {}),
                r21.HttpResponse(200, {}, creator),
            ],
            retry_attempts=2,
        )
        prepared = provider.prepare(request)
        self.assertTrue(prepared["capability"]["supported"])
        self.assertEqual(self.sleeps, [2.0])

    def test_expired_revoked_and_interactive_auth_stop_before_network(self):
        account = "yt-auth-state"
        request = publish_request(
            "youtube_shorts",
            account,
            "privacy:private",
            self.asset,
        )
        cases = [
            (
                credential(
                    "youtube_shorts",
                    account,
                    expires_at="2026-09-30T00:00:00Z",
                ),
                "credential_expired",
            ),
            (
                credential("youtube_shorts", account, revoked=True),
                "credential_revoked",
            ),
            (
                credential(
                    "youtube_shorts",
                    account,
                    interactive_required=True,
                ),
                "interactive_authorization_required",
            ),
        ]
        for index, (material, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                provider, transport = self.provider(
                    "youtube_shorts",
                    account,
                    [],
                    credential_value=material,
                )
                coordinator = r12.DurablePublishCoordinator(
                    self.root / f"auth-{index}.jsonl", request
                )
                result = coordinator.drive(provider, now=NOW)
                self.assertEqual(
                    result["state"], "waiting_for_credentials"
                )
                self.assertEqual(coordinator.operator_reason, reason)
                self.assertEqual(transport.calls, [])

    def test_restart_every_phase_duplicate_request_and_out_of_order_status(self):
        account = "tt-restart"
        request = publish_request(
            "tiktok", account, "privacy:SELF_ONLY", self.asset
        )
        creator = {
            "data": {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 300,
            },
            "error": {"code": "ok"},
        }
        transport = r21.FakeHttpTransport(
            [
                r21.HttpResponse(200, {}, creator),
                r21.HttpResponse(
                    200, {}, {"data": {"publish_id": "tt-restart-pub"}}
                ),
                r21.HttpResponse(200, {}, creator),
                r21.HttpResponse(
                    200, {}, {"data": {"status": "PROCESSING_DOWNLOAD"}}
                ),
                r21.HttpResponse(200, {}, creator),
                r21.HttpResponse(
                    200,
                    {},
                    {
                        "data": {
                            "status": "PUBLISH_COMPLETE",
                            "publicaly_available_post_id": ["tt-final-post"],
                        }
                    },
                ),
                r21.HttpResponse(
                    200, {}, {"data": {"status": "PROCESSING_DOWNLOAD"}}
                ),
            ]
        )
        resolver = r21.StaticCredentialResolver(
            {
                request["credentialRef"]: credential(
                    "tiktok", account
                )
            }
        )
        provider_journal = self.root / "restart-provider.jsonl"
        ledger = self.root / "restart-ledger.jsonl"

        def new_provider():
            return r21.production_provider(
                "tiktok",
                credential_resolver=resolver,
                media_resolver=StaticMediaResolver(self.asset),
                transport=transport,
                journal_path=provider_journal,
                config=r21.RuntimeConfig(
                    timeout_seconds=1,
                    retry_attempts=1,
                ),
                sleep_fn=self.sleeps.append,
                now_fn=lambda: NOW,
            )

        first = r12.DurablePublishCoordinator(
            ledger, request
        ).drive(new_provider(), now=NOW)
        self.assertEqual(first["state"], "waiting_for_provider_processing")
        second = r12.DurablePublishCoordinator(
            ledger, request
        ).drive(new_provider(), now=NOW)
        self.assertEqual(second["state"], "waiting_for_provider_processing")
        third_coord = r12.DurablePublishCoordinator(ledger, request)
        third_provider = new_provider()
        third = third_coord.drive(third_provider, now=NOW)
        self.assertEqual(third["state"], "published")
        duplicate = r12.DurablePublishCoordinator(
            ledger, request
        ).drive(new_provider(), now=NOW)
        self.assertEqual(duplicate["state"], "published")
        init_calls = [
            call for call in transport.calls
            if call["url"].endswith("/v2/post/publish/video/init/")
        ]
        self.assertEqual(len(init_calls), 1)
        operation_ref = third_coord.provider_status["operationRef"]
        before = len(transport.responses)
        cached = third_provider.status(operation_ref)
        self.assertEqual(cached["state"], "published")
        self.assertEqual(len(transport.responses), before)

    def test_malformed_provider_receipt_fails_closed(self):
        request = publish_request(
            "tiktok",
            "sandbox-account",
            "privacy:SELF_ONLY",
            self.asset,
            source_class="synthetic_fixture",
        )
        provider = r12.TikTokMockProvider()
        coordinator = r12.DurablePublishCoordinator(
            self.root / "receipt-ledger.jsonl",
            request,
            allow_synthetic_fixture=True,
        )
        coordinator.drive(provider, now=NOW)
        receipt = coordinator.drive(provider, now=NOW)["receipt"]
        malformed = dict(receipt)
        malformed["mediaContentSha256"] = "f" * 64
        with self.assertRaises(reels.PublishGateError):
            r12.validate_provider_receipt(
                malformed,
                request,
                allow_synthetic_fixture=True,
            )


class R21SandboxPipelineTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "ffmpeg/ffprobe required",
    )
    def test_one_command_sandbox_from_real_mp4_release_auth_to_growth(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "final.mp4"
            result = subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner", "-nostdin", "-y",
                    "-f", "lavfi",
                    "-i", "color=c=blue:s=360x640:r=30:d=15.2",
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
            platform = "tiktok"
            destination = "privacy:SELF_ONLY"
            auth = release_authorization(
                platform, destination, asset.sha256
            )
            auth_path = root / "release.authorization.v1.json"
            auth_path.write_text(
                json.dumps(auth),
                encoding="utf-8",
            )
            out = root / "sandbox"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = r21.main(
                    [
                        "--media", str(media),
                        "--authorization", str(auth_path),
                        "--platform", platform,
                        "--account-id", "sandbox-account",
                        "--destination", destination,
                        "--credential-ref", "vault-ref://sandbox/tiktok",
                        "--caption", "Sandbox only",
                        "--cta", "Learn more",
                        "--out", str(out),
                    ]
                )
            self.assertEqual(code, 0, stdout.getvalue())
            report = json.loads(
                (out / "sandbox-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["state"], "published")
            self.assertFalse(report["networkUsed"])
            self.assertFalse(report["liveSideEffect"])
            self.assertEqual(report["providerAcceptedEffects"], 1)
            self.assertEqual(report["providerSubmitCalls"], 1)
            self.assertFalse(
                report["growthHandoff"]["livePerformanceClaimEligible"]
            )
            self.assertEqual(
                report["growthHandoff"]["sourceClass"],
                "synthetic_fixture",
            )
            text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in out.iterdir()
                if path.is_file() and path.suffix in {".json", ".jsonl"}
            )
            self.assertNotIn("access_token", text.lower())
            self.assertNotIn("authorization:", text.lower())


if __name__ == "__main__":
    unittest.main()
