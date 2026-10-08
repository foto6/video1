from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import autonomous_reels_local_r40 as reels
from creator_orchestrator import media_qa_bind_r40 as mediaqa


class AuthorityDiagnosisTests(unittest.TestCase):
    def test_diagnosis_is_fail_closed_and_specific(self):
        value = reels.diagnosis()
        self.assertEqual(value["state"], "BLOCKED_BEFORE_AUTONOMOUS_REAL_REVIEW")
        self.assertTrue(value["mediaR27AuthorityReady"])
        self.assertFalse(value["growthR39AuthorityReady"])
        self.assertTrue(value["bridgeR44SourceGreen"])
        self.assertFalse(value["bridgeR44LocalCutoverAccepted"])
        self.assertFalse(value["bossR9GoAccepted"])
        self.assertFalse(value["actualLocalInputOutputReceiptPresent"])
        self.assertFalse(value["liveSend"])
        self.assertFalse(value["livePublish"])
        self.assertFalse(value["liveAuthorization"])
        codes = {row["code"] for row in value["blockers"]}
        self.assertIn("WAITING_GROWTH_R39_IMPLEMENTATION", codes)
        self.assertIn("WAITING_REAL_LOCAL_INPUT_OUTPUT_RECEIPT", codes)
        self.assertIn("WAITING_BOSS_R9_GO", codes)
        self.assertIn("HUMAN_REVIEW_REQUIRED_BEFORE_SEND", codes)

    def test_media_qa_is_exact_accepted_non_fixture(self):
        auth = reels.authority_observation()["media"]
        self.assertEqual(auth["producerSha"], reels.MEDIA_SHA)
        self.assertEqual(auth["ciRunId"], reels.MEDIA_CI)
        self.assertEqual(auth["artifactId"], reels.MEDIA_ARTIFACT_ID)
        self.assertEqual(auth["artifactDigest"], reels.MEDIA_ARTIFACT_DIGEST)
        self.assertTrue(auth["independentQaAccepted"])
        self.assertFalse(auth["fixtureOnly"])
        cert = mediaqa.validate_pinned_source()["certificate"]
        self.assertEqual(auth["qaProducerSha"], cert["producerSha"])

    def test_growth_r39_exact_sha_is_task_pointer_only(self):
        auth = reels.authority_observation()["growthR39"]
        self.assertEqual(auth["observedSha"], "887567bb62a3df0879505d68ac6a2be725b57173")
        self.assertEqual(auth["observedCiRunId"], 37645554562)
        self.assertEqual(auth["commitClass"], "TASK_POINTER_ONLY")
        self.assertEqual(auth["changedFiles"], ["TASKS/R39_MEDIA_QA_BIND.md"])
        self.assertFalse(auth["successorArtifactPresent"])
        self.assertFalse(auth["acceptedForRealReview"])

    def test_bridge_r44_exact_source_is_green_but_not_live_accepted(self):
        auth = reels.authority_observation()["bridgeR44"]
        self.assertEqual(auth["producerSha"], "9a8898a70355bbae2d465ee49739030aa27e9f4e")
        self.assertEqual(auth["ciRunId"], 37726498161)
        self.assertEqual(auth["readiness"], "EXACT_HEAD_READY_FOR_NEW_LOCAL_PREFLIGHT")
        self.assertEqual(auth["ubuntuArtifact"]["id"], 11527694819)
        self.assertEqual(auth["windowsArtifact"]["id"], 11527109716)
        self.assertTrue(auth["sourceGreen"])
        self.assertFalse(auth["localPreflightCutoverAccepted"])
        self.assertFalse(auth["providerMutationAuthorized"])

    def test_boss_r9_has_no_go(self):
        auth = reels.authority_observation()["bossR9"]
        self.assertEqual(auth["observedSha"], "9f439b41c2b11640451a803cee8b8d6198ddd04b")
        self.assertEqual(auth["commitClass"], "TASK_POINTER_ONLY")
        self.assertIsNone(auth["ciRunId"])
        self.assertIsNone(auth["goDisposition"])
        self.assertFalse(auth["acceptedGo"])


class GrowthAuthorityTests(unittest.TestCase):
    def test_fixture_growth_rejected_in_real_mode(self):
        with self.assertRaises(reels.AuthorityBlocked):
            reels.validate_growth_authority(reels.fixture_growth_authority())

    def test_fixture_growth_accepted_only_explicit_fixture_mode(self):
        value = reels.validate_growth_authority(reels.fixture_growth_authority(), allow_fixture=True)
        self.assertTrue(value["sourceReadyForRealBundle"])
        self.assertTrue(value["fixtureOnly"])

    def test_current_task_pointer_cannot_form_real_authority(self):
        value = reels.fixture_growth_authority()
        value["producerSha"] = reels.GROWTH_R39_TASK_SHA
        value["fixtureOnly"] = False
        value["artifactId"] = 0
        with self.assertRaises(reels.ReelsLocalError):
            reels.validate_growth_authority(value)

    def test_task_pointer_rejected_even_with_plausible_ci_artifact_fields(self):
        value = reels.fixture_growth_authority()
        value["producerSha"] = reels.GROWTH_R39_TASK_SHA
        value["fixtureOnly"] = False
        value["artifactId"] = 12999999040
        with self.assertRaises(reels.AuthorityBlocked):
            reels.validate_growth_authority(value)


class MediaBundleTests(unittest.TestCase):
    def _make_bundle(self, root: Path):
        source = root / "input.mp4"
        source.write_bytes(b"real-ish-input-bytes")
        output = root / "media-r27"
        candidates = []
        files = []
        for n in range(1, 5):
            cid = f"candidate-{n}"
            p = output / "growth" / "payload" / "candidates" / cid / "final.mp4"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"candidate-{n}-rendered".encode())
            rec = reels.file_record(p)
            candidates.append({"candidateId": cid, **rec})
            files.append({"path": f"candidates/{cid}/final.mp4", **rec})
        final = output / "final" / "final.mp4"
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"producer-targeted-final")
        final_rec = reels.file_record(final)
        bundle = {
            "contractVersion": reels.MEDIA_BUNDLE_CONTRACT,
            "mediaContractId": reels.MEDIA_CONTRACT,
            "producer": {
                "repository": "foto6/video2",
                "sha": reels.MEDIA_SHA,
                "authorityState": "PENDING_INDEPENDENT_QA",
                "acceptedByIndependentQa": False,
            },
            "operationBindingDigest": "1" * 64,
            "inputVideo": {**reels.file_record(source), "pathIdentity": "2" * 64},
            "normalizedSource": {"sha256": "3" * 64, "size": 10, "normalizationSpecDigest": "4" * 64},
            "candidates": candidates,
            "targetedReedit": {
                "candidateId": "targeted",
                "sha256": final_rec["sha256"],
                "size": final_rec["size"],
                "decisionClass": "DETERMINISTIC_OFFLINE_FIXTURE_TARGETED_REEDIT",
            },
            "finalArtifact": final_rec,
            "files": files,
            "evidenceBoundary": {
                "realInputBytes": True,
                "realEncodedMp4": True,
                "fixtureReviewDecision": True,
                "liveModelReview": False,
                "providerMutation": False,
                "browserMutation": False,
                "socialPublish": False,
                "liveAuthorization": False,
            },
        }
        bundle["manifestDigest"] = reels.sha256_json(bundle)
        manifest = output / "growth" / "media.real_input_growth_bundle.r27.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(bundle), encoding="utf-8")
        return source, output, bundle

    def test_four_distinct_candidate_files_are_verified(self):
        with tempfile.TemporaryDirectory() as td:
            source, output, bundle = self._make_bundle(Path(td))
            parsed = reels.verify_media_output(source=source, output_root=output)
            self.assertEqual(parsed["manifestDigest"], bundle["manifestDigest"])
            self.assertEqual(len({row["sha256"] for row in parsed["candidates"]}), 4)

    def test_candidate_byte_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source, output, _ = self._make_bundle(Path(td))
            p = output / "growth" / "payload" / "candidates" / "candidate-2" / "final.mp4"
            p.write_bytes(b"tampered")
            with self.assertRaises(reels.MediaEvidenceError):
                reels.verify_media_output(source=source, output_root=output)

    def test_source_byte_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source, output, _ = self._make_bundle(Path(td))
            source.write_bytes(b"changed-input")
            with self.assertRaises(reels.MediaEvidenceError):
                reels.verify_media_output(source=source, output_root=output)

    def test_live_effect_claim_in_media_bundle_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source, output, bundle = self._make_bundle(Path(td))
            bundle["evidenceBoundary"]["socialPublish"] = True
            material = copy.deepcopy(bundle)
            material.pop("manifestDigest", None)
            bundle["manifestDigest"] = reels.sha256_json(material)
            (output / "growth" / "media.real_input_growth_bundle.r27.manifest.json").write_text(
                json.dumps(bundle), encoding="utf-8"
            )
            with self.assertRaises(reels.MediaEvidenceError):
                reels.verify_media_output(source=source, output_root=output)


class ReviewTests(unittest.TestCase):
    def _available(self):
        return {
            "candidate-1": {"candidateId": "candidate-1", "sha256": "1" * 64, "size": 10, "path": Path("a")},
            "reedit-1": {"candidateId": "reedit-1", "sha256": "2" * 64, "size": 11, "path": Path("b")},
        }

    def _review(self, round_number, candidate_id, sha, decision):
        growth = reels.fixture_growth_authority()
        value = {
            "contractVersion": reels.REVIEW_VERSION,
            "evidenceClass": "FIXTURE_REVIEW",
            "fixtureOnly": True,
            "growthProducerSha": growth["producerSha"],
            "growthArtifactDigest": growth["artifactDigest"],
            "mediaBundleDigest": "a" * 64,
            "reviewRound": round_number,
            "decision": decision,
            "selectedCandidateId": candidate_id,
            "selectedSha256": sha,
            "qualityScores": {"hook": 0.8},
            "directives": [],
            "reeditRequest": None,
            "providerMutation": False,
            "livePublish": False,
            "reviewDigest": "",
        }
        if decision == "REEDIT":
            value["reeditRequest"] = {
                "contractVersion": "media.editorial_reedit_request.r19.v1",
                "requestId": f"r{round_number}",
            }
        value["reviewDigest"] = reels.sha256_json({**value, "reviewDigest": ""})
        return growth, value

    def test_round_zero_reedit_is_accepted_in_fixture_mode(self):
        growth, value = self._review(0, "candidate-1", "1" * 64, "REEDIT")
        parsed = reels.validate_review(
            value, growth_authority=growth, media_bundle_digest="a" * 64,
            round_number=0, available=self._available(), allow_fixture=True,
        )
        self.assertEqual(parsed["decision"], "REEDIT")

    def test_third_reedit_is_forbidden(self):
        growth, value = self._review(2, "reedit-1", "2" * 64, "REEDIT")
        with self.assertRaises(reels.ReeditLimitReached):
            reels.validate_review(
                value, growth_authority=growth, media_bundle_digest="a" * 64,
                round_number=2, available=self._available(), allow_fixture=True,
            )

    def test_review_selection_hash_must_match_available_bytes(self):
        growth, value = self._review(0, "candidate-1", "0" * 64, "WINNER")
        with self.assertRaises(reels.ReviewError):
            reels.validate_review(
                value, growth_authority=growth, media_bundle_digest="a" * 64,
                round_number=0, available=self._available(), allow_fixture=True,
            )

    def test_fixture_review_rejected_in_real_mode(self):
        growth, value = self._review(0, "candidate-1", "1" * 64, "WINNER")
        with self.assertRaises(reels.ReviewError):
            reels.validate_review(
                value, growth_authority=growth, media_bundle_digest="a" * 64,
                round_number=0, available=self._available(), allow_fixture=False,
            )


class LedgerTests(unittest.TestCase):
    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity = {"source": "a", "authority": "b"}
            ledger = reels.StageLedger(root, identity=identity)
            _, reused1 = ledger.append(
                key="x", event_type="TEST", request={"a": 1}, evidence={"b": 2}
            )
            digest = ledger.digest
            ledger2 = reels.StageLedger(root, identity=identity)
            _, reused2 = ledger2.append(
                key="x", event_type="TEST", request={"a": 1}, evidence={"b": 2}
            )
            self.assertFalse(reused1)
            self.assertTrue(reused2)
            self.assertEqual(digest, ledger2.digest)

    def test_changed_identity_same_workspace_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reels.StageLedger(root, identity={"source": "a"})
            with self.assertRaises(reels.ReplayConflict):
                reels.StageLedger(root, identity={"source": "b"})

    def test_changed_event_request_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = reels.StageLedger(root, identity={"source": "a"})
            ledger.append(key="x", event_type="TEST", request={"a": 1}, evidence={"b": 2})
            with self.assertRaises(reels.ReplayConflict):
                ledger.append(key="x", event_type="TEST", request={"a": 2}, evidence={"b": 2})


class EscrowPublishTests(unittest.TestCase):
    def _fixture(self, root):
        source = {"sha256": "1" * 64, "size": 100}
        final = {"sha256": "2" * 64, "size": 90, "path": "final/final.mp4"}
        ledger = reels.StageLedger(root, identity={"fixture": True})
        review = {
            "decision": "WINNER",
            "reviewDigest": "3" * 64,
        }
        escrow = reels.release_escrow(
            workspace=root,
            source=source,
            final=final,
            media_bundle_digest="4" * 64,
            review_chain=[review],
            authority_digest="5" * 64,
            ledger=ledger,
        )
        return source, final, escrow

    def test_release_escrow_never_authorizes_publish(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, escrow = self._fixture(Path(td))
            self.assertTrue(escrow["humanReviewRequiredBeforeSend"])
            self.assertTrue(escrow["bossR9GoRequiredBeforeSend"])
            self.assertFalse(escrow["liveAuthorization"])
            self.assertFalse(escrow["publishAllowed"])
            self.assertFalse(escrow["providerMutation"])

    def test_publish_readiness_is_transactional_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            _, final, escrow = self._fixture(Path(td))
            a = reels.publish_readiness(
                final=final, escrow=escrow, platform="instagram_reels",
                account_ref="acct", destination="profile:acct", caption="hello", title="title"
            )
            b = reels.publish_readiness(
                final=final, escrow=escrow, platform="instagram_reels",
                account_ref="acct", destination="profile:acct", caption="hello", title="title"
            )
            self.assertEqual(a["transactionId"], b["transactionId"])
            self.assertEqual(a["idempotencyKey"], b["idempotencyKey"])
            self.assertFalse(a["sendCommandImplemented"])
            self.assertFalse(a["sendPermitted"])
            self.assertFalse(a["blindRetryPermitted"])
            self.assertTrue(a["readOnlyReconciliationOnlyAfterUnknownOutcome"])
            self.assertFalse(a["networkPermitted"])
            self.assertFalse(a["livePublish"])

    def test_boss_go_rejects_wrong_bridge_tuple_before_any_send(self):
        growth = reels.fixture_growth_authority()
        boss = reels.fixture_boss_go(growth["producerSha"])
        boss["fixtureOnly"] = False
        boss["bridgeProducerSha"] = "0" * 40
        with self.assertRaises(reels.PublishGateError):
            reels.validate_boss_go(boss, allow_fixture=False)

    def test_publish_identity_changes_when_final_changes(self):
        with tempfile.TemporaryDirectory() as td:
            _, final, escrow = self._fixture(Path(td))
            a = reels.publish_readiness(
                final=final, escrow=escrow, platform="instagram_reels",
                account_ref="acct", destination="profile:acct", caption="hello", title="title"
            )
            changed = dict(final)
            changed["sha256"] = "9" * 64
            b = reels.publish_readiness(
                final=changed, escrow=escrow, platform="instagram_reels",
                account_ref="acct", destination="profile:acct", caption="hello", title="title"
            )
            self.assertNotEqual(a["transactionId"], b["transactionId"])


class FixtureTests(unittest.TestCase):
    def test_fixture_exercises_four_candidates_and_two_reedits(self):
        with tempfile.TemporaryDirectory() as td:
            value = reels.run_fixture(td)
            self.assertEqual(value["state"], "FIXTURE_LOOP_COMPLETE")
            self.assertEqual(value["candidateCount"], 4)
            self.assertEqual(len(set(value["candidateHashes"])), 4)
            self.assertEqual(value["reviewRounds"], 3)
            self.assertEqual(value["reeditRounds"], 2)
            self.assertFalse(value["actualLocalPcE2EExecuted"])
            self.assertTrue(value["fixtureOnly"])
            self.assertFalse(value["sendPermitted"])
            self.assertFalse(value["livePublish"])

    def test_fixture_exact_replay_is_stable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = reels.run_fixture(root)
            first = (root / "evidence" / "fixture-autonomous-reels.r40.json").read_bytes()
            b = reels.run_fixture(root)
            self.assertEqual(a["fixtureDigest"], b["fixtureDigest"])
            self.assertEqual(first, (root / "evidence" / "fixture-autonomous-reels.r40.json").read_bytes())

    def test_fixture_publish_readiness_has_no_send_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reels.run_fixture(root)
            value = json.loads((root / "evidence" / "publish-readiness.r40.json").read_text())
            self.assertEqual(value["state"], "PREPARED_HUMAN_BOSS_GATE")
            self.assertFalse(value["allExternalGatesSatisfied"])
            self.assertFalse(value["sendCommandImplemented"])
            self.assertFalse(value["sendPermitted"])
            self.assertFalse(value["networkPermitted"])


class CliTests(unittest.TestCase):
    def test_diagnose_returns_blocked_code_without_side_effect(self):
        self.assertEqual(reels.main(["diagnose"]), 4)

    def test_fixture_cli_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(reels.main(["fixture", "--workspace", td]), 0)


class AdversarialAuthorityTests(unittest.TestCase):
    pass


def _growth_mutation_test(field, value):
    def test(self):
        auth = reels.fixture_growth_authority()
        auth["fixtureOnly"] = False
        auth[field] = value
        with self.assertRaises(reels.ReelsLocalError):
            reels.validate_growth_authority(auth)
    return test


_GROWTH_MUTATIONS = {
    "repository": "other/repo",
    "taskAnchorSha": "0" * 40,
    "producerSha": "bad",
    "ciRunId": 0,
    "ciConclusion": "failure",
    "artifactId": 0,
    "artifactDigest": "bad",
    "growthContract": "growth.other.v1",
    "mediaQaCertificateDigest": "0" * 64,
    "sourceReadyForRealBundle": False,
}
for _field, _value in _GROWTH_MUTATIONS.items():
    setattr(
        AdversarialAuthorityTests,
        "test_growth_mutation_" + _field,
        _growth_mutation_test(_field, _value),
    )


class AdversarialReviewTests(unittest.TestCase):
    pass


def _review_mutation_test(field, value):
    def test(self):
        growth = reels.fixture_growth_authority()
        review = reels._fixture_review(
            growth=growth,
            bundle_digest="a" * 64,
            round_number=0,
            selected_id="candidate-1",
            selected_sha="1" * 64,
            decision="WINNER",
        )
        review[field] = value
        if field != "reviewDigest":
            review["reviewDigest"] = reels.sha256_json({**review, "reviewDigest": ""})
        with self.assertRaises(reels.ReelsLocalError):
            reels.validate_review(
                review,
                growth_authority=growth,
                media_bundle_digest="a" * 64,
                round_number=0,
                available={"candidate-1": {"candidateId": "candidate-1", "sha256": "1" * 64, "size": 1, "path": Path("x")}},
                allow_fixture=True,
            )
    return test


_REVIEW_MUTATIONS = {
    "contractVersion": "creator.other.v1",
    "growthProducerSha": "0" * 40,
    "growthArtifactDigest": "sha256:" + "0" * 64,
    "mediaBundleDigest": "0" * 64,
    "reviewRound": 1,
    "decision": "PUBLISH",
    "selectedCandidateId": "missing",
    "selectedSha256": "0" * 64,
    "providerMutation": True,
    "livePublish": True,
    "reviewDigest": "0" * 64,
}
for _field, _value in _REVIEW_MUTATIONS.items():
    setattr(
        AdversarialReviewTests,
        "test_review_mutation_" + _field,
        _review_mutation_test(_field, _value),
    )


if __name__ == "__main__":
    unittest.main()
