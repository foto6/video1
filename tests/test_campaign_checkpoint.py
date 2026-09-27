from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.checkpoint import (
    CAMPAIGN_CHECKPOINT_VERSION,
    CampaignCheckpointConflictError,
    CampaignCheckpointIntegrityError,
    CampaignCheckpointSecretError,
    CampaignCheckpointVersionError,
    canonical_json,
    compute_checkpoint_hash,
    export_campaign_checkpoint,
    import_campaign_checkpoint,
    load_campaign_checkpoint,
    resume_campaign_from_checkpoint,
    validate_campaign_checkpoint,
    validate_producer_pins,
)
from creator_orchestrator.external_ops import OperationBoundaryCrash, OperationState
from creator_orchestrator.growth_seed import JsonGrowthSeedLedger
from creator_orchestrator.integration import SeedArtifactInput
from creator_orchestrator.media_job_v1 import MediaJobV1ResumableAdapter
from creator_orchestrator.models import JobStage, STAGE_ORDER
from creator_orchestrator.orchestrator import JsonJobStore, Orchestrator
from creator_orchestrator.sim_fakes import FakeMediaJobV1Client
from creator_orchestrator.simulator import (
    CampaignRunner,
    CampaignState,
    JsonCampaignStore,
    load_campaign_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "fixtures" / "campaign.checkpoint.v1.source.json"
CHECKPOINT_DIR = ROOT / "fixtures" / "checkpoints"
GROWTH_FIXTURE = (
    ROOT / "fixtures" / "upstream" / "growth" / "creator_next_cycle_seed_v1.json"
)
MEDIA_FIXTURE = (
    ROOT / "fixtures" / "upstream" / "media" / "media.job.v1.consumer.json"
)

BOUNDARY_FILES = [
    "00_created.checkpoint.json",
    "01_research.checkpoint.json",
    "02_idea.checkpoint.json",
    "03_script.checkpoint.json",
    "04_assets.checkpoint.json",
    "05_voice.checkpoint.json",
    "06_edit.checkpoint.json",
    "07_critic.checkpoint.json",
    "08_publish_queue.checkpoint.json",
    "09_analytics.checkpoint.json",
    "10_terminal.checkpoint.json",
]


class CrashOnce:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.triggered = False

    def __call__(self, name, _receipt) -> None:
        if name == self.boundary and not self.triggered:
            self.triggered = True
            raise OperationBoundaryCrash(name)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rehash(bundle):
    bundle["checkpointHash"] = compute_checkpoint_hash(bundle)
    return bundle


class CampaignCheckpointTests(unittest.TestCase):
    def test_fixture_bundle_covers_every_stage_boundary_and_terminal(self):
        self.assertEqual(
            sorted(path.name for path in CHECKPOINT_DIR.glob("*.checkpoint.json")),
            BOUNDARY_FILES,
        )
        expected_stage_indices = list(range(10)) + [9]
        for filename, expected_stage_index in zip(
            BOUNDARY_FILES,
            expected_stage_indices,
        ):
            with self.subTest(filename=filename):
                bundle = load_campaign_checkpoint(
                    CHECKPOINT_DIR / filename,
                    repo_root=ROOT,
                )
                self.assertEqual(
                    bundle["checkpointVersion"],
                    CAMPAIGN_CHECKPOINT_VERSION,
                )
                self.assertTrue(bundle["checkpointHash"].startswith("sha256:"))
                self.assertEqual(len(bundle["jobs"]), 1)
                self.assertEqual(
                    bundle["jobs"][0]["stageIndex"],
                    expected_stage_index,
                )
                if filename == "10_terminal.checkpoint.json":
                    self.assertEqual(bundle["campaignState"]["status"], "complete")
                    self.assertIsNotNone(
                        bundle["campaignState"]["report_artifact"]
                    )
                else:
                    self.assertEqual(bundle["campaignState"]["status"], "running")

    def test_round_trip_every_boundary_reaches_same_canonical_final_lineage(self):
        terminal = load_campaign_checkpoint(
            CHECKPOINT_DIR / "10_terminal.checkpoint.json",
            repo_root=ROOT,
        )
        expected_lineage_hash = terminal["integrity"]["artifactLineageHash"]
        expected_checkpoint_hash = terminal["checkpointHash"]
        for filename in BOUNDARY_FILES:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as td:
                source = load_campaign_checkpoint(
                    CHECKPOINT_DIR / filename,
                    repo_root=ROOT,
                )
                runner, imported = resume_campaign_from_checkpoint(
                    source,
                    td,
                    repo_root=ROOT,
                )
                self.assertEqual(imported.status, "imported")
                runner.run_to_terminal()
                final = export_campaign_checkpoint(
                    td,
                    campaign_id=runner.config.campaign_id,
                    campaign_config=runner.config.raw,
                    repo_root=ROOT,
                )
                self.assertEqual(
                    final["integrity"]["artifactLineageHash"],
                    expected_lineage_hash,
                )
                self.assertEqual(final["checkpointHash"], expected_checkpoint_hash)

    def test_import_same_checkpoint_is_idempotent(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "04_assets.checkpoint.json",
            repo_root=ROOT,
        )
        with tempfile.TemporaryDirectory() as td:
            first = import_campaign_checkpoint(bundle, td, repo_root=ROOT)
            second = import_campaign_checkpoint(bundle, td, repo_root=ROOT)
            self.assertEqual(first.status, "imported")
            self.assertEqual(second.status, "duplicate")
            self.assertEqual(first.checkpoint_hash, second.checkpoint_hash)

    def test_conflicting_existing_campaign_identity_fails_closed(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "02_idea.checkpoint.json",
            repo_root=ROOT,
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            campaign_path = (
                root
                / "campaigns"
                / f"{bundle['campaignIdentity']['campaignId']}.json"
            )
            campaign_path.parent.mkdir(parents=True)
            conflicting = copy.deepcopy(bundle["campaignState"])
            conflicting["config_digest"] = "conflicting-config"
            campaign_path.write_text(
                json.dumps(conflicting),
                encoding="utf-8",
            )
            with self.assertRaises(CampaignCheckpointConflictError):
                import_campaign_checkpoint(bundle, td, repo_root=ROOT)

    def test_unknown_future_checkpoint_version_is_rejected_without_migration(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "01_research.checkpoint.json",
            repo_root=ROOT,
        )
        future = copy.deepcopy(bundle)
        future["checkpointVersion"] = "creator.campaign_checkpoint.v2"
        rehash(future)
        with self.assertRaises(CampaignCheckpointVersionError):
            validate_campaign_checkpoint(future, repo_root=ROOT)

    def test_tamper_missing_artifact_is_rejected_even_with_recomputed_bundle_hash(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "08_publish_queue.checkpoint.json",
            repo_root=ROOT,
        )
        tampered = copy.deepcopy(bundle)
        tampered["artifactLineage"].pop()
        rehash(tampered)
        with self.assertRaises(CampaignCheckpointIntegrityError):
            validate_campaign_checkpoint(tampered, repo_root=ROOT)

    def test_tamper_altered_digest_is_rejected_even_with_recomputed_bundle_hash(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "08_publish_queue.checkpoint.json",
            repo_root=ROOT,
        )
        tampered = copy.deepcopy(bundle)
        tampered["integrity"]["artifactLineageHash"] = "sha256:" + ("0" * 64)
        rehash(tampered)
        with self.assertRaises(CampaignCheckpointIntegrityError):
            validate_campaign_checkpoint(tampered, repo_root=ROOT)

    def test_tamper_reordered_records_is_rejected_even_with_recomputed_bundle_hash(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "05_voice.checkpoint.json",
            repo_root=ROOT,
        )
        tampered = copy.deepcopy(bundle)
        tampered["stageRecords"] = list(reversed(tampered["stageRecords"]))
        rehash(tampered)
        with self.assertRaises(CampaignCheckpointIntegrityError):
            validate_campaign_checkpoint(tampered, repo_root=ROOT)

    def test_tamper_conflicting_job_identity_fails_closed(self):
        bundle = load_campaign_checkpoint(
            CHECKPOINT_DIR / "03_script.checkpoint.json",
            repo_root=ROOT,
        )
        tampered = copy.deepcopy(bundle)
        tampered["campaignState"]["cycle_job_ids"]["1"] = "different-job"
        rehash(tampered)
        with self.assertRaises(CampaignCheckpointConflictError):
            validate_campaign_checkpoint(tampered, repo_root=ROOT)

    def test_growth_seed_identity_conflict_is_detected(self):
        config = load_campaign_fixture(SOURCE_CONFIG)
        growth_payload = load_json(GROWTH_FIXTURE)
        with tempfile.TemporaryDirectory() as td:
            runner = CampaignRunner(td, config)
            runner.initialize()
            runner.step()
            JsonGrowthSeedLedger(Path(td) / "growth-seeds.jsonl").consume(
                growth_payload,
                artifact_created_at="2026-09-27T00:00:01+00:00",
            )
            bundle = export_campaign_checkpoint(
                td,
                campaign_id=config.campaign_id,
                campaign_config=config.raw,
                repo_root=ROOT,
            )
            self.assertEqual(len(bundle["growthSeedIdentities"]), 1)
            tampered = copy.deepcopy(bundle)
            tampered["growthSeedIdentities"][0]["artifactId"] = "conflicting-seed"
            rehash(tampered)
            with self.assertRaises(CampaignCheckpointConflictError):
                validate_campaign_checkpoint(tampered, repo_root=ROOT)

    def test_export_fails_closed_on_secret_like_provider_state(self):
        config = load_campaign_fixture(SOURCE_CONFIG)
        with tempfile.TemporaryDirectory() as td:
            runner = CampaignRunner(td, config)
            runner.initialize()
            runner.step()
            job_path = Path(td) / "jobs" / "checkpoint-repro-cycle-01.json"
            raw = load_json(job_path)
            raw["artifacts"][0]["metadata"]["api_key"] = "must-not-export"
            job_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CampaignCheckpointSecretError):
                export_campaign_checkpoint(
                    td,
                    campaign_id=config.campaign_id,
                    campaign_config=config.raw,
                    repo_root=ROOT,
                )

    def test_secret_filter_still_rejects_authorization_header(self):
        config = load_campaign_fixture(SOURCE_CONFIG)
        with tempfile.TemporaryDirectory() as td:
            runner = CampaignRunner(td, config)
            runner.initialize()
            runner.step()
            job_path = Path(td) / "jobs" / "checkpoint-repro-cycle-01.json"
            raw = load_json(job_path)
            raw["artifacts"][0]["metadata"]["Authorization"] = "Bearer must-not-export"
            job_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CampaignCheckpointSecretError):
                export_campaign_checkpoint(
                    td,
                    campaign_id=config.campaign_id,
                    campaign_config=config.raw,
                    repo_root=ROOT,
                )

    def test_pinned_growth_and_media_fixture_provenance_is_validated(self):
        pins = validate_producer_pins(ROOT)
        self.assertEqual(
            [item["sourceHead"] for item in pins["fixtures"]],
            [
                "5c38b8844e91cc8e4f82ccf5e1aa135d32204b36",
                "cc542d626622c780fba2d03d094815d3dca240f9",
            ],
        )
        self.assertEqual(
            [item["gitBlobSha1"] for item in pins["fixtures"]],
            [
                "6c663665313cacd10a34f84af153b2546a8dc2c0",
                "678042975df835d258a249d3ec235d6f06b8c089",
            ],
        )

    def test_accepted_media_receipt_restore_never_resubmits(self):
        config_payload = load_json(SOURCE_CONFIG)
        config_payload["campaignId"] = "checkpoint-media"
        config_payload["cycles"] = 1
        config_payload["failures"] = {}
        config_payload["critic"]["rejectsByCycle"] = {}
        media_fixture = load_json(MEDIA_FIXTURE)
        render = media_fixture["submit"]["request"]
        client = FakeMediaJobV1Client()

        with tempfile.TemporaryDirectory() as source_td, tempfile.TemporaryDirectory() as restored_td:
            source_root = Path(source_td)
            job_store = JsonJobStore(source_root / "jobs")
            adapter = MediaJobV1ResumableAdapter(
                client=client,
                export_spec=render["exportSpec"],
                output_path="outputs/checkpoint-media.mp4",
                dry_run=False,
                logical_job_id="checkpoint-media-job",
            )
            crash = CrashOnce("after_accept_persisted")
            orchestrator = Orchestrator(
                job_store,
                {JobStage.EDIT: adapter},
                operation_boundary_hook=crash,
            )
            job_id = "checkpoint-media-cycle-01"
            orchestrator.create_job(
                job_id,
                "checkpoint accepted media resume",
                seed_artifacts=[
                    SeedArtifactInput("media_timeline_v1", render["timeline"])
                ],
            )
            job = job_store.load(job_id)
            job.stage_index = STAGE_ORDER.index(JobStage.EDIT)
            job_store.save(job)

            config_digest = hashlib.sha256(
                canonical_json(config_payload).encode("utf-8")
            ).hexdigest()
            JsonCampaignStore(source_root / "campaigns").save(
                CampaignState(
                    campaign_id="checkpoint-media",
                    config_digest=config_digest,
                    cycle_job_ids={"1": job_id},
                )
            )

            with self.assertRaises(OperationBoundaryCrash):
                orchestrator.run_next(job_id)
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)

            bundle = export_campaign_checkpoint(
                source_root,
                campaign_id="checkpoint-media",
                campaign_config=config_payload,
                repo_root=ROOT,
            )
            self.assertEqual(len(bundle["acceptedMediaJobs"]), 1)
            accepted = bundle["acceptedMediaJobs"][0]
            self.assertEqual(accepted["mediaJobId"], "checkpoint-media-job")
            self.assertEqual(accepted["receiptState"], OperationState.ACCEPTED.value)

            imported = import_campaign_checkpoint(
                bundle,
                restored_td,
                repo_root=ROOT,
            )
            self.assertEqual(imported.status, "imported")

            restored_store = JsonJobStore(Path(restored_td) / "jobs")
            restored_adapter = MediaJobV1ResumableAdapter(
                client=client,
                export_spec=render["exportSpec"],
                output_path="outputs/checkpoint-media.mp4",
                dry_run=False,
                logical_job_id="checkpoint-media-job",
            )
            restored = Orchestrator(
                restored_store,
                {JobStage.EDIT: restored_adapter},
            )
            resumed_job = restored.run_next(job_id)
            self.assertEqual(
                resumed_job.stage_index,
                STAGE_ORDER.index(JobStage.EDIT) + 1,
            )
            self.assertEqual(client.submit_requests, 1)
            self.assertEqual(client.accepted_jobs, 1)
            self.assertEqual(client.resume_calls, 1)
            finals = [
                artifact
                for artifact in resumed_job.artifacts
                if artifact.kind == "media_final_artifact"
            ]
            self.assertEqual(len(finals), 1)
            self.assertEqual(
                finals[0].metadata["jobId"],
                "checkpoint-media-job",
            )

    def test_reproducibility_report_matches_terminal_lineage_and_checkpoint_hash(self):
        report = load_json(
            CHECKPOINT_DIR / "reproducibility_report_v1.json"
        )
        terminal = load_campaign_checkpoint(
            CHECKPOINT_DIR / "10_terminal.checkpoint.json",
            repo_root=ROOT,
        )
        self.assertEqual(
            report["finalCheckpointHash"],
            terminal["checkpointHash"],
        )
        self.assertEqual(
            report["finalLineageHash"],
            terminal["integrity"]["artifactLineageHash"],
        )
        self.assertEqual(len(report["checkpoints"]), len(BOUNDARY_FILES))


if __name__ == "__main__":
    unittest.main()
