from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import candidate_tournament as r15
from creator_orchestrator import media_r13_compat as m13


class MediaR13ProductionPinR16Tests(unittest.TestCase):
    def bundle(self):
        return m13.load_and_validate_bundle()

    def test_exact_media_r13_pin_and_every_pinned_git_blob_are_green(self):
        actual = m13.validate_local_pinned_contracts()
        self.assertEqual(
            actual["mediaJobConsumerManifest"],
            "96b252acae743f8fe059fd634ee320f92bd9c79c",
        )
        self.assertEqual(
            actual["mediaArtifactManifest"],
            "42aed1ca4720cddd4a5e48af076bc73b663322b0",
        )
        self.assertEqual(
            actual["creativePlanManifest"],
            "d031a07f1d392c690942bd5f8288a1713f1af791",
        )
        self.assertEqual(
            actual["creativePlanContract"],
            "5298aeb2a9e4e13ed31b1610ce88778b7a911592",
        )
        self.assertEqual(
            actual["shortformEditorManifest"],
            "07c38a048d23490b8e55924697650e9969bf089f",
        )
        self.assertEqual(
            actual["shortformProfile"],
            "d8f19d9a9d117c5736238159bd5e6d2491370986",
        )
        self.assertEqual(
            actual["compatContract"],
            "ecfeaed347b53ed549124b9d1701ebf70b37eea3",
        )
        self.assertEqual(
            actual["resultEnvelopeSchema"],
            "119b26b494df77c4ce8d83ffd63791afc112d264",
        )
        self.assertEqual(
            actual["technicalQaSchema"],
            "1b2f71e443b0038736e8be99f544493965693658",
        )
        self.assertEqual(
            actual["creativeQualitySchema"],
            "c63f95b45f5440aabd8c14dc5fcb8eeae1fc8535",
        )
        self.assertEqual(
            actual["creatorCompatManifest"],
            "b750b347f6c6a7a2398e47e53e166f5fb1c72781",
        )
        ready = m13.readiness()
        self.assertEqual(ready["state"], "READY_MEDIA_R13")
        self.assertTrue(ready["productionMediaReady"])
        self.assertEqual(
            ready["acceptedPin"]["producerSha"],
            "ad4e0ba487a3cabc84dd339d412e19a0db0f9add",
        )
        self.assertEqual(ready["ciRunId"], "36801556474")
        self.assertEqual(ready["ciConclusion"], "success")

    def test_old_failed_media_r12_sha_remains_rejected(self):
        pin = m13.MediaR13ProductionPin(
            producer_sha="98f298b88faaef106fb412712d6c9824e2b926d9"
        )
        with self.assertRaises(m13.MediaR13CompatibilityError):
            pin.validate()
        ready = m13.readiness(pin=pin)
        self.assertEqual(ready["state"], "BLOCKED_MEDIA_R13")
        self.assertFalse(ready["productionMediaReady"])
        self.assertIn("producer SHA", ready["reason"])
        self.assertTrue(ready["oldFailedMediaR12Rejected"])

    def test_changed_pin_blob_ids_and_schema_fail_closed(self):
        changed_contract = m13.MediaR13ProductionPin(
            compatibility_contract_blob_sha="f" * 40
        )
        with self.assertRaises(m13.MediaR13CompatibilityError):
            changed_contract.validate()

        changed_schema = m13.MediaR13ProductionPin(
            result_envelope_schema_blob_sha="e" * 40
        )
        with self.assertRaises(m13.MediaR13CompatibilityError):
            changed_schema.validate()

        bundle = self.bundle()
        drift = copy.deepcopy(bundle)
        drift["contractDigests"]["technicalQaSchema"]["gitBlobSha"] = "d" * 40
        with self.assertRaises(m13.MediaR13CompatibilityError):
            m13.validate_bundle_value(drift)

    def test_changed_producer_and_unknown_envelope_schema_field_fail_closed(self):
        bundle = self.bundle()
        stale = copy.deepcopy(bundle)
        stale["producer"]["sha"] = "98f298b88faaef106fb412712d6c9824e2b926d9"
        with self.assertRaises(m13.MediaR13CompatibilityError):
            m13.validate_bundle_value(stale)

        envelope = copy.deepcopy(bundle["demoConsumerEnvelope"])
        envelope["futureSchemaField"] = True
        with self.assertRaises(m13.MediaR13CompatibilityError):
            m13.validate_envelope(envelope)

    def test_technical_qa_and_creative_guardrail_tamper_fail_closed(self):
        bundle = self.bundle()

        technical = copy.deepcopy(bundle["demoConsumerEnvelope"])
        technical["technicalQa"]["passed"] = False
        with self.assertRaises(m13.MediaR13CompatibilityError):
            m13.validate_envelope(technical)

        creative = copy.deepcopy(bundle["demoConsumerEnvelope"])
        creative["creativeQuality"]["guardrails"][0]["pass"] = False
        with self.assertRaises(m13.MediaR13CompatibilityError):
            m13.validate_envelope(creative)

    def test_exact_workflow_artifact_reemits_identical_bundle_and_envelope(self):
        with tempfile.TemporaryDirectory() as temp:
            emitted = m13.emit_exact_workflow_artifact(temp)
            bundle_bytes = Path(emitted["bundlePath"]).read_bytes()
            envelope_bytes = Path(emitted["envelopePath"]).read_bytes()
        self.assertEqual(
            hashlib.sha256(bundle_bytes).hexdigest(),
            "e5f45429604519e2776fddeedb11032baae2728799aebfff2f6f1076686eeb7f",
        )
        self.assertEqual(
            hashlib.sha256(envelope_bytes).hexdigest(),
            "e7ee654f3a3b098f32d7611ff721e506eb26caffe44d1a77aa25f077be94541c",
        )
        self.assertEqual(emitted["producerSha"], m13.MEDIA_R13_PRODUCER_SHA)
        self.assertEqual(emitted["ciRunId"], "36801556474")
        self.assertEqual(emitted["workflowArtifactId"], "11136028209")

    def test_real_cross_repo_roundtrip_enters_r15_without_synthetic_substitution(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r15.run_real_media_r13_roundtrip(temp)
        self.assertEqual(
            report["state"],
            "REAL_MEDIA_R13_COMPATIBILITY_GREEN",
        )
        self.assertTrue(report["productionMediaReady"])
        self.assertFalse(report["livePublishingEnabled"])
        self.assertFalse(report["credentialsPresent"])
        self.assertEqual(
            report["mediaSource"]["producerSha"],
            "ad4e0ba487a3cabc84dd339d412e19a0db0f9add",
        )
        self.assertEqual(report["mediaSource"]["ciRunId"], "36801556474")
        self.assertEqual(report["mediaSource"]["ciConclusion"], "success")
        self.assertTrue(report["acceptedCandidate"]["technicalQaPassed"])
        self.assertTrue(report["acceptedCandidate"]["creativeQualityPassed"])
        self.assertEqual(
            report["tournamentAcceptance"]["realCandidateCount"],
            1,
        )
        self.assertEqual(
            report["tournamentAcceptance"]["decisionState"],
            "insufficient_evidence",
        )
        self.assertFalse(
            report["tournamentAcceptance"]["qualityCertaintyClaimed"]
        )
        self.assertEqual(
            report["tournamentAcceptance"]["fakeRealRendersCreated"],
            0,
        )
        self.assertEqual(
            report["tournamentAcceptance"]["syntheticMultiCandidateBreadth"],
            "separate_conformance_only",
        )

    def test_real_roundtrip_is_restart_safe_and_provenance_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            first = r15.run_real_media_r13_roundtrip(temp)
            second = r15.run_real_media_r13_roundtrip(temp)
        self.assertEqual(first["reportDigest"], second["reportDigest"])
        self.assertEqual(
            first["tournamentLedgerDigest"],
            second["tournamentLedgerDigest"],
        )
        self.assertEqual(
            first["acceptedCandidate"]["evaluationDigest"],
            second["acceptedCandidate"]["evaluationDigest"],
        )

    def test_synthetic_multi_candidate_breadth_remains_conformance_only(self):
        with tempfile.TemporaryDirectory() as temp:
            report = r15.run_deterministic_replay(temp)
        self.assertEqual(report["state"], "SYNTHETIC_REPLAY_GREEN")
        self.assertFalse(report["productionReadinessClaim"])
        self.assertEqual(
            report["mediaR13Readiness"]["state"],
            "READY_MEDIA_R13",
        )
        self.assertTrue(
            report["mediaR13Readiness"]["productionMediaReady"]
        )
        self.assertEqual(report["candidateCount"], 4)
        self.assertEqual(report["mediaLogicalEffects"], 4)
        self.assertEqual(report["mediaSubmitCalls"], 4)

    def test_checked_in_bundle_is_exact_ci_artifact_bytes(self):
        root = Path(__file__).resolve().parents[1]
        raw = (
            root
            / "fixtures"
            / "media_r13_cross_repo"
            / "compatibility-bundle.json"
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            m13.MEDIA_R13_BUNDLE_SHA256,
        )
        bundle = json.loads(raw)
        self.assertEqual(
            bundle["producer"]["sha"],
            m13.MEDIA_R13_PRODUCER_SHA,
        )
        self.assertEqual(
            bundle["compatibilityManifest"]["gitBlobSha"],
            m13.COMPAT_MANIFEST_BLOB_SHA,
        )


if __name__ == "__main__":
    unittest.main()
