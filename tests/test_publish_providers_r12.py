from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.autonomous_reels import (
    ContractValidationError,
    InjectedCrash,
    PublishGateError,
)
from creator_orchestrator.publish_providers import (
    DurablePublishCoordinator,
    InstagramReelsMockProvider,
    TikTokMockProvider,
    YouTubeShortsMockProvider,
    build_growth_handoff,
    build_publish_request,
    validate_provider_receipt,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "publish_provider_r12_conformance.json"
PROVIDERS = {
    "instagram_reels": InstagramReelsMockProvider,
    "tiktok": TikTokMockProvider,
    "youtube_shorts": YouTubeShortsMockProvider,
}


def release_authorization(case: dict) -> dict:
    media = case["media"]
    platform = case["platform"]
    return {
        "contractVersion": "release.authorization.v1",
        "decisionId": f"decision-{platform}",
        "idempotencyKey": f"release-key-{platform}",
        "requestId": f"release-request-{platform}",
        "campaignId": "campaign-r12-fixture",
        "candidateId": f"candidate-{platform}",
        "artifactId": media["contentId"],
        "artifactHash": f"sha256:{media['contentSha256']}",
        "lineageHash": "fixture-lineage-r12",
        "destinationScope": {
            "provider": platform,
            "destination": case["destination"],
            "action": "release",
        },
        "decision": "approved",
        "authorizationId": f"authorization-{platform}",
        "expiresAt": "2026-10-02T00:00:00Z",
        "decidedAt": "2026-09-30T23:00:00Z",
        "decisionSource": "external",
        "approverRef": "fixture-human-approval",
    }


def request_for(case: dict) -> dict:
    return build_publish_request(
        platform=case["platform"],
        account_id=case["accountId"],
        destination=case["destination"],
        credential_ref=case["credentialRef"],
        authorization_lineage=case["authorizationLineage"],
        media=case["media"],
        caption=case["caption"],
        cta=case["cta"],
        release_authorization=release_authorization(case),
        allow_synthetic_fixture=True,
    )


class PublishProviderR12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]

    def test_three_platform_conformance_async_to_terminal_receipt(self) -> None:
        for case in self.cases:
            with self.subTest(platform=case["platform"]), tempfile.TemporaryDirectory() as tmp:
                request = request_for(case)
                provider = PROVIDERS[case["platform"]](runtime_secret="never-persist-this")
                ledger = Path(tmp) / "publish.jsonl"
                coordinator = DurablePublishCoordinator(
                    ledger, request, allow_synthetic_fixture=True
                )
                first = coordinator.drive(provider, now="2026-10-01T00:00:00Z")
                self.assertEqual(first["state"], "waiting_for_provider_processing")
                second = coordinator.drive(provider, now="2026-10-01T00:00:01Z")
                self.assertEqual(second["state"], "published")
                receipt = second["receipt"]
                self.assertEqual(receipt["platform"], case["platform"])
                self.assertEqual(receipt["mediaContentSha256"], case["media"]["contentSha256"])
                self.assertEqual(receipt["caption"], case["caption"])
                self.assertEqual(receipt["cta"], case["cta"])
                self.assertEqual(receipt["authorizationId"], f"authorization-{case['platform']}")
                self.assertEqual(provider.accepted_effects, 1)
                self.assertEqual(provider.submit_calls, 1)
                text = ledger.read_text(encoding="utf-8")
                self.assertNotIn("never-persist-this", text)

    def test_waiting_for_credentials_has_no_provider_side_effect_or_recovery(self) -> None:
        case = self.cases[0]
        request = request_for(case)
        provider = InstagramReelsMockProvider(credentials_available=False)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DurablePublishCoordinator(
                Path(tmp) / "publish.jsonl", request, allow_synthetic_fixture=True
            )
            result = coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            self.assertEqual(result["state"], "waiting_for_credentials")
            self.assertEqual(provider.recover_calls, 0)
            self.assertEqual(provider.submit_calls, 0)
            self.assertEqual(provider.accepted_effects, 0)

    def test_capability_gate_rejects_account_before_side_effect(self) -> None:
        case = self.cases[1]
        request = request_for(case)
        provider = TikTokMockProvider(blocked_accounts={case["accountId"]})
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DurablePublishCoordinator(
                Path(tmp) / "publish.jsonl", request, allow_synthetic_fixture=True
            )
            result = coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            self.assertEqual(result["state"], "failed_terminal")
            self.assertEqual(provider.recover_calls, 0)
            self.assertEqual(provider.submit_calls, 0)
            self.assertEqual(provider.accepted_effects, 0)

    def test_crash_after_provider_effect_before_local_ack_recovers_without_resubmit(self) -> None:
        case = self.cases[2]
        request = request_for(case)
        provider = YouTubeShortsMockProvider(crash_after_effect_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "publish.jsonl"
            coordinator = DurablePublishCoordinator(
                ledger, request, allow_synthetic_fixture=True
            )
            with self.assertRaises(InjectedCrash):
                coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            self.assertEqual(provider.accepted_effects, 1)
            self.assertEqual(provider.submit_calls, 1)

            restarted = DurablePublishCoordinator(
                ledger, request, allow_synthetic_fixture=True
            )
            recovered = restarted.drive(provider, now="2026-10-01T00:00:01Z")
            self.assertEqual(recovered["state"], "waiting_for_provider_processing")
            terminal = restarted.drive(provider, now="2026-10-01T00:00:02Z")
            self.assertEqual(terminal["state"], "published")
            self.assertEqual(provider.accepted_effects, 1)
            self.assertEqual(provider.submit_calls, 1)
            self.assertGreaterEqual(provider.recover_calls, 2)

    def test_non_authoritative_recovery_never_blindly_submits(self) -> None:
        case = self.cases[0]
        request = request_for(case)
        provider = InstagramReelsMockProvider(recovery_unknown_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DurablePublishCoordinator(
                Path(tmp) / "publish.jsonl", request, allow_synthetic_fixture=True
            )
            first = coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            self.assertEqual(first["state"], "recoverable_unknown")
            self.assertEqual(provider.submit_calls, 0)
            second = coordinator.drive(provider, now="2026-10-01T00:00:01Z")
            self.assertEqual(second["state"], "waiting_for_provider_processing")
            self.assertEqual(provider.submit_calls, 1)

    def test_expired_authorization_fails_before_provider_prepare_or_submit(self) -> None:
        case = self.cases[0]
        request = request_for(case)
        provider = InstagramReelsMockProvider()
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DurablePublishCoordinator(
                Path(tmp) / "publish.jsonl", request, allow_synthetic_fixture=True
            )
            result = coordinator.drive(provider, now="2026-10-02T00:00:00Z")
            self.assertEqual(result["state"], "failed_terminal")
            self.assertEqual(provider.prepare_calls, 0)
            self.assertEqual(provider.submit_calls, 0)

    def test_receipt_tamper_breaks_media_caption_and_authorization_bindings(self) -> None:
        case = self.cases[0]
        request = request_for(case)
        provider = InstagramReelsMockProvider()
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DurablePublishCoordinator(
                Path(tmp) / "publish.jsonl", request, allow_synthetic_fixture=True
            )
            coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            receipt = coordinator.drive(provider, now="2026-10-01T00:00:01Z")["receipt"]
            for field, value in (
                ("mediaContentSha256", "f" * 64),
                ("caption", "tampered"),
                ("authorizationId", "other-authorization"),
            ):
                with self.subTest(field=field):
                    tampered = dict(receipt)
                    tampered[field] = value
                    with self.assertRaises(PublishGateError):
                        validate_provider_receipt(
                            tampered, request, allow_synthetic_fixture=True
                        )

    def test_synthetic_conformance_receipt_never_becomes_live_growth_claim(self) -> None:
        case = self.cases[1]
        request = request_for(case)
        provider = TikTokMockProvider()
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DurablePublishCoordinator(
                Path(tmp) / "publish.jsonl", request, allow_synthetic_fixture=True
            )
            coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            receipt = coordinator.drive(provider, now="2026-10-01T00:00:01Z")["receipt"]
            handoff = build_growth_handoff(
                receipt, request, allow_synthetic_fixture=True
            )
            self.assertFalse(handoff["livePerformanceClaimEligible"])
            self.assertEqual(handoff["sourceClass"], "synthetic_fixture")
            self.assertEqual(handoff["providerReceiptDigest"], receipt["receiptDigest"])

    def test_synthetic_media_is_fail_closed_outside_conformance(self) -> None:
        case = self.cases[0]
        with self.assertRaises(PublishGateError):
            build_publish_request(
                platform=case["platform"],
                account_id=case["accountId"],
                destination=case["destination"],
                credential_ref=case["credentialRef"],
                authorization_lineage=case["authorizationLineage"],
                media=case["media"],
                caption=case["caption"],
                cta=case["cta"],
                release_authorization=release_authorization(case),
            )

    def test_request_rejects_secret_like_fields(self) -> None:
        case = dict(self.cases[0])
        lineage = dict(case["authorizationLineage"])
        lineage["accessToken"] = "forbidden"
        with self.assertRaises(ContractValidationError):
            build_publish_request(
                platform=case["platform"],
                account_id=case["accountId"],
                destination=case["destination"],
                credential_ref=case["credentialRef"],
                authorization_lineage=lineage,
                media=case["media"],
                caption=case["caption"],
                cta=case["cta"],
                release_authorization=release_authorization(case),
                allow_synthetic_fixture=True,
            )


if __name__ == "__main__":
    unittest.main()
