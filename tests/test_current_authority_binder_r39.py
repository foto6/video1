from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import current_authority_binder_r39 as r39
from creator_orchestrator import local_fullstack_rehearsal_r38 as r38


class R39AuthorityTests(unittest.TestCase):
    def test_default_readiness_waits_only_for_media_r27_qa(self):
        value = r39.readiness()
        self.assertEqual(value["state"], "WAITING_MEDIA_R27_QA")
        self.assertTrue(value["sourceReady"])
        self.assertTrue(value["mediaR27ExactGreen"])
        self.assertFalse(value["mediaR27QaAccepted"])
        self.assertEqual(value["growthCurrentSha"], "f3cb8ec0d8aa7155b6169d5f86828de3fbc9d3ba")
        self.assertEqual(value["bridgeCurrentSha"], "a6adf698764776856567239b07b0687e8ac89fa5")
        self.assertEqual(value["mediaR27Sha"], "183838a24205c6885b2366ad6ffa394164283d91")
        self.assertFalse(value["movingRefsAccepted"])
        self.assertFalse(value["liveAuthorization"])
        self.assertFalse(value["publishAllowed"])

    def test_checked_in_authorities_are_exact(self):
        values = r39.checked_in_authorities()
        self.assertEqual(values["creator"], r39.CREATOR_EXPECTED)
        self.assertEqual(values["growth"], r39.GROWTH_EXPECTED)
        self.assertEqual(values["bridge"], r39.BRIDGE_EXPECTED)
        self.assertEqual(values["media"], r39.MEDIA_EXPECTED)

    def test_fixture_qa_can_prove_source_ready_only_when_explicitly_allowed(self):
        qa = r39.fixture_media_qa()
        with self.assertRaises(r39.MediaR27QARequired):
            r39.readiness(qa)
        ready = r39.readiness(qa, allow_fixture_qa=True)
        self.assertEqual(ready["state"], "SOURCE_READY")
        self.assertTrue(ready["mediaR27QaAccepted"])

    def test_authority_set_digest_binds_all_exact_manifests(self):
        value = r39.authority_set(allow_pending_media=True)
        self.assertEqual(set(value["authorityDigests"]), {"creator", "growth", "bridge", "media"})
        self.assertFalse(value["mediaQaAccepted"])
        self.assertFalse(value["liveAuthorization"])

    def test_real_authority_set_fails_without_media_qa(self):
        with self.assertRaises(r39.MediaR27QARequired):
            r39.authority_set()

    def test_r38_history_validator_is_reused(self):
        with tempfile.TemporaryDirectory() as td:
            evidence = r39.verify_immutable_r38_history(Path(td))
            self.assertTrue(evidence["r38MediaValidatorReused"])
            self.assertFalse(evidence["liveAuthorization"])


class R39BundleTests(unittest.TestCase):
    def test_fixture_r27_bundle_has_four_distinct_candidates(self):
        bundle = r39.validate_r27_bundle(r39.fixture_r27_bundle())
        self.assertEqual(len(bundle["candidates"]), 4)
        self.assertEqual(len({c["sha256"] for c in bundle["candidates"]}), 4)
        self.assertEqual(bundle["targetedReedit"]["sha256"], bundle["finalArtifact"]["sha256"])
        self.assertFalse(bundle["evidenceBoundary"]["liveAuthorization"])

    def test_operation_identity_binds_authority_and_bundle_digests(self):
        authorities = r39.authority_set(allow_pending_media=True)
        bundle = r39.fixture_r27_bundle()
        identity = r39.operation_identity("op-1", bundle, authorities)
        self.assertEqual(identity["sealedBundleDigest"], bundle["manifestDigest"])
        self.assertEqual(identity["authoritySetDigest"], authorities["authoritySetDigest"])
        self.assertEqual(identity["authorityDigests"], authorities["authorityDigests"])


class R39FixtureTests(unittest.TestCase):
    def test_fixture_closed_loop_is_safe_and_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = r39.run_fixture(root)
            self.assertEqual(status["state"], "LOCAL_REHEARSAL_COMPLETE")
            self.assertEqual(status["readinessState"], "WAITING_MEDIA_R27_QA")
            self.assertEqual(status["finalDisposition"], "LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE")
            self.assertFalse(status["mediaQaAccepted"])
            self.assertFalse(status["liveAuthorization"])
            manifest = json.loads((root / status["manifestPath"]).read_text())
            self.assertFalse(manifest["publishAllowed"])
            self.assertFalse(manifest["liveBridgeCutover"])
            self.assertEqual(manifest["selectedWinnerSha256"], manifest["targetedReeditSha256"])

    def test_exact_replay_reuses_verified_stage_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = r39.run_fixture(root)
            ledger = root / r38.workspace_layout()["ledger"]
            count = len(ledger.read_text().splitlines())
            second = r39.run_fixture(root)
            self.assertEqual(first["manifestDigest"], second["manifestDigest"])
            self.assertEqual(count, len(ledger.read_text().splitlines()))

    def test_changed_bundle_under_same_workspace_identity_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r39.run_fixture(root)
            authorities = r39.authority_set(allow_pending_media=True)
            bundle = r39.fixture_r27_bundle()
            bundle["inputVideo"]["sha256"] = "0" * 64
            bundle["manifestDigest"] = r39.sha256_json({k: v for k, v in bundle.items() if k != "manifestDigest"})
            with self.assertRaises(r38.ReplayConflict):
                r39._bind(
                    bundle=bundle,
                    authorities=authorities,
                    workspace=root,
                    operation_id="creator-r39-current-authority-fixture",
                )

    def test_changed_authority_under_same_identity_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r39.run_fixture(root)
            authorities = r39.authority_set(allow_pending_media=True)
            changed = copy.deepcopy(authorities)
            changed["authorityDigests"]["growth"] = "0" * 64
            changed["authoritySetDigest"] = r39.sha256_json(
                {k: v for k, v in changed.items() if k != "authoritySetDigest"}
            )
            with self.assertRaises(r38.ReplayConflict):
                r39._bind(
                    bundle=r39.fixture_r27_bundle(),
                    authorities=changed,
                    workspace=root,
                    operation_id="creator-r39-current-authority-fixture",
                )

    def test_proof_and_release_escrow_are_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = r39.run_fixture(root)
            manifest = json.loads((root / status["manifestPath"]).read_text())
            proof_escrow = json.loads((root / manifest["proofEscrowEvidence"]["path"]).read_text())
            self.assertEqual(
                proof_escrow["proof"]["contractVersion"],
                "creator.local_integration_proof_graph.r37.v1",
            )
            self.assertEqual(
                proof_escrow["escrow"]["contractVersion"],
                "creator.current_release_escrow_binding.r39.v1",
            )
            self.assertFalse(proof_escrow["escrow"]["liveAuthorization"])
            self.assertEqual(proof_escrow["escrow"]["providerEffects"], 0)

    def test_status_rejects_final_manifest_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = r39.run_fixture(root)
            path = root / status["manifestPath"]
            body = json.loads(path.read_text())
            body["liveAuthorization"] = True
            path.write_text(json.dumps(body))
            with self.assertRaises(r39.R39Error):
                r39.status(root)

    def test_evidence_reports_adversarial_count(self):
        with tempfile.TemporaryDirectory() as td:
            summary = r39.run_evidence(td)
            self.assertGreaterEqual(summary["adversarialCaseCount"], 25)
            self.assertTrue(summary["allAdversarialCasesPassed"])
            self.assertEqual(summary["state"], "WAITING_MEDIA_R27_QA")
            self.assertFalse(summary["liveAuthorization"])


class R39CliTests(unittest.TestCase):
    def test_readiness_cli_returns_three_while_waiting_media_qa(self):
        self.assertEqual(r39.main(["readiness"]), 3)

    def test_fixture_cli_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(r39.main(["fixture", "--workspace", td]), 0)


class R39AdversarialTests(unittest.TestCase):
    pass


def _make_adversarial_test(name):
    def test(self):
        self.assertTrue(r39.run_one_adversarial_case(name), name)
    test.__name__ = "test_" + name
    return test


for _name in r39.ADVERSARIAL_CASE_NAMES:
    setattr(R39AdversarialTests, "test_" + _name, _make_adversarial_test(_name))


if __name__ == "__main__":
    unittest.main()
