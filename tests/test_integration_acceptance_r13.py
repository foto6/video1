from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import integration_acceptance as r13
from creator_orchestrator.autonomous_reels import InjectedCrash, sha256_json
from creator_orchestrator.publish_providers import (
    DurablePublishCoordinator,
    YouTubeShortsMockProvider,
    build_publish_request,
)


def ready_media_pin() -> r13.MediaAcceptancePin:
    observed = r13.MEDIA_OBSERVED_CANDIDATE
    return r13.MediaAcceptancePin(
        producer_sha=observed["producerSha"],
        job_contract_blob_sha=observed["jobContractBlobSha"],
        artifact_manifest_contract_blob_sha=observed["artifactManifestContractBlobSha"],
        conformance_manifest_blob_sha=observed["conformanceManifestBlobSha"],
        creator_consumer_blob_sha=observed["creatorConsumerBlobSha"],
        ci_run_id="synthetic-test-only-ci-evidence",
        ci_conclusion="success",
    )


class IntegrationAcceptanceR13Tests(unittest.TestCase):
    def test_current_readiness_is_explicitly_blocked_on_media(self) -> None:
        report = r13.readiness_report(None)
        self.assertEqual(report["overall"], "BLOCKED_MEDIA")
        self.assertEqual(report["gates"]["mediaR11"]["state"], "BLOCKED_MEDIA")
        self.assertIsNone(report["gates"]["mediaR11"]["acceptedPin"])
        self.assertEqual(
            report["gates"]["mediaR11"]["observedCandidate"]["producerSha"],
            "530e0ea43288840d2d66609ca2407640522df3f7",
        )
        self.assertIsNone(
            report["gates"]["mediaR11"]["observedCandidate"]["exactHeadCiRunId"]
        )

    def test_growth_r11_exact_source_hashes_are_pinned(self) -> None:
        source = r13.growth_r11_source_pin()
        self.assertEqual(
            source["producerSha"],
            "c4ed94d3e76b75d36bf8cc8280f6937f455133a6",
        )
        self.assertEqual(
            source["manifestBlobSha"],
            "8b47817cb344c4a1670d338fca351c1056e8ba6f",
        )
        self.assertEqual(
            source["implementationBlobSha"],
            "3fde5ed6fbae9356cc232613a8a81ea442c74315",
        )
        self.assertEqual(
            source["r10ContractBlobSha"],
            "0a63ebece0fe8620a57e635143cc3ea16d095f59",
        )
        self.assertTrue(source["readOnly"])
        self.assertEqual(
            r13.GROWTH_R11_FIXTURE_BLOBS,
            {
                "instagram_reels": "9c411453e66a59d0388a142a4b874348f4d0f1d8",
                "tiktok": "3e5fe2212ab8b120209bd73abf509bf9eab188b8",
                "youtube_shorts": "95bb85583cbed8e7d04d54d71c13d7b75fa53ef9",
            },
        )

    def test_full_synthetic_acceptance_is_green_for_all_three_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = r13.run_all_platforms(
                work_dir=temp,
                media_pin=ready_media_pin(),
            )
        self.assertEqual(report["overall"], "SYNTHETIC_ACCEPTANCE_GREEN")
        self.assertFalse(report["productionReadinessClaim"])
        self.assertEqual(
            [item["platform"] for item in report["platforms"]],
            ["instagram_reels", "tiktok", "youtube_shorts"],
        )
        for item in report["platforms"]:
            self.assertEqual(item["boundaryEventCount"], len(r13.CROSS_REPO_BOUNDARIES))
            self.assertEqual(item["nextCycleConsumeStatus"], "accepted")
            self.assertFalse(item["livePerformanceClaimEligible"])
            self.assertFalse(item["productionReadinessClaim"])
            self.assertEqual(item["effects"]["mediaLogicalEffects"], 1)
            self.assertEqual(item["effects"]["publishLogicalEffects"], 1)
            self.assertEqual(item["effects"]["growthLogicalEffects"], 1)

    def test_every_cross_repo_boundary_is_durable_across_commit_crash_and_replay(self) -> None:
        for boundary in r13.CROSS_REPO_BOUNDARIES:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "boundaries.jsonl"
                ledger = r13.IntegrationAcceptanceLedger(path, run_id="boundary-replay")
                payload = {"boundaryFixture": boundary, "digest": sha256_json({"b": boundary})}
                with self.assertRaises(r13.BoundaryCrash):
                    ledger.commit_boundary(boundary, payload, crash_after_commit=True)
                restarted = r13.IntegrationAcceptanceLedger(path, run_id="boundary-replay")
                self.assertEqual(restarted.commit_boundary(boundary, payload), "duplicate")
                self.assertEqual(len(restarted.boundaries), 1)
                with self.assertRaises(r13.BoundaryConflict):
                    restarted.commit_boundary(
                        boundary,
                        {"boundaryFixture": boundary, "digest": "f" * 64},
                    )

    def test_media_unknown_ack_replay_has_one_logical_effect(self) -> None:
        pin = ready_media_pin()
        provider = r13.MockMediaAcceptanceProvider(
            pin,
            fail_after_effect_once=True,
        )
        profile = r13._profile("instagram_reels")
        inputs = r13._stage_inputs(profile)
        request = r13.build_media_request(
            cycle_id="r13-media-crash",
            profile=profile,
            script=inputs["script"],
            asset_plan=inputs["asset_plan"],
            edit_request=inputs["edit_request"],
        )
        with self.assertRaises(r13.BoundaryCrash):
            provider.submit(request, profile)
        recovered = provider.submit(request, profile)
        self.assertEqual(recovered["sourceClass"], "synthetic_fixture")
        self.assertEqual(provider.accepted_effects, 1)
        self.assertEqual(provider.submit_calls, 2)

    def test_publish_unknown_ack_recovery_is_exercised_through_r12(self) -> None:
        pin = ready_media_pin()
        platform = "youtube_shorts"
        profile = r13._profile(platform)
        inputs = r13._stage_inputs(profile)
        media_provider = r13.MockMediaAcceptanceProvider(pin)
        media_request = r13.build_media_request(
            cycle_id="r13-publish-crash",
            profile=profile,
            script=inputs["script"],
            asset_plan=inputs["asset_plan"],
            edit_request=inputs["edit_request"],
        )
        media = media_provider.submit(media_request, profile)
        manifest = media["artifactManifest"]
        destination = "fixture-youtube_shorts-destination"
        auth = r13._release_authorization(
            cycle_id="r13-publish-crash",
            platform=platform,
            destination=destination,
            artifact_id=manifest["content"]["contentId"],
            artifact_digest=manifest["content"]["sha256"],
        )
        request = build_publish_request(
            platform=platform,
            account_id="fixture-youtube-account",
            destination=destination,
            credential_ref="vault-ref://youtube/r13-fixture",
            authorization_lineage={
                "credentialRef": "vault-ref://youtube/r13-fixture",
                "authorizationRef": "oauth-grant-ref://youtube/r13-fixture",
            },
            media={
                "sourceClass": "synthetic_fixture",
                "contentId": manifest["content"]["contentId"],
                "contentSha256": manifest["content"]["sha256"],
                "sizeBytes": manifest["content"]["size"],
                "contentType": "video/mp4",
                "durationSeconds": 30.0,
                "aspectRatio": "9:16",
                "manifestDigest": sha256_json(manifest),
            },
            caption=profile["metadata"]["caption"],
            cta=profile["metadata"]["cta"],
            release_authorization=auth,
            allow_synthetic_fixture=True,
        )
        provider = YouTubeShortsMockProvider(crash_after_effect_once=True)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "publish.jsonl"
            coordinator = DurablePublishCoordinator(
                path,
                request,
                allow_synthetic_fixture=True,
            )
            with self.assertRaises(InjectedCrash):
                coordinator.drive(provider, now="2026-10-01T00:00:00Z")
            restarted = DurablePublishCoordinator(
                path,
                request,
                allow_synthetic_fixture=True,
            )
            first = restarted.drive(provider, now="2026-10-01T00:00:01Z")
            self.assertEqual(first["state"], "waiting_for_provider_processing")
            second = restarted.drive(provider, now="2026-10-01T00:00:02Z")
            self.assertEqual(second["state"], "published")
        self.assertEqual(provider.accepted_effects, 1)
        self.assertEqual(provider.submit_calls, 1)

    def test_growth_unknown_ack_replay_has_one_logical_effect(self) -> None:
        pin = ready_media_pin()
        platform = "instagram_reels"
        profile = r13._profile(platform)
        inputs = r13._stage_inputs(profile)
        media_provider = r13.MockMediaAcceptanceProvider(pin)
        request = r13.build_media_request(
            cycle_id="r13-growth-crash",
            profile=profile,
            script=inputs["script"],
            asset_plan=inputs["asset_plan"],
            edit_request=inputs["edit_request"],
        )
        media = media_provider.submit(request, profile)
        receipt = {
            "platform": platform,
            "accountId": "fixture-account",
            "postId": "fixture-post",
            "publishedAt": "2026-10-01T00:00:03Z",
            "capturedAt": "2026-10-01T00:00:04Z",
            "mediaContentId": media["artifactManifest"]["content"]["contentId"],
            "mediaContentSha256": media["artifactManifest"]["content"]["sha256"],
            "receiptDigest": "a" * 64,
        }
        handoff = {
            "contractVersion": "creator.publish_provider_growth_handoff.v1",
            "sourceClass": "synthetic_fixture",
            "livePerformanceClaimEligible": False,
            "providerReceiptDigest": receipt["receiptDigest"],
            "platform": platform,
            "accountId": receipt["accountId"],
            "postId": receipt["postId"],
            "publishedAt": receipt["publishedAt"],
            "mediaContentSha256": receipt["mediaContentSha256"],
        }
        handoff["handoffDigest"] = sha256_json(handoff)
        provider = r13.MockGrowthR11AcceptanceProvider(fail_after_effect_once=True)
        kwargs = dict(
            handoff=handoff,
            next_cycle_id="r13-growth-next",
            cycle_revision=1,
            script=inputs["script"],
            media_envelope=media,
            receipt=receipt,
        )
        with self.assertRaises(r13.BoundaryCrash):
            provider.ingest(**kwargs)
        recovered = provider.ingest(**kwargs)
        self.assertEqual(
            recovered["growthR11Evidence"]["metricsEvent"]["source_class"],
            "synthetic_fixture",
        )
        self.assertEqual(provider.accepted_effects, 1)
        self.assertEqual(provider.calls, 2)

    def test_growth_provenance_cannot_promote_synthetic_to_live(self) -> None:
        event = r13._growth_metrics_event(
            platform="tiktok",
            account_id="acct",
            post_id="post",
            cycle_revision=1,
            source_class="synthetic_fixture",
        )
        envelope = {
            "contractVersion": r13.GROWTH_R11_EVIDENCE_VERSION,
            "source": r13.growth_r11_source_pin(),
            "metricsEvent": event,
        }
        r13.validate_growth_r11_provider_evidence(
            envelope,
            expected_platform="tiktok",
            expected_account_id="acct",
            expected_post_id="post",
            expected_source_class="synthetic_fixture",
        )
        tampered = {
            **envelope,
            "metricsEvent": {
                **event,
                "source_class": "platform_export",
                "provenance": {
                    **event["provenance"],
                    "provider": "tiktok",
                    "fixture_source_sha256": None,
                    "live_performance_claim_allowed": True,
                },
            },
        }
        with self.assertRaises(r13.IntegrationAcceptanceError):
            r13.validate_growth_r11_provider_evidence(
                tampered,
                expected_platform="tiktok",
                expected_account_id="acct",
                expected_post_id="post",
                expected_source_class="synthetic_fixture",
            )

    def test_invalid_media_pin_stays_blocked(self) -> None:
        bad = r13.MediaAcceptancePin(
            producer_sha=r13.MEDIA_PREMILESTONE_SHA,
            job_contract_blob_sha="1" * 40,
            artifact_manifest_contract_blob_sha="2" * 40,
            conformance_manifest_blob_sha="3" * 40,
            creator_consumer_blob_sha="4" * 40,
            ci_run_id="123",
            ci_conclusion="success",
        )
        report = r13.readiness_report(bad)
        self.assertEqual(report["overall"], "BLOCKED_MEDIA")
        self.assertIn("pre-milestone", report["gates"]["mediaR11"]["reason"])

    def test_ready_media_pin_never_claims_production_readiness(self) -> None:
        report = r13.readiness_report(ready_media_pin())
        self.assertEqual(report["overall"], "SYNTHETIC_ACCEPTANCE_READY")
        self.assertEqual(
            report["gates"]["mediaR11"]["state"],
            "GREEN_FOR_SYNTHETIC_ACCEPTANCE",
        )


if __name__ == "__main__":
    unittest.main()
