from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import creator_orchestrator.autonomous_reels as m

MEDIA_HEAD = m.MEDIA_R11_PREMILESTONE_HEAD
MEDIA_JOB_BLOB = "96b252acae743f8fe059fd634ee320f92bd9c79c"
MEDIA_MANIFEST_BLOB = "42aed1ca4720cddd4a5e48af076bc73b663322b0"
GROWTH_HEAD = "26430780657713ab54cc6a6e53692240443b0c99"
GROWTH_BLOB = "f69f564c51f0ed42c5e9b0ebb9420173bd4f5bb7"


def provenance(name: str) -> dict:
    return {
        "producer": name,
        "sourceClass": "synthetic_fixture",
        "sourceRef": f"fixture://{name}",
        "sha256": hashlib.sha256(name.encode()).hexdigest(),
    }


def profile() -> dict:
    return m.canonical_reels_profile(
        caption="Three cuts, one idea.",
        cta="Save this workflow.",
        hashtags=("#editing", "#shorts"),
    )


def media_envelope(p: dict, *, source_class: str = "synthetic_fixture", producer_sha: str = MEDIA_HEAD) -> dict:
    probe = {
        "hasVideo": True,
        "hasAudio": True,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "durationMs": 30000,
        "videoCodec": "h264",
        "audioCodec": "aac",
        "blackFrameRatio": 0.0,
    }
    qa = {
        "passed": True,
        "checks": [
            {"name": "video-present", "pass": True, "actual": True, "expected": True},
            {"name": "vertical", "pass": True, "actual": "1080x1920", "expected": "1080x1920"},
            {"name": "duration", "pass": True, "actual": 30000, "expected": "15000..60000"},
        ],
        "expected": {"width": 1080, "height": 1920, "durationMs": 30000, "hasAudio": True},
    }
    content_digest = "4" * 64
    render_fp = "1" * 64
    manifest = {
        "contractVersion": m.MEDIA_ARTIFACT_MANIFEST_VERSION,
        "logicalJobId": "media-r11-cycle-2",
        "idempotencyKey": "creator:cycle-2:media",
        "renderFingerprint": render_fp,
        "attemptToken": "media-r11-cycle-2:render:1",
        "validatedRequestDigest": "2" * 64,
        "profileDigest": p["profileDigest"],
        "content": {
            "algorithm": "sha256",
            "sha256": content_digest,
            "size": 123456,
            "contentId": f"sha256:{content_digest}",
        },
        "probeEvidence": {"sha256": m.sha256_json(probe), "value": probe},
        "qaEvidence": {"sha256": m.sha256_json(qa), "passed": True, "value": qa},
        "finalization": {
            "method": "atomic_rename",
            "preparedSha256": content_digest,
            "preparedSize": 123456,
            "preparedAtMs": 1790812800000,
            "finalizedAtMs": 1790812801000,
        },
        "timestamps": {"jobCreatedAtMs": 1790812799000, "manifestCommittedAtMs": 1790812802000},
    }
    return {
        "contractVersion": m.MEDIA_R11_ENVELOPE_VERSION,
        "sourceClass": source_class,
        "source": {
            "repository": m.MEDIA_R11_REPOSITORY,
            "branch": m.MEDIA_R11_BRANCH,
            "producerSha": producer_sha,
            "jobContractPath": m.MEDIA_JOB_CONTRACT_PATH,
            "jobContractBlobSha": MEDIA_JOB_BLOB,
            "artifactManifestContractPath": m.MEDIA_ARTIFACT_CONTRACT_PATH,
            "artifactManifestContractBlobSha": MEDIA_MANIFEST_BLOB,
        },
        "job": {
            "contractVersion": m.MEDIA_JOB_VERSION,
            "jobId": manifest["logicalJobId"],
            "status": "succeeded",
            "idempotencyKey": manifest["idempotencyKey"],
            "renderFingerprint": render_fp,
        },
        "artifactManifest": manifest,
        "preview": {"sha256": "5" * 64, "contentType": "image/jpeg"},
        "timelineSpec": {
            "sha256": "6" * 64,
            "profileDigest": p["profileDigest"],
            "editRequestDigest": "7" * 64,
        },
    }


def growth_seed_envelope(*, next_cycle_id: str = "cycle-2", revision: int = 1) -> dict:
    seed = {
        "contract_version": m.GROWTH_NEXT_CYCLE_SEED_VERSION,
        "next_cycle_id": next_cycle_id,
        "cycle_revision": revision,
        "source_class": "synthetic_fixture",
        "live_performance_claim_allowed": False,
        "creator_cycle_eligible": False,
        "evidence_state": "directional_observational",
        "lineage": {
            "publish_result_digest": "8" * 64,
            "metric_snapshot_digest": "9" * 64,
            "decision": {"handoff_digest": "a" * 64},
        },
        "metrics": {"normalized": {"views": 5000}},
        "recommendations": [{"action": "preserve_shareable_hook", "certainty": "directional_not_causal"}],
        "authority": {
            "auto_publish": False,
            "external_mutation": False,
            "release_authorized": False,
            "publish_authorized": False,
            "requires_creator_release_authorization": True,
        },
        "interpretation": "Synthetic fixture; no live claim.",
    }
    identity = {
        "next_cycle_id": seed["next_cycle_id"],
        "cycle_revision": seed["cycle_revision"],
        "publish_result_digest": seed["lineage"]["publish_result_digest"],
        "metric_snapshot_digest": seed["lineage"]["metric_snapshot_digest"],
        "decision_handoff_digest": seed["lineage"]["decision"]["handoff_digest"],
    }
    seed["idempotency_key"] = "grs1:" + m.sha256_json(identity)
    seed["seed_digest"] = m.sha256_json(seed)
    return {
        "contractVersion": m.GROWTH_R10_ENVELOPE_VERSION,
        "source": {
            "repository": m.GROWTH_R10_REPOSITORY,
            "branch": m.GROWTH_R10_BRANCH,
            "producerSha": GROWTH_HEAD,
            "contractPath": m.GROWTH_R10_CONTRACT_PATH,
            "contractBlobSha": GROWTH_BLOB,
        },
        "seed": seed,
    }


def stage_payloads(p: dict) -> dict:
    script_text = "Hook fast. Show the proof. End with one concrete call to action."
    media = media_envelope(p)
    artifact_id = media["artifactManifest"]["content"]["contentId"]
    artifact_digest = media["artifactManifest"]["content"]["sha256"]
    provider = "instagram_reels"
    destination = "fixture-account"
    auth = {
        "contractVersion": m.RELEASE_AUTHORIZATION_VERSION,
        "decisionId": "decision-001",
        "idempotencyKey": "release-auth-001",
        "requestId": "release-request-001",
        "campaignId": "cycle-2",
        "candidateId": "candidate-001",
        "artifactId": artifact_id,
        "artifactHash": f"sha256:{artifact_digest}",
        "lineageHash": "sha256:" + "b" * 64,
        "destinationScope": {"provider": provider, "destination": destination, "action": "release"},
        "decision": "approved",
        "authorizationId": "authorization-001",
        "expiresAt": "2026-10-02T00:00:00+00:00",
        "decidedAt": "2026-10-01T00:00:00+00:00",
        "decisionSource": "external",
        "approverRef": "fixture-human-approver",
    }
    return {
        "brief": {"goal": "Create a useful 30-second Reel", "topic": "editing workflow", "audience": "short-form creators"},
        "research_evidence": {
            "items": [
                {
                    "evidenceId": "evidence-1",
                    "sourceUri": "fixture://research/source-1",
                    "sha256": "c" * 64,
                    "capturedAt": "2026-10-01T00:00:00Z",
                }
            ]
        },
        "idea_hook": {
            "idea": "Show before/after pacing",
            "hook": "Your first three seconds are too slow.",
            "hookWindowSeconds": p["hookWindowSeconds"],
        },
        "script": {"revision": 1, "text": script_text, "sha256": m.sha256_text(script_text)},
        "asset_plan": {
            "assets": [
                {
                    "assetId": "asset-1",
                    "sourceUri": "fixture://asset/1",
                    "sha256": "d" * 64,
                    "rightsRef": "fixture-rights-1",
                }
            ]
        },
        "edit_request": {
            "voice": {"mode": "voiceover", "sourceRef": "fixture://voice/1"},
            "music": {"assetRef": "fixture://music/1", "duckUnderVoiceDb": -9},
            "subtitles": {"enabled": True, "language": "en", "burnIn": True},
            "edit": {
                "trim": True,
                "cuts": "beat-aligned",
                "reframe": "center-subject",
                "transitions": "requested-only",
                "ctaOutroSeconds": 2.0,
            },
            "profileDigest": p["profileDigest"],
        },
        "media_render": media,
        "critic_qa": {
            "decision": "pass",
            "qaDigest": "e" * 64,
            "checks": [
                {"name": "hook-within-window", "pass": True},
                {"name": "captions-present", "pass": True},
                {"name": "media-qa-bound", "pass": True},
            ],
        },
        "publish_queue": {
            "intentId": "publish-intent-001",
            "idempotencyKey": "publish:cycle-2:001",
            "provider": provider,
            "destination": destination,
            "platform": provider,
            "artifactId": artifact_id,
            "artifactDigest": artifact_digest,
            "caption": p["metadata"]["caption"],
            "cta": p["metadata"]["cta"],
            "releaseAuthorization": auth,
            "adapterState": {
                "state": "ready",
                "provider": provider,
                "destination": destination,
                "recoverySupported": True,
                "idempotentSubmit": True,
                "evidenceDigest": "f" * 64,
            },
        },
    }


class AutonomousReelsR11Tests(unittest.TestCase):
    def new_ledger(self, path: Path, p: dict | None = None) -> m.AutonomousReelsLedger:
        p = p or profile()
        return m.AutonomousReelsLedger(
            path,
            cycle_id="cycle-2",
            topic="editing workflow",
            cycle_revision=2,
            profile=p,
            media_producer_sha=MEDIA_HEAD,
            media_job_contract_blob_sha=MEDIA_JOB_BLOB,
            media_manifest_contract_blob_sha=MEDIA_MANIFEST_BLOB,
            growth_producer_sha=GROWTH_HEAD,
            growth_contract_blob_sha=GROWTH_BLOB,
            allow_synthetic_fixture=True,
        )

    def test_profile_is_canonical_vertical_shortform(self):
        p = profile()
        self.assertEqual(p["canvas"]["aspectRatio"], "9:16")
        self.assertEqual((p["canvas"]["width"], p["canvas"]["height"]), (1080, 1920))
        self.assertEqual(p["durationSeconds"], {"targetMin": 15.0, "targetMax": 60.0})
        self.assertEqual(p["hookWindowSeconds"], {"start": 0.0, "end": 3.0})
        self.assertEqual(set(p["metadata"]["platformTargets"]), set(m.PLATFORMS))
        material = dict(p)
        digest = material.pop("profileDigest")
        self.assertEqual(digest, m.sha256_json(material))

    def test_media_live_source_fails_closed_while_r11_branch_is_still_at_premilestone_head(self):
        p = profile()
        live = media_envelope(p, source_class="provider")
        with self.assertRaises(m.DependencyUnavailable):
            m.validate_media_r11_envelope(
                live,
                expected_producer_sha=MEDIA_HEAD,
                expected_job_contract_blob_sha=MEDIA_JOB_BLOB,
                expected_manifest_contract_blob_sha=MEDIA_MANIFEST_BLOB,
                expected_profile_digest=p["profileDigest"],
            )

    def test_growth_seed_exactly_once_across_restart_lost_ack_and_stale_revision(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            ledger = self.new_ledger(path)
            envelope = growth_seed_envelope()
            with self.assertRaises(m.InjectedCrash):
                ledger.consume_growth_seed(envelope, expected_source_cycle_revision=1, crash_after_commit=True)
            reopened = self.new_ledger(path)
            self.assertEqual(reopened.consume_growth_seed(envelope, expected_source_cycle_revision=1), "duplicate")
            self.assertEqual(len(reopened.growth_consumed), 1)
            stale = growth_seed_envelope(revision=2)
            with self.assertRaises(m.StageOrderError):
                reopened.consume_growth_seed(stale, expected_source_cycle_revision=1)

    def test_crash_restart_after_every_stage_is_resumable_and_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            p = profile()
            payloads = stage_payloads(p)
            ledger = self.new_ledger(path, p)
            ledger.consume_growth_seed(growth_seed_envelope(), expected_source_cycle_revision=1)
            provider = m.FakePublishProvider()
            for stage in m.REELS_STAGES:
                if stage == "publish_result":
                    intent = ledger.stage_records["publish_queue"]["payload"]
                    receipt = provider.submit(intent)
                    payload = {"receipt": receipt}
                elif stage == "analytics_handoff":
                    payload = ledger.build_growth_handoff()
                else:
                    payload = payloads[stage]
                with self.assertRaises(m.InjectedCrash):
                    ledger.commit_stage(stage, payload, provenance=provenance(stage), crash_after_commit=True)
                ledger = self.new_ledger(path, p)
                self.assertEqual(
                    ledger.commit_stage(stage, payload, provenance=provenance(stage)),
                    "duplicate",
                )
            snapshot = ledger.snapshot()
            self.assertIsNone(snapshot["nextStage"])
            self.assertEqual(snapshot["completedStages"], list(m.REELS_STAGES))
            self.assertEqual(snapshot["growthSeedCount"], 1)
            again = self.new_ledger(path, p).snapshot()
            self.assertEqual(snapshot["stateDigest"], again["stateDigest"])
            expected = json.loads(
                (Path(__file__).resolve().parents[1] / "fixtures" / "autonomous_reels_r11_e2e.expected.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(snapshot, expected["stageCrashSnapshot"])

    def test_duplicate_media_result_is_noop_but_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            p = profile()
            payloads = stage_payloads(p)
            ledger = self.new_ledger(path, p)
            for stage in m.REELS_STAGES[:6]:
                ledger.commit_stage(stage, payloads[stage], provenance=provenance(stage))
            self.assertEqual(ledger.commit_stage("media_render", payloads["media_render"], provenance=provenance("media_render")), "committed")
            self.assertEqual(ledger.commit_stage("media_render", payloads["media_render"], provenance=provenance("media_render")), "duplicate")
            changed = copy.deepcopy(payloads["media_render"])
            changed["preview"]["sha256"] = "0" * 64
            with self.assertRaises(m.ContractValidationError):
                ledger.commit_stage("media_render", changed, provenance=provenance("media_render"))

    def test_publish_lost_ack_recovers_result_after_effect_without_second_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            p = profile()
            payloads = stage_payloads(p)
            ledger = self.new_ledger(path, p)
            for stage in m.REELS_STAGES[:9]:
                ledger.commit_stage(stage, payloads[stage], provenance=provenance(stage))
            provider = m.FakePublishProvider(fail_after_effect_once=True)
            with self.assertRaises(m.PublishOutcomeUnknown):
                ledger.execute_publish(provider, now="2026-10-01T00:30:00Z")
            self.assertEqual(provider.accepted_effects, 1)
            self.assertEqual(provider.calls, 1)
            reopened = self.new_ledger(path, p)
            self.assertTrue(reopened.snapshot()["publishPrepared"])
            self.assertFalse(reopened.snapshot()["publishReceiptCommitted"])
            self.assertEqual(reopened.execute_publish(provider, now="2026-10-01T00:30:00Z"), "committed")
            self.assertEqual(provider.accepted_effects, 1)
            self.assertEqual(provider.calls, 1)
            final = self.new_ledger(path, p)
            self.assertEqual(final.execute_publish(provider, now="2026-10-01T00:30:00Z"), "duplicate")
            self.assertEqual(provider.accepted_effects, 1)
            expected = json.loads(
                (Path(__file__).resolve().parents[1] / "fixtures" / "autonomous_reels_r11_e2e.expected.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(
                {"providerCalls": provider.calls, "acceptedEffects": provider.accepted_effects},
                expected["publishRecovery"],
            )

    def test_publish_intent_requires_external_release_authorization_and_ready_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            p = profile()
            payloads = stage_payloads(p)
            ledger = self.new_ledger(path, p)
            for stage in m.REELS_STAGES[:8]:
                ledger.commit_stage(stage, payloads[stage], provenance=provenance(stage))
            bad = copy.deepcopy(payloads["publish_queue"])
            bad["releaseAuthorization"]["decisionSource"] = "creator"
            with self.assertRaises(m.PublishGateError):
                ledger.commit_stage("publish_queue", bad, provenance=provenance("publish_queue"))
            bad = copy.deepcopy(payloads["publish_queue"])
            bad["adapterState"]["state"] = "disconnected"
            with self.assertRaises(m.PublishGateError):
                ledger.commit_stage("publish_queue", bad, provenance=provenance("publish_queue"))

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            p = profile()
            payloads = stage_payloads(p)
            ledger = self.new_ledger(path, p)
            for stage in m.REELS_STAGES[:9]:
                ledger.commit_stage(stage, payloads[stage], provenance=provenance(stage))
            with self.assertRaises(m.PublishGateError):
                ledger.execute_publish(
                    m.FakePublishProvider(),
                    now="2026-10-02T00:00:00Z",
                )

    def test_growth_handoff_from_synthetic_publish_never_claims_live_platform_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            p = profile()
            payloads = stage_payloads(p)
            ledger = self.new_ledger(path, p)
            for stage in m.REELS_STAGES[:9]:
                ledger.commit_stage(stage, payloads[stage], provenance=provenance(stage))
            provider = m.FakePublishProvider()
            ledger.execute_publish(provider, now="2026-10-01T00:30:00Z")
            handoff = ledger.build_growth_handoff()
            publish = handoff["publishResult"]
            self.assertEqual(publish["source_class"], "synthetic_fixture")
            self.assertFalse(publish["provenance"]["live_performance_claim_allowed"])
            self.assertIsNone(publish["provenance"]["provider_receipt_digest"])
            self.assertEqual(publish["provenance"]["fixture_source_sha256"], ledger.publish_receipt["providerReceiptDigest"])

    def test_secret_shaped_fields_are_rejected_from_durable_stage_payloads(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cycle.jsonl"
            ledger = self.new_ledger(path)
            bad = {"goal": "g", "topic": "t", "audience": "a", "apiKey": "should-not-persist"}
            with self.assertRaises(m.ContractValidationError):
                ledger.commit_stage("brief", bad, provenance=provenance("brief"))


if __name__ == "__main__":
    unittest.main()
