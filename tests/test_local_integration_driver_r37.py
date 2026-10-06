from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import local_integration_driver_r37 as r37


class R37CoreTests(unittest.TestCase):
    def test_readiness_requires_media_and_never_claims_local_e2e(self):
        value = r37.readiness()
        self.assertEqual(value["state"], "SOURCE_READY_WAITING_ACCEPTED_MEDIA")
        self.assertTrue(value["SOURCE_READY"])
        self.assertTrue(value["LOCAL_FIXTURE_REHEARSAL_AVAILABLE"])
        self.assertFalse(value["ACTUAL_LOCAL_PC_E2E_EXECUTED"])
        self.assertTrue(value["media"]["required"])
        self.assertEqual(value["media"]["status"], "UNACCEPTED")
        self.assertEqual(value["media"]["consumption"], "NOT_CONSUMED")
        self.assertFalse(value["fixtureLiveAuthorization"])
        self.assertEqual(value["safety"]["providerEffects"], 0)
        self.assertEqual(value["safety"]["networkEffects"], 0)
        self.assertFalse(value["safety"]["liveAuthorization"])

    def test_exact_growth_bridge_and_qa_authorities_are_frozen(self):
        a = r37.authority_envelope()
        self.assertEqual(
            a["growth"]["producerSha"],
            "9ff243bc5ec6977bc5f0eb8f16cd5e51aa0dcdfc",
        )
        self.assertEqual(a["growth"]["ciRunId"], 37244660304)
        self.assertEqual(a["growth"]["artifactId"], 11318054384)
        self.assertEqual(
            a["growth"]["artifactDigest"],
            "sha256:6fc329964c14ce7c11f27fd2dd47235912470a377c6a1f5a6f3e66f4481f5ac9",
        )
        self.assertEqual(
            a["bridge"]["producerSha"],
            "f4f6070a975ac2c5bd8323777db1514c4733e427",
        )
        self.assertEqual(a["bridge"]["ciRunId"], 37244988343)
        self.assertEqual(a["qaR6"]["producerSha"], "aa415759795beb24f1333d190ff842451020be5f")
        self.assertEqual(a["qaR6"]["ciRunId"], 37245738748)
        self.assertEqual(a["media"]["status"], "UNACCEPTED")
        self.assertEqual(a["media"]["consumption"], "NOT_CONSUMED")
        r37.validate_authority_envelope(a, require_accepted_media=False)

    def test_actual_local_run_blocks_without_independent_media_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            source.write_bytes(b"not-a-real-video-needed-before-media-gate")
            with self.assertRaises(r37.MediaAuthorityRequired):
                r37.prepare_local_run(
                    source_path=source,
                    brief="short brief",
                    out_dir=root / "out",
                    media_authority=None,
                )

    def test_accepted_media_tuple_validator_requires_independent_exact_binding(self):
        media = r37.accepted_media_fixture()
        self.assertEqual(
            r37.validate_media_authority(media, require_accepted=True),
            media,
        )
        media["independentQa"]["acceptedMediaProducerSha"] = "9" * 40
        with self.assertRaises(r37.MediaAuthorityRequired):
            r37.validate_media_authority(media, require_accepted=True)

    def test_fixture_closed_loop_reaches_required_terminal_state(self):
        with tempfile.TemporaryDirectory() as td:
            report = r37.run_fixture_rehearsal(td)
            self.assertEqual(report["state"], "LOCAL_REHEARSAL_COMPLETE")
            self.assertEqual(
                report["finalDisposition"],
                "LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE",
            )
            self.assertEqual(report["candidateCount"], 3)
            self.assertEqual(report["reviewRounds"], 2)
            self.assertEqual(report["targetedReeditRounds"], 1)
            self.assertFalse(report["actualLocalPcE2EExecuted"])
            self.assertFalse(report["mediaAuthorityAccepted"])
            self.assertEqual(report["providerEffects"], 0)
            self.assertEqual(report["networkEffects"], 0)
            self.assertFalse(report["liveAuthorization"])

    def test_fixture_restart_replay_adds_no_event(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = r37.run_fixture_rehearsal(root)
            self.assertEqual(report["eventsAddedOnReplay"], 0)
            ledger = r37.DriverLedger(root)
            before = len(ledger.events)
            state = r37.resume_fixture(ledger)
            self.assertEqual(state["state"], "LOCAL_REHEARSAL_COMPLETE")
            self.assertEqual(len(ledger.events), before)

    def test_proof_graph_and_release_escrow_bind_winner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r37.run_fixture_rehearsal(root)
            state = json.loads((root / "final-state.r37.json").read_text())
            self.assertEqual(
                state["releaseEscrow"]["winnerRenderSha256"],
                state["winner"]["renderSha256"],
            )
            self.assertEqual(
                state["releaseEscrow"]["proofFinalDigest"],
                state["proof"]["finalDigest"],
            )
            self.assertEqual(state["releaseEscrow"]["providerEffects"], 0)
            self.assertFalse(state["releaseEscrow"]["liveAuthorization"])
            self.assertTrue(r37.verify_proof_graph(state["proof"])["valid"])

    def test_evidence_bundle_reports_at_least_25_adversarial_cases(self):
        with tempfile.TemporaryDirectory() as td:
            value = r37.run_evidence(td)
            self.assertGreaterEqual(value["adversarialCaseCount"], 25)
            self.assertTrue(value["allAdversarialCasesPassed"])
            self.assertEqual(value["fixtureState"], "LOCAL_REHEARSAL_COMPLETE")
            self.assertFalse(value["actualLocalPcE2EExecuted"])
            self.assertTrue(value["mediaRequired"])
            self.assertFalse(value["mediaAccepted"])
            self.assertFalse(value["liveAuthorization"])

    def test_cli_run_without_media_returns_blocked_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            source.write_bytes(b"fixture")
            code = r37.main(
                [
                    "run",
                    "--source",
                    str(source),
                    "--brief",
                    "brief",
                    "--out",
                    str(root / "out"),
                ]
            )
            self.assertEqual(code, 3)

    def test_windows_wrapper_exists_and_invokes_module(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = root / "tools" / "creator-local-integration-r37.cmd"
        self.assertTrue(wrapper.is_file())
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("creator_orchestrator.local_integration_driver_r37", text)
        self.assertIn("%*", text)


class R37AdversarialCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.results = r37.run_adversarial_cases(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_case_manifest_count(self):
        self.assertEqual(set(self.results["cases"]), set(r37.ADVERSARIAL_CASES))
        self.assertGreaterEqual(self.results["caseCount"], 25)
        self.assertTrue(self.results["allCasesPassed"])


def _make_case_test(case_name):
    def test(self):
        self.assertIn(case_name, self.results["cases"])
        self.assertTrue(
            self.results["cases"][case_name]["passed"],
            msg=f"adversarial case failed: {case_name}",
        )
    return test


for _case in r37.ADVERSARIAL_CASES:
    setattr(
        R37AdversarialCases,
        "test_adversarial_" + _case,
        _make_case_test(_case),
    )


if __name__ == "__main__":
    unittest.main()
