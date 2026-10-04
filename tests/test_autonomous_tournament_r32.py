from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import autonomous_tournament_r32 as r32


class R32TournamentTests(unittest.TestCase):
    def new_ledger(self, root: Path) -> r32.TournamentLedger:
        return r32.TournamentLedger(
            root / "ledger.jsonl",
            source_sha256="a" * 64,
            source_size=790819,
            source_duration_ms=30000,
            brief_digest="b" * 64,
        )

    def dispatch_all(
        self,
        ledger: r32.TournamentLedger,
        adapter: r32.FixtureDispatchAdapter,
        prefix: str,
    ) -> None:
        for i in range(3):
            r32.dispatch_review(
                ledger,
                reviewer_index=i,
                conversation_id=f"{prefix}-{i}",
                adapter=adapter,
            )

    def test_readiness_freezes_current_authorities_and_waits_next_wave(self):
        ready = r32.readiness()
        self.assertEqual(ready["status"], "AUTONOMOUS_LOOP_SOURCE_READY")
        self.assertTrue(ready["SOURCE_READY"])
        self.assertFalse(ready["FULL_NEXT_WAVE_PINNED"])
        self.assertEqual(
            ready["currentAuthorities"]["mediaR24"]["producerSha"],
            "244acdf154741e669991b17df3ef2a47e2dfdfa9",
        )
        self.assertEqual(
            ready["currentAuthorities"]["growthR29"]["producerSha"],
            "3e4a8ad6d73b058c953abeadba7a60abe567adbc",
        )
        self.assertEqual(
            ready["currentAuthorities"]["bridgeR34"]["producerSha"],
            "4e2a37545cc0cdd940cf6e86d40e0d620d6c94ae",
        )
        missing = ready["blockers"][0]["missing"]
        self.assertEqual(
            {item["expectedContract"] for item in missing},
            {
                "media.multicandidate_round.r25.v1",
                "growth.consensus_review.r30.v1",
                "bridge.multiagent_dispatch.r35.v1",
            },
        )

    def test_candidate_package_rejects_duplicate_bytes_and_swapped_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            duplicate = copy.deepcopy(package)
            duplicate["candidates"][1]["renderSha256"] = duplicate["candidates"][0]["renderSha256"]
            duplicate["candidates"][1]["sealedToken"] = r32._sha(
                {
                    "candidateId": duplicate["candidates"][1]["candidateId"],
                    "renderSha256": duplicate["candidates"][1]["renderSha256"],
                    "editGraphDigest": duplicate["candidates"][1]["editGraphDigest"],
                }
            )
            duplicate["candidateSetDigest"] = r32._sha(duplicate["candidates"])
            mapping = [
                {
                    "candidateId": item["candidateId"],
                    "sealedToken": item["sealedToken"],
                    "renderSha256": item["renderSha256"],
                }
                for item in duplicate["candidates"]
            ]
            duplicate["sealedMappingDigest"] = r32._sha(mapping)
            material = copy.deepcopy(duplicate)
            material["packageDigest"] = ""
            duplicate["packageDigest"] = r32._sha(material)
            with self.assertRaises(r32.StateConflict):
                r32.validate_candidate_package(ledger, duplicate)

            swapped = copy.deepcopy(package)
            swapped["candidates"][0]["sealedToken"], swapped["candidates"][1]["sealedToken"] = (
                swapped["candidates"][1]["sealedToken"],
                swapped["candidates"][0]["sealedToken"],
            )
            swapped["candidateSetDigest"] = r32._sha(swapped["candidates"])
            swapped["sealedMappingDigest"] = r32._sha(
                [
                    {
                        "candidateId": item["candidateId"],
                        "sealedToken": item["sealedToken"],
                        "renderSha256": item["renderSha256"],
                    }
                    for item in swapped["candidates"]
                ]
            )
            material = copy.deepcopy(swapped)
            material["packageDigest"] = ""
            swapped["packageDigest"] = r32._sha(material)
            with self.assertRaises(r32.StateConflict):
                r32.validate_candidate_package(ledger, swapped)

    def test_stale_source_and_undeclared_graph_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            stale = copy.deepcopy(package)
            stale["sourceSha256"] = "c" * 64
            material = copy.deepcopy(stale)
            material["packageDigest"] = ""
            stale["packageDigest"] = r32._sha(material)
            with self.assertRaises(r32.StateConflict):
                r32.validate_candidate_package(ledger, stale)

            graph = copy.deepcopy(package)
            graph["candidates"][0]["editGraphDeclared"] = False
            graph["candidateSetDigest"] = r32._sha(graph["candidates"])
            material = copy.deepcopy(graph)
            material["packageDigest"] = ""
            graph["packageDigest"] = r32._sha(material)
            with self.assertRaises(r32.StateConflict):
                r32.validate_candidate_package(ledger, graph)

    def test_frozen_session_rejects_changed_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = self.new_ledger(root)
            changed = r32.authority_profiles()
            changed["current"]["mediaR24"]["producerSha"] = "0" * 40
            with self.assertRaises(r32.AuthorityDrift):
                r32.TournamentLedger(ledger.path, authorities=changed)

    def test_illegal_source_to_publish_jump_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            with self.assertRaises(r32.NonPublishable):
                r32.emit_publish_handoff(ledger, package=package)

    def test_lost_ack_halts_consensus_and_recovery_does_not_duplicate_send(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package)
            adapter = r32.FixtureDispatchAdapter()
            r32.dispatch_review(
                ledger,
                reviewer_index=0,
                conversation_id="c0",
                adapter=adapter,
            )
            state = r32.dispatch_review(
                ledger,
                reviewer_index=1,
                conversation_id="c1",
                adapter=adapter,
                lose_ack=True,
            )
            self.assertEqual(state["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(adapter.effect_count, 2)
            with self.assertRaises(r32.ReconciliationRequired):
                r32.dispatch_review(
                    ledger,
                    reviewer_index=2,
                    conversation_id="c2",
                    adapter=adapter,
                )
            with self.assertRaises((r32.ReconciliationRequired, KeyError)):
                consensus = r32.build_fixture_consensus(
                    ledger,
                    decision="targeted_reedit",
                    selected_candidate_id=package["candidates"][0]["candidateId"],
                    directives=r32._directive_fixture(0),
                )
                r32.ingest_consensus(ledger, consensus)
            ledger = r32.TournamentLedger(ledger.path)
            r32.reconcile_dispatch(
                ledger,
                reviewer_index=1,
                conversation_id="c1",
                adapter=adapter,
            )
            r32.dispatch_review(
                ledger,
                reviewer_index=2,
                conversation_id="c2",
                adapter=adapter,
            )
            self.assertEqual(adapter.effect_count, 3)
            self.assertEqual(ledger.state["state"], "REVIEWS_COMPLETE")

    def test_same_operation_changed_conversation_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package)
            adapter = r32.FixtureDispatchAdapter()
            r32.dispatch_review(
                ledger,
                reviewer_index=0,
                conversation_id="conversation-A",
                adapter=adapter,
            )
            with self.assertRaises(r32.ReplayConflict):
                r32.dispatch_review(
                    ledger,
                    reviewer_index=0,
                    conversation_id="conversation-B",
                    adapter=adapter,
                )

    def test_consensus_exact_replay_idempotent_changed_response_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package)
            adapter = r32.FixtureDispatchAdapter()
            self.dispatch_all(ledger, adapter, "round0")
            consensus = r32.build_fixture_consensus(
                ledger,
                decision="targeted_reedit",
                selected_candidate_id=package["candidates"][0]["candidateId"],
                directives=r32._directive_fixture(0),
            )
            first = r32.ingest_consensus(ledger, consensus)
            event_count = len(ledger.events)
            second = r32.ingest_consensus(ledger, consensus)
            self.assertEqual(first, second)
            self.assertEqual(len(ledger.events), event_count)
            changed = copy.deepcopy(consensus)
            changed["directives"][0]["parameters"]["removeLeadInMs"] = 400
            material = copy.deepcopy(changed)
            material["consensusDigest"] = ""
            changed["consensusDigest"] = r32._sha(material)
            with self.assertRaises(r32.ReplayConflict):
                r32.ingest_consensus(ledger, changed)

    def test_targeted_reedit_preserves_unaffected_graph_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package)
            dispatch = r32.FixtureDispatchAdapter()
            self.dispatch_all(ledger, dispatch, "round0")
            consensus = r32.build_fixture_consensus(
                ledger,
                decision="targeted_reedit",
                selected_candidate_id=package["candidates"][0]["candidateId"],
                directives=r32._directive_fixture(0),
            )
            r32.ingest_consensus(ledger, consensus)
            media = r32.FixtureMediaReeditAdapter()
            state = r32.apply_targeted_reedit(
                ledger,
                package=package,
                consensus=consensus,
                adapter=media,
            )
            self.assertEqual(state["reeditRound"], 1)
            self.assertEqual(state["reviewRound"], 1)
            self.assertEqual(media.effect_count, 1)
            event = ledger.by_key["reedit:r1"]
            request = event["requestDigest"]
            self.assertTrue(request)
            replay = r32.apply_targeted_reedit(
                ledger,
                package=package,
                consensus=consensus,
                adapter=media,
            )
            self.assertEqual(replay, state)
            self.assertEqual(media.effect_count, 1)

    def test_third_reedit_attempt_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            dispatch = r32.FixtureDispatchAdapter()
            media = r32.FixtureMediaReeditAdapter()

            package0 = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package0)
            self.dispatch_all(ledger, dispatch, "r0")
            consensus0 = r32.build_fixture_consensus(
                ledger,
                decision="targeted_reedit",
                selected_candidate_id=package0["candidates"][0]["candidateId"],
                directives=r32._directive_fixture(0),
            )
            r32.ingest_consensus(ledger, consensus0)
            r32.apply_targeted_reedit(ledger, package=package0, consensus=consensus0, adapter=media)

            package1 = r32.build_fixture_candidate_package(
                ledger,
                base_render_sha=ledger.state["selectedRender"]["outputRenderSha256"],
            )
            r32.ingest_candidate_package(ledger, package1)
            self.dispatch_all(ledger, dispatch, "r1")
            consensus1 = r32.build_fixture_consensus(
                ledger,
                decision="targeted_reedit",
                selected_candidate_id=package1["candidates"][0]["candidateId"],
                directives=r32._directive_fixture(1),
            )
            r32.ingest_consensus(ledger, consensus1)
            r32.apply_targeted_reedit(ledger, package=package1, consensus=consensus1, adapter=media)

            package2 = r32.build_fixture_candidate_package(
                ledger,
                base_render_sha=ledger.state["selectedRender"]["outputRenderSha256"],
            )
            r32.ingest_candidate_package(ledger, package2)
            self.dispatch_all(ledger, dispatch, "r2")
            third = r32.build_fixture_consensus(
                ledger,
                decision="targeted_reedit",
                selected_candidate_id=package2["candidates"][0]["candidateId"],
                directives=r32._directive_fixture(2),
            )
            with self.assertRaises(r32.RoundOverflow):
                r32.ingest_consensus(ledger, third)

    def test_human_review_is_nonpublishable(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package)
            dispatch = r32.FixtureDispatchAdapter()
            self.dispatch_all(ledger, dispatch, "human")
            consensus = r32.build_fixture_consensus(
                ledger,
                decision="human_review",
                selected_candidate_id=None,
                consensus_state="HUMAN_REVIEW_REQUIRED",
            )
            r32.ingest_consensus(ledger, consensus)
            self.assertEqual(ledger.state["state"], "HUMAN_REVIEW_REQUIRED")
            with self.assertRaises(r32.NonPublishable):
                r32.emit_publish_handoff(ledger, package=package)

    def test_publish_is_blocked_under_unresolved_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            package = r32.build_fixture_candidate_package(ledger)
            r32.ingest_candidate_package(ledger, package)
            dispatch = r32.FixtureDispatchAdapter()
            r32.dispatch_review(
                ledger,
                reviewer_index=0,
                conversation_id="lost",
                adapter=dispatch,
                lose_ack=True,
            )
            with self.assertRaises(r32.ReconciliationRequired):
                r32.emit_publish_handoff(ledger, package=package)

    def test_adversarial_ledger_state_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            lines = ledger.path.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["newState"]["state"] = "PUBLISH_HANDOFF_READY"
            ledger.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            with self.assertRaises(r32.StateConflict):
                r32.TournamentLedger(ledger.path)

    def test_chaos_rehearsal_is_deterministic_and_side_effect_bounded(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = r32.run_chaos_rehearsal(a)
            second = r32.run_chaos_rehearsal(b)
            self.assertEqual(first["reportDigest"], second["reportDigest"])
            self.assertEqual(first["ledgerDigest"], second["ledgerDigest"])
            self.assertEqual(first["state"], "PUBLISH_HANDOFF_READY")
            self.assertEqual(first["initialCandidateCount"], 4)
            self.assertEqual(first["independentReviewerCount"], 3)
            self.assertEqual(first["reviewRoundsCompleted"], 2)
            self.assertEqual(first["reeditRoundsExecuted"], 1)
            self.assertEqual(first["dispatchLogicalEffects"], 6)
            self.assertEqual(first["mediaReeditLogicalEffects"], 1)
            self.assertTrue(first["lostAckConsensusBlocked"])
            self.assertFalse(first["browserMutation"])
            self.assertFalse(first["providerMutation"])
            self.assertFalse(first["livePublish"])
            self.assertFalse(first["humanGroundTruthClaimed"])

    def test_status_reports_exact_next_action_and_authority_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.new_ledger(Path(td))
            status = ledger.status()
            self.assertEqual(status["state"], "SOURCE_READY")
            self.assertEqual(status["nextPermittedAction"], "INGEST_CANDIDATE_PACKAGE")
            self.assertEqual(status["overallAuthorityStatus"], "AUTONOMOUS_LOOP_SOURCE_READY")
            self.assertFalse(r32.readiness()["FULL_NEXT_WAVE_PINNED"])


if __name__ == "__main__":
    unittest.main()
