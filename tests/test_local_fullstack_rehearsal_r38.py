from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import local_fullstack_rehearsal_r38 as r38


class R38AuthorityTests(unittest.TestCase):
    def test_readiness_waits_for_media(self):
        value = r38.readiness()
        self.assertEqual(value["state"], "WAITING_MEDIA_AUTHORITY")
        self.assertTrue(value["mediaRequired"])
        self.assertFalse(value["mediaAccepted"])
        self.assertFalse(value["liveAuthorization"])
        self.assertFalse(value["publishAllowed"])

    def test_exact_parent_authorities(self):
        value = r38.readiness()
        self.assertEqual(value["creatorR37"]["producerSha"], "1f7cb9ed8f1985cd4faca79ce55f1c5fda9e3a57")
        self.assertEqual(value["creatorR37"]["ciRunId"], 37398299900)
        self.assertEqual(value["growthR36"]["producerSha"], "a53f9deb180bb256d193f0422c6ffd7a5923d97a")
        self.assertEqual(value["growthR36"]["ciRunId"], 37398558145)
        self.assertEqual(value["growthR36"]["artifactId"], 11383953328)
        self.assertEqual(value["bridgeR40"]["producerSha"], "9fca5e7e4cdc820a1a3aee6ada9102fc97649d16")
        self.assertEqual(value["bridgeR40"]["ciRunId"], 37399009019)

    def test_fixture_media_never_authorizes_real_run(self):
        media = r38.fixture_media_authority()
        with self.assertRaises(r38.MediaAuthorityRequired):
            r38.validate_media_authority(media)
        self.assertEqual(r38.validate_media_authority(media, allow_fixture=True)["milestone"], "R26")

    def test_old_r25_contract_forbidden(self):
        media = r38.fixture_media_authority()
        media["contract"] = "media.multicandidate_round.r25.v1"
        media["independentQa"]["acceptedMediaContract"] = media["contract"]
        with self.assertRaises(r38.MediaAuthorityRequired):
            r38.validate_media_authority(media, allow_fixture=True)

    def test_media_qa_must_bind_exact_tuple(self):
        media = r38.fixture_media_authority()
        media["independentQa"]["acceptedMediaProducerSha"] = "9" * 40
        with self.assertRaises(r38.MediaAuthorityRequired):
            r38.validate_media_authority(media, allow_fixture=True)

    def test_media_runner_must_be_offline(self):
        media = r38.fixture_media_authority()
        media["localRunner"]["networkAllowed"] = True
        with self.assertRaises(r38.MediaAuthorityRequired):
            r38.validate_media_authority(media, allow_fixture=True)

    def test_media_runner_cannot_require_cuda(self):
        media = r38.fixture_media_authority()
        media["localRunner"]["cudaRequired"] = True
        with self.assertRaises(r38.MediaAuthorityRequired):
            r38.validate_media_authority(media, allow_fixture=True)

    def test_media_runner_path_cannot_escape(self):
        media = r38.fixture_media_authority()
        media["localRunner"]["relativePath"] = "../escape.cmd"
        with self.assertRaises(r38.MediaAuthorityRequired):
            r38.validate_media_authority(media, allow_fixture=True)


class R38ResourceTests(unittest.TestCase):
    def test_resource_defaults_do_not_assume_cuda(self):
        value = r38.resource_declaration()
        self.assertEqual(value["gpuMode"], "none")
        self.assertFalse(value["cudaAssumed"])
        self.assertFalse(value["cudaRequired"])
        self.assertFalse(value["heavyHostedCiRenderAllowed"])

    def test_invalid_cpu_rejected(self):
        with self.assertRaises(r38.R38Error):
            r38.resource_declaration(cpu_workers=0)

    def test_invalid_disk_rejected(self):
        with self.assertRaises(r38.R38Error):
            r38.resource_declaration(disk_budget_mb=64)

    def test_temp_path_escape_rejected(self):
        with self.assertRaises(r38.R38Error):
            r38.resource_declaration(temp_root="../temp")


class R38FixturePipelineTests(unittest.TestCase):
    def test_tiny_fixture_full_loop_and_sealed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = r38.run_tiny_fixture(root)
            self.assertEqual(status["state"], "LOCAL_REHEARSAL_COMPLETE")
            manifest = json.loads((root / "evidence" / "final-rehearsal-manifest.r38.json").read_text())
            self.assertEqual(len(manifest["candidates"]), 3)
            self.assertEqual(manifest["selectedWinner"]["sha256"], manifest["targetedReedit"]["sha256"])
            self.assertEqual(manifest["finalMp4"]["sha256"], manifest["targetedReedit"]["sha256"])
            self.assertEqual(manifest["authorities"]["creatorR37"]["producerSha"], r38.CREATOR_R37["producerSha"])
            self.assertEqual(manifest["authorities"]["growthR36"]["producerSha"], r38.GROWTH_R36["producerSha"])
            self.assertEqual(manifest["authorities"]["bridgeR40"]["producerSha"], r38.BRIDGE_R40["producerSha"])
            self.assertFalse(manifest["liveAuthorization"])
            self.assertFalse(manifest["publishAllowed"])
            self.assertEqual(manifest["networkEffects"], 0)

    def test_exact_rerun_reuses_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = r38.run_tiny_fixture(root)
            ledger = root / "ledger" / "stage-ledger.r38.jsonl"
            count = len(ledger.read_text().splitlines())
            second = r38.run_tiny_fixture(root)
            self.assertEqual(first["manifestDigest"], second["manifestDigest"])
            self.assertEqual(len(ledger.read_text().splitlines()), count)
            manifest = json.loads((root / second["manifestPath"]).read_text())
            self.assertTrue(manifest["stageReuse"]["exactRerunSupported"])

    def test_changed_source_same_workspace_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            (root / "fixture-source.mp4").write_bytes(b"changed")
            with self.assertRaises(r38.ReplayConflict):
                r38.run_tiny_fixture(root)

    def test_completed_artifact_hash_drift_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            (root / "candidates" / "candidate-01.mp4").write_bytes(b"tamper")
            with self.assertRaises(r38.ReplayConflict):
                r38.run_tiny_fixture(root)

    def test_ledger_has_started_and_completed_for_expensive_steps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            rows = [json.loads(x) for x in (root / "ledger" / "stage-ledger.r38.jsonl").read_text().splitlines()]
            keys = {row["eventKey"] for row in rows}
            for stage in ("MEDIA_CANDIDATES", "REVIEW_PACKAGE", "GROWTH_DECISION", "TARGETED_REEDIT", "FINALIZE"):
                self.assertIn(stage + ":STARTED", keys)
                self.assertIn(stage + ":COMPLETED", keys)

    def test_offline_review_fixture_has_no_network_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            review = json.loads((root / "review" / "review-package.r38.json").read_text())
            self.assertEqual(review["source"]["mode"], "OFFLINE_FAKE_REVIEW")
            self.assertFalse(review["source"]["exactLiveReviewSupplied"])
            self.assertEqual(review["networkEffects"], 0)
            self.assertFalse(review["liveAuthorization"])

    def test_growth_decision_is_local_advisory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            decision = json.loads((root / "growth" / "growth-decision.r38.json").read_text())
            self.assertEqual(decision["contractVersion"], "growth.local_offline_decision.r36.v1")
            self.assertEqual(decision["growthAuthoritySha"], r38.GROWTH_R36["producerSha"])
            self.assertEqual(decision["decisionMode"], "LOCAL_ADVISORY_ONLY")
            self.assertFalse(decision["publishAllowed"])

    def test_final_manifest_hash_is_self_consistent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            manifest = json.loads((root / "evidence" / "final-rehearsal-manifest.r38.json").read_text())
            digest = manifest.pop("manifestDigest")
            self.assertEqual(digest, r38.sha256_json(manifest))

    def test_status_verifies_manifest_before_return(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            status = r38.status(root)
            self.assertEqual(status["state"], "LOCAL_REHEARSAL_COMPLETE")
            manifest_path = root / status["manifestPath"]
            body = json.loads(manifest_path.read_text())
            body["networkEffects"] = 1
            manifest_path.write_text(json.dumps(body))
            with self.assertRaises(r38.ReplayConflict):
                r38.status(root)

    def test_cleanup_preserves_final_and_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r38.run_tiny_fixture(root)
            temp = root / "temp"
            temp.mkdir(exist_ok=True)
            (temp / "scratch.bin").write_bytes(b"x")
            result = r38.cleanup(root)
            self.assertFalse(temp.exists())
            self.assertTrue((root / "final" / "final.mp4").is_file())
            self.assertTrue((root / "evidence" / "final-rehearsal-manifest.r38.json").is_file())
            self.assertFalse(result["sourceMaterialDeleted"])
            self.assertFalse(result["acceptedEvidenceDeleted"])

    def test_workspace_layout_is_deterministic(self):
        self.assertEqual(r38.workspace_layout(), r38.workspace_layout())
        self.assertEqual(r38.workspace_layout()["finalVideo"], "final/final.mp4")


class R38DryRunTests(unittest.TestCase):
    def test_dry_run_waits_without_media(self):
        with tempfile.TemporaryDirectory() as td:
            value = r38.dry_run(source_path=None, workspace=td, media=None, resources=r38.resource_declaration())
            self.assertEqual(value["state"], "WAITING_MEDIA_AUTHORITY")
            self.assertFalse(value["networkRequired"])
            self.assertFalse(value["credentialsRequired"])
            self.assertFalse(value["cudaAssumed"])
            self.assertFalse(value["liveBridgeCutover"])

    def test_cli_readiness_missing_media_returns_three(self):
        self.assertEqual(r38.main(["readiness"]), 3)

    def test_cli_fixture_rehearsal_is_tiny(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(r38.main(["fixture-rehearsal", "--workspace", td]), 0)
            self.assertLess((Path(td) / "final" / "final.mp4").stat().st_size, 4096)


class R38AdversarialMediaCases(unittest.TestCase):
    def test_media_gate_mutations(self):
        mutations = {
            "wrong_repo": lambda m: m.__setitem__("repository", "other/repo"),
            "wrong_milestone": lambda m: m.__setitem__("milestone", "R25"),
            "unaccepted": lambda m: m.__setitem__("status", "UNACCEPTED"),
            "ci_failure": lambda m: m.__setitem__("ciConclusion", "failure"),
            "bad_sha": lambda m: m.__setitem__("producerSha", "0"),
            "bad_artifact_digest": lambda m: m.__setitem__("artifactDigest", "bad"),
            "runner_protocol": lambda m: m["localRunner"].__setitem__("protocol", "bad"),
            "runner_response": lambda m: m["localRunner"].__setitem__("responseContract", "bad"),
            "runner_network": lambda m: m["localRunner"].__setitem__("networkAllowed", True),
            "runner_credentials": lambda m: m["localRunner"].__setitem__("credentialsRequired", True),
            "qa_disposition": lambda m: m["independentQa"].__setitem__("disposition", "PENDING"),
            "qa_ci": lambda m: m["independentQa"].__setitem__("ciConclusion", "failure"),
            "qa_sha_binding": lambda m: m["independentQa"].__setitem__("acceptedMediaProducerSha", "9" * 40),
            "qa_ci_binding": lambda m: m["independentQa"].__setitem__("acceptedMediaCiRunId", 1),
            "qa_artifact_binding": lambda m: m["independentQa"].__setitem__("acceptedMediaArtifactId", 1),
            "qa_digest_binding": lambda m: m["independentQa"].__setitem__("acceptedMediaArtifactDigest", "sha256:" + "9" * 64),
            "qa_contract_binding": lambda m: m["independentQa"].__setitem__("acceptedMediaContract", "media.other.r26.v1"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                media = r38.fixture_media_authority()
                mutate(media)
                with self.assertRaises(r38.AuthorityError):
                    r38.validate_media_authority(media, allow_fixture=True)


if __name__ == "__main__":
    unittest.main()
