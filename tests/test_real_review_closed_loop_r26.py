import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import real_review_closed_loop as r26


def binding():
    return {
        "source_id": "source-r26",
        "source_sha256": "1" * 64,
        "source_size": 100,
        "media_repository": "foto6/video2",
        "media_producer_sha": r26.MEDIA_R15_SHA,
        "candidate_id": "candidate-r26",
        "render_sha256": "2" * 64,
        "render_size": 100,
        "render_export_sha256": "3" * 64,
        "attachment_sha256": "2" * 64,
        "attachment_size": 100,
        "attachment_identity": "attachment:r26",
        "review_bundle_digest": "4" * 64,
        "critic_input_digest": "5" * 64,
        "critic_output_digest": "6" * 64,
    }


def handoff(*, state="targeted_reedit", round_index=0, operation="trim"):
    b = binding()
    directives = []
    if state == "targeted_reedit":
        row = {
            "operation": operation,
            "start_ms": 1000,
            "end_ms": 1400,
            "defect_category": "awkward_dead_moment",
            "severity": "major",
            "source_observation_id": "obs-r26",
            "evidence": "externally supplied test fixture evidence",
            "confidence": 0.9,
            "uncertainty": "test-only uncertainty",
            "upstream_proposed_edit": "remove the pause",
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(b),
            "directive_id": "gcrd1:" + "7" * 64,
        }
        directives = [row]
    value = {
        "contract_version": r26.GROWTH_HANDOFF_VERSION,
        "adapter_version": r26.GROWTH_ADAPTER_VERSION,
        "handoff_id": "",
        "handoff_digest": "",
        "state": state,
        "reedit_round": round_index,
        "max_reedit_rounds": 2,
        "binding": b,
        "pairwise": {
            "selection": None,
            "mapped_candidate_id": None,
            "output_digest": None,
        },
        "coverage": {
            "method": "attached_video_review",
            "inspected_ranges": [{"start_ms": 0, "end_ms": 5000}],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": "test fixture preserves coverage uncertainty",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": "test fixture; not a live review claim",
        "directives": directives,
        "bridge_r26_authority": copy.deepcopy(r26.BRIDGE_R26_AUTHORITY),
        "media_r18_authority": copy.deepcopy(r26.MEDIA_R18_AUTHORITY),
        "evidence_boundary": {
            "model_review_only": True,
            "human_ground_truth": False,
            "human_label": False,
            "live_platform_evidence": False,
            "live_video_review_fabricated": False,
        },
        "authority": {
            "advisory_only": True,
            "creator_mutation": False,
            "media_mutation": False,
            "provider_mutation": False,
            "upload_performed": False,
            "publish_authorized": False,
            "release_authorized": False,
        },
    }
    value["handoff_id"] = "gcrh1:" + r26._sha({
        "critic_output_digest": b["critic_output_digest"],
        "pairwise_output_digest": None,
        "reedit_round": round_index,
    })
    material = copy.deepcopy(value)
    material["handoff_digest"] = ""
    value["handoff_digest"] = r26._sha(material)
    return value


def event(*, state="targeted_reedit", round_index=0, operation="trim", mode="test_fixture"):
    h = handoff(state=state, round_index=round_index, operation=operation)
    return {
        "contractVersion": r26.REVIEW_EVENT_VERSION,
        "producer": r26._growth_producer_descriptor(),
        "captureMode": mode,
        "reviewIdentity": h["handoff_id"],
        "handoff": h,
    }


class R26ReviewBoundaryTests(unittest.TestCase):
    def test_valid_growth_r23_handoff_and_event(self):
        parsed = r26.parse_review_event(event(), allow_test_fixture=True)
        self.assertEqual(parsed["handoff"]["state"], "targeted_reedit")
        self.assertEqual(parsed["producer"]["sha"], r26.GROWTH_R23_SHA)

    def test_test_fixture_is_blocked_without_explicit_test_mode(self):
        with self.assertRaises(r26.LiveReviewRequired):
            r26.parse_review_event(event(), allow_test_fixture=False)

    def test_wrong_attachment_lineage_fails(self):
        value = handoff()
        value["binding"]["attachment_sha256"] = "8" * 64
        material = copy.deepcopy(value)
        material["handoff_digest"] = ""
        value["handoff_digest"] = r26._sha(material)
        with self.assertRaises(r26.ReviewLineageError):
            r26.parse_growth_r23_handoff(value)

    def test_unsupported_directive_fails_closed(self):
        value = handoff(operation="not_supported")
        with self.assertRaises(r26.UnsupportedDirective):
            r26.parse_growth_r23_handoff(value)

    def test_max_round_rejects_third_reedit(self):
        parent = {
            "contractVersion": r26.r22.PLAN_VERSION,
            "roundIndex": 2,
            "parentCandidateId": "parent",
            "ordinal": 0,
            "semanticAnalysisDigest": "a" * 64,
            "editorialMode": "clean_podcast",
            "semanticDirectivesDigest": "b" * 64,
            "variant": {"pacingPreset": "steady"},
            "targetedDeltas": [],
            "candidateId": "candidate-r2",
            "planDigest": "c" * 64,
        }
        with self.assertRaises(r26.RoundRegression):
            r26.build_reedit_plan_from_handoff(
                parent_plan=parent,
                handoff=handoff(round_index=2),
            )

    def test_round_regression_rejected(self):
        parent = {
            "contractVersion": r26.r22.PLAN_VERSION,
            "roundIndex": 1,
            "parentCandidateId": "parent",
            "ordinal": 0,
            "semanticAnalysisDigest": "a" * 64,
            "editorialMode": "clean_podcast",
            "semanticDirectivesDigest": "b" * 64,
            "variant": {"pacingPreset": "steady"},
            "targetedDeltas": [],
            "candidateId": "candidate-r1",
            "planDigest": "c" * 64,
        }
        with self.assertRaises(r26.RoundRegression):
            r26.build_reedit_plan_from_handoff(
                parent_plan=parent,
                handoff=handoff(round_index=0),
            )

    def test_reedit_candidate_id_is_stable(self):
        parent = {
            "contractVersion": r26.r22.PLAN_VERSION,
            "roundIndex": 0,
            "parentCandidateId": None,
            "ordinal": 0,
            "semanticAnalysisDigest": "a" * 64,
            "editorialMode": "clean_podcast",
            "semanticDirectivesDigest": "b" * 64,
            "variant": {"pacingPreset": "steady"},
            "targetedDeltas": [],
            "candidateId": "candidate-r0",
            "planDigest": "c" * 64,
        }
        h = handoff(round_index=0)
        first = r26.build_reedit_plan_from_handoff(parent_plan=parent, handoff=h)
        second = r26.build_reedit_plan_from_handoff(parent_plan=parent, handoff=h)
        self.assertEqual(first["candidateId"], second["candidateId"])
        self.assertEqual(first["planDigest"], second["planDigest"])
        self.assertEqual(first["roundIndex"], 1)

    def test_duplicate_review_in_one_invocation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p1 = Path(td) / "a.json"
            p2 = Path(td) / "b.json"
            payload = event()
            p1.write_text(json.dumps(payload))
            p2.write_text(json.dumps(payload))
            with self.assertRaises(r26.ReviewReplayError):
                r26._review_map([p1, p2], allow_test_fixture=True)

    def test_out_of_order_reviews_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p0 = Path(td) / "r0.json"
            p1 = Path(td) / "r1.json"
            p0.write_text(json.dumps(event(round_index=0)))
            p1.write_text(json.dumps(event(round_index=1)))
            with self.assertRaises(r26.RoundRegression):
                r26._review_map([p1, p0], allow_test_fixture=True)

    def test_ledger_restart_duplicate_is_noop_and_conflict_fails(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = r26.Ledger(path)
            payload = {"handoffDigest": "d" * 64}
            self.assertEqual(
                ledger.append_once("review:0", "growth_r23_real_review", payload),
                "committed",
            )
            restarted = r26.Ledger(path)
            self.assertEqual(
                restarted.append_once("review:0", "growth_r23_real_review", payload),
                "duplicate",
            )
            self.assertEqual(len(restarted.events), 1)
            with self.assertRaises(r26.ReviewReplayError):
                restarted.append_once(
                    "review:0",
                    "growth_r23_real_review",
                    {"handoffDigest": "e" * 64},
                )

    def test_stale_source_and_render_are_rejected(self):
        value = event()
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / "final.mp4"
            final.write_bytes(b"x" * 100)
            record = {
                "candidateId": "candidate-r26",
                "renderPath": str(final),
                "render": {
                    "render_sha256": "2" * 64,
                    "render_provenance": {"mediaR15ExportDigest": "3" * 64},
                },
            }
            source = {
                "sourceId": "source-r26",
                "sha256": "1" * 64,
                "sizeBytes": 100,
            }
            r26._validate_review_against_render(
                value,
                source=source,
                render_record=record,
                expected_round=0,
            )
            stale = copy.deepcopy(value)
            stale["handoff"]["binding"]["source_sha256"] = "9" * 64
            with self.assertRaises(r26.ReviewLineageError):
                r26._validate_review_against_render(
                    stale,
                    source=source,
                    render_record=record,
                    expected_round=0,
                )
            stale = copy.deepcopy(value)
            stale["handoff"]["binding"]["render_sha256"] = "9" * 64
            with self.assertRaises(r26.ReviewLineageError):
                r26._validate_review_against_render(
                    stale,
                    source=source,
                    render_record=record,
                    expected_round=0,
                )

    def test_only_winner_is_publish_eligible(self):
        winner = handoff(state="winner")
        parsed = r26._terminal_review_validator(
            winner,
            expected_source_id="source-r26",
            expected_render_sha256="2" * 64,
        )
        self.assertEqual(parsed["state"], "winner")
        with self.assertRaises(r26.r23.EditorOutcomeIneligible):
            r26._terminal_review_validator(
                handoff(state="tie"),
                expected_source_id="source-r26",
                expected_render_sha256="2" * 64,
            )

    def test_readiness_distinguishes_implementation_from_execution(self):
        report = r26.readiness_report()
        self.assertEqual(report["implementationStatus"], "IMPLEMENTED")
        self.assertEqual(report["realReviewExecutionStatus"], "BLOCKED")
        self.assertEqual(
            report["blocker"]["code"],
            "MISSING_EXTERNAL_GROWTH_R23_REAL_REVIEW_EVENT",
        )
        self.assertFalse(report["providerInvoked"])
        self.assertFalse(report["credentialsUsed"])


if __name__ == "__main__":
    unittest.main()
