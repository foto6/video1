import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import exact_dynamic_e2e_r29 as r29
from creator_orchestrator import dynamic_live_review_loop as r28
from creator_orchestrator import editor_publish_handoff as r23


def unit_context(round_index=0):
    candidate = {
        "candidateId": f"candidate-r29-r{round_index}",
        "roundIndex": round_index,
        "finalPath": "candidate/final.mp4",
        "renderSha256": "2" * 64,
        "renderSize": 200,
        "renderExportPath": "candidate/media.render_export.v1.json",
        "renderExportSha256": "3" * 64,
        "renderExportDigest": "4" * 64,
        "renderProducerSha": r29.MEDIA_R21_AUTHORITY["producerSha"],
        "editorialApplication": None,
    }
    if round_index:
        candidate["editorialApplication"] = {
            "path": "candidate/media.editorial_reedit_application.v1.json",
            "fileSha256": "5" * 64,
            "digest": "6" * 64,
        }
    return r28.build_candidate_context(
        loop_id="loop-r29",
        brief_digest="7" * 64,
        semantic_analysis_digest="8" * 64,
        semantic_directives_digest="9" * 64,
        ledger_digest="a" * 64,
        source={
            "sourceId": "source-r29",
            "sha256": "1" * 64,
            "size": 100,
            "path": "source.mp4",
        },
        candidate=candidate,
        timeline={
            "id": "timeline-r29",
            "canvas": {"durationMs": 5000},
            "tracks": [],
        },
        export_spec={"format": "mp4"},
    )


def build_envelope(context, state="targeted_reedit", *, assistant_digest=None):
    context = r28.validate_candidate_context(context)
    candidate = context["candidate"]
    package_digest = "b" * 64
    sealed_digest = "c" * 64
    capture_digest = "d" * 64
    critic_input = "e" * 64
    critic_output = "f" * 64
    pairwise_output = "0" * 64
    other_render = "a" * 64
    binding = {
        "source_id": context["source"]["sourceId"],
        "source_sha256": context["source"]["sha256"],
        "source_size": context["source"]["size"],
        "media_repository": r29.MEDIA_R21_AUTHORITY["repository"],
        "media_producer_sha": r29.MEDIA_R21_AUTHORITY["producerSha"],
        "package_digest": package_digest,
        "sealed_mapping_digest": sealed_digest,
        "review_round": candidate["roundIndex"],
        "candidate_id": candidate["candidateId"],
        "candidate_round": candidate["roundIndex"],
        "render_sha256": candidate["renderSha256"],
        "render_size": candidate["renderSize"],
        "render_export_sha256": candidate["renderExportSha256"],
        "attachment_sha256": candidate["renderSha256"],
        "attachment_size": candidate["renderSize"],
        "attachment_mime_type": "video/mp4",
        "critic_input_digest": critic_input,
        "critic_output_digest": critic_output,
        "capture_digest": capture_digest,
    }
    selected = candidate["candidateId"] if state == "winner" else None
    selection = "A" if state == "winner" else "tie"
    if state == "targeted_reedit":
        selected = "other-candidate"
        selection = "B"
    if state == "insufficient_evidence":
        selection = "insufficient_evidence"
    directives = []
    if state == "targeted_reedit":
        directive = {
            "operation": "trim",
            "start_ms": 100,
            "end_ms": 300,
            "defect_category": "awkward_dead_moment",
            "severity": "major",
            "source_observation_id": "obs-r29",
            "evidence": "conformance fixture evidence",
            "confidence": 0.9,
            "uncertainty": "fixture only",
            "upstream_proposed_edit": "remove the bounded pause",
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(binding),
        }
        directive["directive_id"] = "gdr26d1:" + r29._sha(directive)
        directives = [directive]
    handoff = {
        "contract_version": r29.GROWTH_R26_AUTHORITY["dynamicHandoffContract"],
        "handoff_id": "",
        "handoff_digest": "",
        "state": state,
        "review_round": candidate["roundIndex"],
        "max_reedit_rounds": 2,
        "binding": binding,
        "pairwise": {
            "model_facing_selection": selection,
            "selected_candidate_id": selected,
            "output_digest": pairwise_output,
        },
        "coverage": {
            "method": "test_fixture",
            "inspected_ranges": [{"start_ms": 0, "end_ms": 5000}],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": "synthetic conformance fixture",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": "synthetic conformance fixture",
        "directives": directives,
        "evidence_boundary": {
            "model_review_only": True,
            "human_ground_truth": False,
            "human_label": False,
            "human_rating_evidence": False,
            "live_platform_evidence": False,
            "free_form_proposed_edit_executable": False,
        },
        "authority": {
            "advisory_only": True,
            "creator_mutation": False,
            "media_mutation": False,
            "provider_mutation": False,
            "publish_authorized": False,
            "release_authorized": False,
        },
    }
    handoff["handoff_id"] = "gdr26h1:" + r29._sha({
        "capture_digest": capture_digest,
        "package_digest": package_digest,
        "candidate_id": candidate["candidateId"],
        "critic_output_digest": critic_output,
        "pairwise_output_digest": pairwise_output,
        "review_round": candidate["roundIndex"],
    })
    material = copy.deepcopy(handoff)
    material["handoff_digest"] = ""
    handoff["handoff_digest"] = r29._sha(material)
    media_authority = {
        "contract_version": "growth.media_dynamic_review_authority.r26.v1",
        "repository": r29.MEDIA_R21_AUTHORITY["repository"],
        "producer_sha": r29.MEDIA_R21_AUTHORITY["producerSha"],
        "ci_run_id": r29.MEDIA_R21_AUTHORITY["ciRunId"],
        "package_contract": "media.dynamic_review_package.r21.v1",
        "contract_blob_sha1": r29.MEDIA_R21_AUTHORITY["reviewBundleContractBlobSha1"],
        "schema_blob_sha1": r29.MEDIA_R21_AUTHORITY["reviewBundleSchemaBlobSha1"],
        "implementation_blob_sha1": r29.MEDIA_R21_AUTHORITY["reviewBundleImplementationBlobSha1"],
        "artifact_id": r29.MEDIA_R21_AUTHORITY["artifactId"],
        "artifact_name": r29.MEDIA_R21_AUTHORITY["artifactName"],
        "artifact_digest": r29.MEDIA_R21_AUTHORITY["artifactDigest"],
        "package_digest": package_digest,
        "package_file_sha256": "1" * 64,
        "evidence_file_sha256": "2" * 64,
        "prompt_digest": "3" * 64,
        "prompt_file_sha256": "4" * 64,
        "sealed_mapping_digest": sealed_digest,
        "sealed_mapping_file_sha256": "5" * 64,
        "review_round": candidate["roundIndex"],
        "source": {
            "source_id": context["source"]["sourceId"],
            "sha256": context["source"]["sha256"],
            "size": context["source"]["size"],
        },
        "attachments": [
            {
                "blind_label": "A",
                "generic_file_name": "review-A.mp4",
                "sha256": candidate["renderSha256"],
                "size": candidate["renderSize"],
                "mime_type": "video/mp4",
            },
            {
                "blind_label": "B",
                "generic_file_name": "review-B.mp4",
                "sha256": other_render,
                "size": candidate["renderSize"] + 1,
                "mime_type": "video/mp4",
            },
        ],
    }
    bridge_authority = {
        "contract_version": "growth.bridge_dynamic_capture_authority.r26.v1",
        "repository": r29.BRIDGE_R30_AUTHORITY["repository"],
        "producer_sha": r29.BRIDGE_R30_AUTHORITY["producerSha"],
        "ci_run_id": r29.BRIDGE_R30_AUTHORITY["ciRunId"],
        "capture_contract": r29.BRIDGE_R30_AUTHORITY["captureContract"],
        "capture_schema_id": r29.BRIDGE_R30_AUTHORITY["captureSchemaId"],
        "contract_blob_sha1": r29.BRIDGE_R30_AUTHORITY["handoffSchemaBlobSha1"],
        "schema_blob_sha1": r29.BRIDGE_R30_AUTHORITY["captureSchemaBlobSha1"],
        "implementation_blob_sha1": r29.BRIDGE_R30_AUTHORITY["implementationBlobSha1"],
    }
    capture = {
        "capture_id": "bridge-r30-capture-r29",
        "capture_digest": capture_digest,
        "assistant_response_digest": assistant_digest or "6" * 64,
        "conversation": {
            "conversation_id": "conversation-r29",
            "request_id": "request-r29",
        },
        "response_shape": "bridge_r29_native_strict",
        "normalization_generated_summary": False,
        "normalization_generated_pairwise_confidence": False,
    }
    envelope = {
        "contract_version": r29.GROWTH_R26_AUTHORITY["creatorEnvelopeContract"],
        "envelope_id": "",
        "envelope_digest": "",
        "creator_event": {
            "contractVersion": "creator.dynamic_external_review_event.r26.v1",
            "producer": {
                "repository": r29.GROWTH_R26_AUTHORITY["repository"],
                "sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
                "ciRunId": r29.GROWTH_R26_AUTHORITY["ciRunId"],
                "contract": r29.GROWTH_R26_AUTHORITY["dynamicHandoffContract"],
            },
            "captureMode": "external_live_review",
            "reviewIdentity": handoff["handoff_id"],
            "handoff": handoff,
        },
        "growth_r26": {
            "repository": r29.GROWTH_R26_AUTHORITY["repository"],
            "producer_sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
            "ci_run_id": r29.GROWTH_R26_AUTHORITY["ciRunId"],
            "starting_r25_sha": r29.GROWTH_R26_AUTHORITY["startingR25Sha"],
            "ingest_contract": r29.GROWTH_R26_AUTHORITY["captureContract"],
        },
        "media_authority": media_authority,
        "bridge_authority": bridge_authority,
        "capture": capture,
        "review": {
            "package_digest": package_digest,
            "sealed_mapping_digest": sealed_digest,
            "review_round": candidate["roundIndex"],
            "model_facing_selection": selection,
            "selected_candidate_id": selected,
        },
        "candidate": {
            "candidate_id": candidate["candidateId"],
            "candidate_round": candidate["roundIndex"],
            "source_id": context["source"]["sourceId"],
            "source_sha256": context["source"]["sha256"],
            "render_sha256": candidate["renderSha256"],
            "render_size": candidate["renderSize"],
            "attachment_sha256": candidate["renderSha256"],
            "attachment_size": candidate["renderSize"],
            "attachment_mime_type": "video/mp4",
            "handoff_digest": handoff["handoff_digest"],
            "state": state,
        },
        "evidence_boundary": {
            "model_evidence": True,
            "human_ground_truth": False,
            "human_rating_evidence": False,
            "human_parity_inferred": False,
            "provider_mutation": False,
        },
    }
    envelope["envelope_id"] = "gdr26ce1:" + r29._sha({
        "growth_producer_sha": r29.GROWTH_R26_AUTHORITY["producerSha"],
        "capture_digest": capture_digest,
        "package_digest": package_digest,
        "candidate_id": candidate["candidateId"],
        "handoff_digest": handoff["handoff_digest"],
        "review_round": candidate["roundIndex"],
    })
    material = copy.deepcopy(envelope)
    material["envelope_digest"] = ""
    envelope["envelope_digest"] = r29._sha(material)
    return envelope


def redigest_envelope(value):
    material = copy.deepcopy(value)
    material["envelope_digest"] = ""
    value["envelope_digest"] = r29._sha(material)
    return value


class R29AuthorityAndEnvelopeTests(unittest.TestCase):
    def test_exact_authorities_and_source_ready_gate(self):
        self.assertEqual(
            r29.MEDIA_R21_AUTHORITY["producerSha"],
            "d753e9e4c1f4448386608a1425232dbc1dba87ea",
        )
        self.assertEqual(
            r29.GROWTH_R26_AUTHORITY["producerSha"],
            "e844ed2daaaca9e9694fe1e0fb6b8b7bfac69cbc",
        )
        self.assertEqual(
            r29.BRIDGE_R30_AUTHORITY["producerSha"],
            "ceaee873231a8552c5b7324083baa800eec566a8",
        )
        report = r29.readiness_report()
        self.assertEqual(report["state"], "BLOCKED_WAITING_GENUINE_DYNAMIC_CAPTURE")
        self.assertTrue(report["SOURCE_READY"])
        self.assertFalse(report["REAL_REVIEW_INGESTED"])
        self.assertFalse(report["REAL_REEDIT_EXECUTED"])
        self.assertFalse(report["NEXT_REVIEW_PACKAGE_READY"])
        self.assertFalse(report["PUBLISH_HANDOFF_READY"])
        self.assertIsNone(
            report["growthR26ExactHeadArtifact"]["liveCapture"]
        )
        self.assertIsNone(
            report["growthR26ExactHeadArtifact"]["creatorEnvelopes"]
        )

    def test_wrong_producer_sha_and_blob_drift_fail_closed(self):
        growth = copy.deepcopy(r29.GROWTH_R26_AUTHORITY)
        growth["producerSha"] = "0" * 40
        with self.assertRaises(r29.AuthorityDrift):
            r29.validate_growth_authority(growth)
        media = copy.deepcopy(r29.MEDIA_R21_AUTHORITY)
        media["reviewBundleSchemaBlobSha1"] = "0" * 40
        with self.assertRaises(r29.AuthorityDrift):
            r29.validate_media_authority(media)
        bridge = copy.deepcopy(r29.BRIDGE_R30_AUTHORITY)
        bridge["implementationBlobSha1"] = "0" * 40
        with self.assertRaises(r29.AuthorityDrift):
            r29.validate_bridge_authority(bridge)

    def test_valid_r26_envelope_binds_exact_package_capture_and_candidate(self):
        context = unit_context()
        envelope = build_envelope(context)
        parsed = r29.validate_growth_r26_envelope(envelope)
        self.assertEqual(
            parsed["candidate"]["render_sha256"],
            context["candidate"]["renderSha256"],
        )
        self.assertEqual(
            parsed["review"]["package_digest"],
            parsed["creator_event"]["handoff"]["binding"]["package_digest"],
        )
        self.assertEqual(
            parsed["capture"]["capture_digest"],
            parsed["creator_event"]["handoff"]["binding"]["capture_digest"],
        )

    def test_package_and_sealed_mapping_digest_mismatch_fail_closed(self):
        envelope = build_envelope(unit_context())
        broken = copy.deepcopy(envelope)
        broken["review"]["package_digest"] = "9" * 64
        redigest_envelope(broken)
        with self.assertRaises(r29.PackageDrift):
            r29.validate_growth_r26_envelope(broken)
        broken = copy.deepcopy(envelope)
        broken["review"]["sealed_mapping_digest"] = "8" * 64
        redigest_envelope(broken)
        with self.assertRaises(r29.PackageDrift):
            r29.validate_growth_r26_envelope(broken)

    def test_stale_round_and_third_reedit_fail_closed(self):
        context = unit_context(round_index=1)
        envelope = build_envelope(context)
        broken = copy.deepcopy(envelope)
        broken["review"]["review_round"] = 0
        redigest_envelope(broken)
        with self.assertRaises(r29.LineageDrift):
            r29.validate_growth_r26_envelope(broken)
        round_two = build_envelope(unit_context(round_index=2))
        with self.assertRaises(r29.RoundLimit):
            r29.validate_growth_r26_envelope(round_two)

    def test_media_compat_adapter_preserves_r26_origin_without_claiming_legacy_provenance(self):
        context = unit_context()
        envelope = build_envelope(context)
        compat, adapter = r29.adapt_growth_r26_for_media_r19(
            envelope, context
        )
        self.assertEqual(
            adapter["sourceHandoffDigest"],
            envelope["candidate"]["handoff_digest"],
        )
        self.assertFalse(
            adapter["legacyAuthorityFieldsAcceptedAsLiveProvenance"]
        )
        self.assertFalse(adapter["modelJudgmentSynthesized"])
        self.assertEqual(
            compat["binding"]["render_sha256"],
            envelope["candidate"]["render_sha256"],
        )

    def test_duplicate_review_idempotent_changed_response_conflicts(self):
        envelope = build_envelope(unit_context())
        payload = {
            "envelopeDigest": envelope["envelope_digest"],
            "captureDigest": envelope["capture"]["capture_digest"],
            "assistantResponseDigest": envelope["capture"]["assistant_response_digest"],
        }
        with tempfile.TemporaryDirectory() as td:
            ledger = r29.Ledger(Path(td) / "ledger.jsonl")
            self.assertEqual(
                ledger.append_once("review:0", "growth_r26_live_review", payload),
                "committed",
            )
            self.assertEqual(
                ledger.append_once("review:0", "growth_r26_live_review", payload),
                "duplicate",
            )
            changed = dict(payload)
            changed["assistantResponseDigest"] = "7" * 64
            with self.assertRaises(r29.ReplayConflict):
                ledger.append_once(
                    "review:0", "growth_r26_live_review", changed
                )

    def test_nonwinner_never_passes_publish_validator(self):
        tie = build_envelope(unit_context(), state="tie")
        with self.assertRaises(r23.EditorOutcomeIneligible):
            r29._terminal_growth_validator(
                tie,
                expected_source_id="source-r29",
                expected_render_sha256="2" * 64,
            )


@unittest.skipUnless(
    os.environ.get("R29_MEDIA_R21_CHECKOUT")
    and os.environ.get("R29_GROWTH_R26_CHECKOUT"),
    "exact Media R21 and Growth R26 checkouts required",
)
class R29ExactIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(os.environ["R29_MEDIA_R21_CHECKOUT"]).resolve()
        cls.growth = Path(os.environ["R29_GROWTH_R26_CHECKOUT"]).resolve()
        r29.verify_media_checkout(cls.media)
        r29.verify_growth_checkout(cls.growth)
        env = dict(os.environ)
        env["GITHUB_SHA"] = r29.MEDIA_R21_AUTHORITY["producerSha"]
        result = subprocess.run(
            ["node", str(cls.media / "tools/demo-r19-editorial-reedit.mjs")],
            cwd=cls.media,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr[-6000:])
        cls.demo_root = cls.media / ".artifacts/r19-demo"
        cls.case_root = cls.demo_root / "cases/talking-head-vertical"
        cls.request = json.loads(
            (cls.case_root / "request.json").read_text(encoding="utf-8")
        )
        candidate = cls.request["candidate"]
        timeline = cls.request["timeline"]
        source_uri = next(
            track for track in timeline["tracks"] if track["kind"] == "video"
        )["items"][0]["source"]["uri"]
        export_path = cls.demo_root / candidate["renderExportPath"]
        export_digest = r28._media_semantic_digest(
            cls.media, export_path, "render"
        )
        cls.context = r28.build_candidate_context(
            loop_id="r29-exact-integration",
            brief_digest="a" * 64,
            semantic_analysis_digest="b" * 64,
            semantic_directives_digest="c" * 64,
            ledger_digest="d" * 64,
            source={
                "sourceId": candidate["source"]["sourceId"],
                "sha256": candidate["source"]["sha256"],
                "size": candidate["source"]["size"],
                "path": source_uri,
            },
            candidate={
                "candidateId": candidate["candidateId"],
                "roundIndex": 0,
                "finalPath": candidate["finalPath"],
                "renderSha256": candidate["renderSha256"],
                "renderSize": candidate["renderSize"],
                "renderExportPath": candidate["renderExportPath"],
                "renderExportSha256": candidate["renderExportSha256"],
                "renderExportDigest": export_digest,
                "renderProducerSha": candidate["renderProducerSha"],
                "editorialApplication": None,
            },
            timeline=timeline,
            export_spec=cls.request["exportSpec"],
        )

    def setUp(self):
        for name in (
            ".creator-r28",
            ".creator-r29-packages",
            "round-1",
            "round-2",
        ):
            shutil.rmtree(self.demo_root / name, ignore_errors=True)

    def test_exact_checkout_blob_profiles(self):
        self.assertEqual(
            r29.verify_media_checkout(self.media)["checkoutSha"],
            r29.MEDIA_R21_AUTHORITY["producerSha"],
        )
        self.assertEqual(
            r29.verify_growth_checkout(self.growth)["checkoutSha"],
            r29.GROWTH_R26_AUTHORITY["producerSha"],
        )

    def test_real_media_reedit_then_exact_r21_round_package(self):
        envelope = build_envelope(self.context)
        result = r29.execute_media_reedit(
            media_checkout=self.media,
            candidate_root=self.demo_root,
            context=self.context,
            envelope=envelope,
            out_dir=self.demo_root,
        )
        self.assertEqual(result["evidence"]["logicalEffects"], 1)
        self.assertNotEqual(
            result["evidence"]["before"]["sha256"],
            result["evidence"]["after"]["sha256"],
        )
        self.assertFalse(result["adapter"]["modelJudgmentSynthesized"])
        next_context = r29.build_next_context(
            prior=self.context,
            media_result=result,
            candidate_root=self.demo_root,
        )
        package = r29.build_r21_next_package(
            media_checkout=self.media,
            candidate_root=self.demo_root,
            before_context=self.context,
            after_context=next_context,
            envelope=envelope,
            out_dir=self.demo_root / ".creator-r29-packages" / "integration",
        )
        self.assertEqual(
            package["bundle"]["contractVersion"],
            "media.review_round_bundle.r21.v1",
        )
        self.assertEqual(package["bundle"]["reviewRound"], 1)
        self.assertEqual(
            package["evidence"]["sourceGrowthR26HandoffDigest"],
            envelope["candidate"]["handoff_digest"],
        )
        self.assertFalse(package["evidence"]["modelReviewPerformed"])

        replay = r29.execute_media_reedit(
            media_checkout=self.media,
            candidate_root=self.demo_root,
            context=self.context,
            envelope=envelope,
            out_dir=self.demo_root,
        )
        self.assertTrue(replay["evidence"]["replayed"])
        self.assertEqual(replay["evidence"]["logicalEffects"], 0)
        self.assertEqual(
            replay["evidence"]["after"]["sha256"],
            result["evidence"]["after"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
