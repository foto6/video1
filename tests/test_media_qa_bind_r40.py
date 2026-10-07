from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import media_qa_bind_r40 as r40


class R40CertificateTests(unittest.TestCase):
    def test_pinned_certificate_is_exact_real_acceptance(self):
        value = r40.validate_pinned_source()
        cert = value["certificate"]
        self.assertEqual(cert["producerSha"], "6ab529846e99e572d77006dee48d6c4b01caea12")
        self.assertEqual(cert["ciRunId"], 37452884976)
        self.assertEqual(cert["artifactId"], 11407720740)
        self.assertEqual(
            cert["artifactDigest"],
            "sha256:910326676dd9371745cb70099ec3db76a21ad7f0d5e171bcd59bddfa091bd7d8",
        )
        self.assertEqual(
            cert["matrixDigest"],
            "831804bedce4652156ac052e1c50f1e6f3642cd36dadbc58a00907804e646a54",
        )
        self.assertIs(cert["fixtureOnly"], False)
        self.assertEqual(cert["disposition"], "ACCEPTED")

    def test_certificate_binds_exact_media_r27_tuple(self):
        cert = r40.validate_pinned_source()["certificate"]
        self.assertEqual(cert["acceptedMediaProducerSha"], r40.MEDIA_SHA)
        self.assertEqual(cert["acceptedMediaCiRunId"], r40.MEDIA_CI_RUN_ID)
        self.assertEqual(cert["acceptedMediaArtifactId"], r40.MEDIA_ARTIFACT_ID)
        self.assertEqual(cert["acceptedMediaArtifactDigest"], r40.MEDIA_ARTIFACT_DIGEST)
        self.assertEqual(cert["acceptedMediaContract"], r40.MEDIA_CONTRACT)
        self.assertEqual(
            cert["acceptedMediaGrowthBundleContract"],
            r40.MEDIA_GROWTH_BUNDLE_CONTRACT,
        )

    def test_certificate_raw_bytes_are_pinned(self):
        value = r40.validate_pinned_source()
        self.assertEqual(value["certificateRawSha256"], r40.QA_CERTIFICATE_RAW_SHA256)
        self.assertEqual(value["matrixRawSha256"], r40.QA_MATRIX_SHA256)

    def test_matrix_contains_independent_media_acceptance(self):
        matrix = r40.validate_pinned_source()["matrix"]
        media = next(row for row in matrix["rows"] if row["role"] == "MediaR27")
        self.assertEqual(media["status"], "ACCEPTED")
        self.assertEqual(media["exact_sha"], r40.MEDIA_SHA)
        self.assertFalse(matrix["media_independent_qa"]["live_authorization"])

    def test_fixture_certificate_is_rejected(self):
        cert = r40.expected_certificate()
        cert["fixtureOnly"] = True
        with self.assertRaises(r40.CertificateError):
            r40.validate_certificate(cert)

    def test_stale_qa_producer_is_rejected(self):
        cert = r40.expected_certificate()
        cert["producerSha"] = "0" * 40
        with self.assertRaises(r40.CertificateError):
            r40.validate_certificate(cert)

    def test_moving_ref_is_rejected(self):
        cert = r40.expected_certificate()
        cert["branch"] = "agent/moving"
        with self.assertRaises(r40.R40Error):
            r40.validate_certificate(cert)


class R40BridgeTests(unittest.TestCase):
    def test_r42_remains_current_accepted_bridge(self):
        value = r40.validate_bridge_refresh(r40.expected_bridge_refresh())
        self.assertEqual(value["selectedAuthoritySha"], r40.BRIDGE_ACCEPTED_SHA)
        self.assertFalse(value["authorityRefreshed"])
        self.assertFalse(value["liveCutoverAuthorized"])

    def test_r43_exact_source_green_is_not_promoted_without_control_plane_acceptance(self):
        value = r40.validate_bridge_refresh(r40.expected_bridge_refresh())
        observed = value["observedSuccessor"]
        self.assertEqual(observed["sourceSha"], r40.BRIDGE_R43_OBSERVED_SHA)
        self.assertEqual(observed["ciRunId"], r40.BRIDGE_R43_OBSERVED_CI)
        self.assertEqual(observed["ciConclusion"], "success")
        self.assertEqual(observed["readiness"], "EXACT_HEAD_READY_FOR_CONTROLLED_PREFLIGHT")
        self.assertFalse(observed["acceptedForCurrentControlPlane"])
        self.assertGreaterEqual(len(observed["missingAcceptanceEvidence"]), 3)

    def test_unaccepted_r43_cannot_be_selected(self):
        value = r40.expected_bridge_refresh()
        value["selectedAuthoritySha"] = r40.BRIDGE_R43_OBSERVED_SHA
        with self.assertRaises(r40.BridgeAuthorityError):
            r40.validate_bridge_refresh(value)

    def test_live_cutover_authorization_is_rejected(self):
        value = r40.expected_bridge_refresh()
        value["liveCutoverAuthorized"] = True
        with self.assertRaises(r40.BridgeAuthorityError):
            r40.validate_bridge_refresh(value)


class R40ReadinessTests(unittest.TestCase):
    def test_media_qa_advances_r39_gate_to_source_ready(self):
        value = r40.readiness()
        self.assertEqual(value["state"], "SOURCE_READY")
        self.assertTrue(value["localRehearsalReady"])
        self.assertTrue(value["mediaR27QaAccepted"])
        self.assertFalse(value["mediaR27QaFixtureOnly"])
        self.assertFalse(value["bridgeAuthorityRefreshed"])
        self.assertFalse(value["liveAuthorization"])
        self.assertFalse(value["publishAllowed"])
        self.assertFalse(value["liveBridgeCutover"])
        self.assertFalse(value["actualLocalPcE2EExecuted"])
        self.assertFalse(value["overallStackGoClaimed"])

    def test_authority_binding_contains_exact_qa_and_r39_digests(self):
        value = r40.authority_binding()
        self.assertTrue(value["mediaQaAccepted"])
        self.assertFalse(value["mediaQaFixtureOnly"])
        self.assertEqual(value["qaCertificateRawSha256"], r40.QA_CERTIFICATE_RAW_SHA256)
        self.assertEqual(value["sourceMatrixDigest"], r40.QA_MATRIX_SHA256)
        self.assertEqual(value["selectedBridgeAuthoritySha"], r40.BRIDGE_ACCEPTED_SHA)
        self.assertFalse(value["bridgeAuthorityRefreshed"])
        self.assertFalse(value["liveAuthorization"])


class R40FixtureTests(unittest.TestCase):
    def test_fixture_completes_with_source_ready_and_no_live_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = r40.run_fixture(root)
            self.assertEqual(status["state"], "LOCAL_REHEARSAL_COMPLETE")
            self.assertEqual(status["readinessState"], "SOURCE_READY")
            self.assertTrue(status["mediaQaAccepted"])
            self.assertFalse(status["bridgeAuthorityRefreshed"])
            self.assertFalse(status["liveAuthorization"])
            self.assertFalse(status["publishAllowed"])
            manifest = json.loads((root / status["manifestPath"]).read_text())
            self.assertEqual(
                manifest["finalDisposition"],
                "LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE",
            )
            self.assertTrue(manifest["localRehearsalReady"])
            self.assertFalse(manifest["actualLocalPcE2EExecuted"])
            self.assertFalse(manifest["overallStackGoClaimed"])

    def test_exact_replay_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = r40.run_fixture(root)
            first_bytes = (root / first["manifestPath"]).read_bytes()
            second = r40.run_fixture(root)
            self.assertEqual(first["manifestDigest"], second["manifestDigest"])
            self.assertEqual(first_bytes, (root / second["manifestPath"]).read_bytes())

    def test_status_detects_manifest_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = r40.run_fixture(root)
            path = root / status["manifestPath"]
            body = json.loads(path.read_text())
            body["liveAuthorization"] = True
            path.write_text(json.dumps(body))
            with self.assertRaises(r40.R40Error):
                r40.status(root)

    def test_status_without_workspace_evidence_returns_source_ready(self):
        with tempfile.TemporaryDirectory() as td:
            value = r40.status(td)
            self.assertEqual(value["state"], "SOURCE_READY")
            self.assertTrue(value["mediaR27QaAccepted"])

    def test_evidence_is_deterministic_and_adversarial_green(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = r40.run_evidence(root)
            first_bytes = (root / "evidence-summary.r40.json").read_bytes()
            second = r40.run_evidence(root)
            self.assertEqual(first["evidenceDigest"], second["evidenceDigest"])
            self.assertEqual(first_bytes, (root / "evidence-summary.r40.json").read_bytes())
            self.assertGreaterEqual(first["adversarialCaseCount"], 50)
            self.assertTrue(first["allAdversarialCasesPassed"])
            self.assertEqual(first["state"], "SOURCE_READY")
            self.assertFalse(first["liveAuthorization"])


class R40CliTests(unittest.TestCase):
    def test_readiness_cli_is_success(self):
        self.assertEqual(r40.main(["readiness"]), 0)

    def test_validate_pinned_certificate_cli(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "validated.json"
            self.assertEqual(
                r40.main(
                    [
                        "validate-certificate",
                        "--certificate",
                        str(r40.CERTIFICATE_PATH),
                        "--out",
                        str(out),
                    ]
                ),
                0,
            )
            value = json.loads(out.read_text())
            self.assertTrue(value["valid"])
            self.assertFalse(value["liveAuthorization"])

    def test_fixture_cli_is_success(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(r40.main(["fixture", "--workspace", td]), 0)


class R40AdversarialTests(unittest.TestCase):
    pass


def _make_case(name):
    def test(self):
        self.assertTrue(r40.run_one_adversarial_case(name), name)
    test.__name__ = "test_" + name
    return test


for _name in r40.ADVERSARIAL_CASE_NAMES:
    setattr(R40AdversarialTests, "test_" + _name, _make_case(_name))


if __name__ == "__main__":
    unittest.main()
