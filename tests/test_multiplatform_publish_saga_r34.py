from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import multiplatform_publish_saga_r34 as r34
from creator_orchestrator import publish_transaction_r33 as r33


class R34MultiplatformPublishSagaTests(unittest.TestCase):
    def kwargs(self) -> dict:
        return r34._fixture_kwargs()

    def prepare(self, root: Path) -> r34.SagaLedger:
        return r34.prepare_saga(root, **self.kwargs())

    def prepare_all(self, saga: r34.SagaLedger) -> None:
        for platform in r34.REQUIRED_PLATFORMS:
            r34.validate_platform(saga, platform)
            r34.mark_platform_commit_eligible(saga, platform)

    def test_readiness_waits_for_parent_qa_r3_without_acceptance_claim(self):
        value = r34.readiness()
        self.assertEqual(value["state"], "SOURCE_READY_WAITING_PARENT_QA")
        self.assertTrue(value["SOURCE_READY"])
        self.assertFalse(value["PARENT_R33_ACCEPTED"])
        self.assertEqual(value["parentQa"]["requiredGate"], "QA-R3")
        self.assertEqual(value["parentQa"]["status"], "PENDING")
        self.assertEqual(
            value["parentR33Authority"]["producerSha"],
            "9556108f423a15a40614a8bc9d590e6dc2e49746",
        )
        self.assertEqual(value["parentR33Authority"]["ciRunId"], 37203622591)
        self.assertEqual(value["parentR33Authority"]["artifactId"], 11304071297)
        self.assertEqual(
            value["parentR33Authority"]["artifactDigest"],
            "sha256:adbfb6d257332220e2be2f9d8f134a87f8bcc6b6e064dfac7f469fd95d690d6d",
        )
        self.assertFalse(value["safety"]["livePublish"])
        self.assertEqual(value["safety"]["providerNetworkEffects"], 0)

    def test_prepare_creates_three_independent_r33_transactions(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            status = r34.saga_status(saga)
            self.assertEqual(status["state"], "ALL_PENDING")
            self.assertFalse(status["globalSuccess"])
            self.assertEqual(set(status["perPlatform"]), set(r34.REQUIRED_PLATFORMS))
            keys = set()
            transaction_ids = set()
            for platform in r34.REQUIRED_PLATFORMS:
                item = status["perPlatform"][platform]
                self.assertEqual(item["state"], "PREPARED")
                keys.add(item["idempotencyKey"])
                transaction_ids.add(item["transactionId"])
                self.assertEqual(
                    saga.state["platformIdentity"][platform]["configRevision"],
                    7,
                )
                self.assertTrue(
                    (Path(td) / "transactions" / f"{platform}.jsonl").is_file()
                )
            self.assertEqual(len(keys), 3)
            self.assertEqual(len(transaction_ids), 3)

    def test_idempotency_key_binds_winner_copy_window_target_revision_and_platform(self):
        kwargs = self.kwargs()
        spec = r34.build_saga_spec(**kwargs)
        original = {
            p: spec["childSpecs"][p]["idempotencyKey"]
            for p in r34.REQUIRED_PLATFORMS
        }

        changed = self.kwargs()
        changed["platform_configs"]["tiktok"]["caption"] += " changed"
        changed_spec = r34.build_saga_spec(**changed)
        self.assertEqual(
            original["instagram_reels"],
            changed_spec["childSpecs"]["instagram_reels"]["idempotencyKey"],
        )
        self.assertNotEqual(
            original["tiktok"],
            changed_spec["childSpecs"]["tiktok"]["idempotencyKey"],
        )

        changed = self.kwargs()
        changed["platform_configs"]["tiktok"]["configRevision"] += 1
        changed_spec = r34.build_saga_spec(**changed)
        self.assertNotEqual(
            original["tiktok"],
            changed_spec["childSpecs"]["tiktok"]["idempotencyKey"],
        )

        changed = self.kwargs()
        changed["release_window"]["revision"] += 1
        changed_spec = r34.build_saga_spec(**changed)
        for platform in r34.REQUIRED_PLATFORMS:
            self.assertNotEqual(
                original[platform],
                changed_spec["childSpecs"][platform]["idempotencyKey"],
            )

    def test_exact_replay_reopens_byte_stable_saga(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self.prepare(root)
            first_bytes = first.path.read_bytes()
            first_status = r34.saga_status(first)
            second = r34.prepare_saga(root, **self.kwargs())
            self.assertEqual(first_bytes, second.path.read_bytes())
            self.assertEqual(first.digest, second.digest)
            self.assertEqual(first_status, r34.saga_status(second))

    def test_same_saga_changed_copy_is_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.prepare(root)
            changed = self.kwargs()
            changed["platform_configs"]["instagram_reels"]["caption"] = "different"
            with self.assertRaises((r34.SagaConflict, r33.ReplayConflict)):
                r34.prepare_saga(root, **changed)

    def test_same_saga_changed_config_revision_is_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.prepare(root)
            changed = self.kwargs()
            changed["platform_configs"]["youtube_shorts"]["configRevision"] += 1
            with self.assertRaises((r34.SagaConflict, r33.ReplayConflict)):
                r34.prepare_saga(root, **changed)

    def test_schedule_revision_drift_is_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.prepare(root)
            changed = self.kwargs()
            changed["release_window"]["revision"] += 1
            with self.assertRaises((r34.SagaConflict, r33.ReplayConflict)):
                r34.prepare_saga(root, **changed)

    def test_stale_parent_authority_rejected(self):
        kwargs = self.kwargs()
        parent = copy.deepcopy(r34.PARENT_R33_AUTHORITY)
        parent["producerSha"] = "0" * 40
        kwargs["parent_r33_authority"] = parent
        with self.assertRaises(r34.SagaAuthorityDrift):
            r34.build_saga_spec(**kwargs)

    def test_nonwinner_r32_handoff_never_prepares_saga(self):
        for outcome in ("tie", "human_review", "insufficient_evidence"):
            kwargs = self.kwargs()
            kwargs["upstream_outcome"] = outcome
            with self.assertRaises(r33.UpstreamIneligible):
                r34.build_saga_spec(**kwargs)

    def test_commit_blocked_before_window_and_after_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            provider = r33.FakeProviderHarness("clean_success")
            with self.assertRaises(r34.SagaScheduleError):
                r34.commit_platform(
                    saga,
                    "instagram_reels",
                    provider,
                    at_time="2026-10-05T11:59:59Z",
                )
            self.assertEqual(provider.commit_calls, 0)
            with self.assertRaises(r34.SagaScheduleError):
                r34.commit_platform(
                    saga,
                    "instagram_reels",
                    provider,
                    at_time="2026-10-05T13:00:01Z",
                )
            self.assertEqual(provider.commit_calls, 0)
            status = r34.saga_status(
                saga,
                at_time="2026-10-05T11:59:59Z",
            )
            self.assertEqual(
                status["perPlatform"]["instagram_reels"]["nextSafeAction"],
                "WAIT_FOR_RELEASE_WINDOW",
            )
            self.assertFalse(
                status["perPlatform"]["instagram_reels"]["replayAuthorized"]
            )

    def test_partial_commit_does_not_mark_global_success(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            ig = r33.FakeProviderHarness("clean_success")
            r34.commit_platform(
                saga,
                "instagram_reels",
                ig,
                at_time="2026-10-05T12:10:00Z",
            )
            status = r34.saga_status(saga, at_time="2026-10-05T12:10:01Z")
            self.assertEqual(status["state"], "PARTIALLY_COMMITTED")
            self.assertEqual(status["committedPlatforms"], ["instagram_reels"])
            self.assertFalse(status["globalSuccess"])
            self.assertEqual(ig.effect_count, 1)

    def test_unknown_tiktok_outcome_blocks_blind_replay_but_not_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            provider = r33.FakeProviderHarness("unknown_no_lookup")
            r34.commit_platform(
                saga,
                "tiktok",
                provider,
                at_time="2026-10-05T12:10:00Z",
            )
            calls = provider.commit_calls
            status = r34.saga_status(saga, at_time="2026-10-05T12:10:01Z")
            self.assertEqual(status["state"], "RECONCILIATION_REQUIRED")
            item = status["perPlatform"]["tiktok"]
            self.assertEqual(item["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(item["nextSafeAction"], "READ_ONLY_RECONCILE_ONLY")
            self.assertFalse(item["replayAuthorized"])
            with self.assertRaises(r33.ReconciliationRequired):
                r34.commit_platform(
                    saga,
                    "tiktok",
                    provider,
                    at_time="2026-10-05T12:10:02Z",
                )
            self.assertEqual(provider.commit_calls, calls)
            r34.reconcile_platform(saga, "tiktok", provider)
            self.assertEqual(
                r34.saga_status(saga)["perPlatform"]["tiktok"]["state"],
                "RECONCILIATION_REQUIRED",
            )

    def test_lost_ack_duplicate_confirmed_promotes_only_with_exact_lookup_proof(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            provider = r34.DuplicateConfirmedAfterDispatch()
            state = r34.commit_platform(
                saga,
                "tiktok",
                provider,
                at_time="2026-10-05T12:10:00Z",
            )
            self.assertEqual(state["state"], "RECONCILIATION_REQUIRED")
            calls = provider.commit_calls
            committed = r34.reconcile_platform(saga, "tiktok", provider)
            self.assertEqual(committed["state"], "COMMITTED")
            self.assertEqual(
                committed["commit"]["providerOutcome"],
                "duplicate_confirmed",
            )
            self.assertIsNotNone(committed["commit"]["outcomeProofDigest"])
            self.assertEqual(provider.commit_calls, calls)

    def test_success_on_ig_never_authorizes_unknown_tiktok_replay(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            ig = r33.FakeProviderHarness("clean_success")
            tt = r33.FakeProviderHarness("unknown_no_lookup")
            r34.commit_platform(
                saga,
                "instagram_reels",
                ig,
                at_time="2026-10-05T12:10:00Z",
            )
            r34.commit_platform(
                saga,
                "tiktok",
                tt,
                at_time="2026-10-05T12:11:00Z",
            )
            status = r34.saga_status(saga, at_time="2026-10-05T12:11:01Z")
            self.assertTrue(
                status["perPlatform"]["instagram_reels"][
                    "externalPostConfirmed"
                ]
            )
            self.assertFalse(
                status["perPlatform"]["tiktok"]["replayAuthorized"]
            )
            tt_calls = tt.commit_calls
            r34.commit_platform(
                saga,
                "youtube_shorts",
                r33.FakeProviderHarness("clean_success"),
                at_time="2026-10-05T12:12:00Z",
            )
            self.assertEqual(tt.commit_calls, tt_calls)
            self.assertEqual(
                r34.saga_status(saga)["state"],
                "RECONCILIATION_REQUIRED",
            )

    def test_validation_reject_is_terminal_block_under_default_policy(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            r34.validate_platform(saga, "instagram_reels")
            r34.mark_platform_commit_eligible(saga, "instagram_reels")
            r34.validate_platform(saga, "tiktok")
            r34.mark_platform_commit_eligible(saga, "tiktok")
            r34.reject_platform_validation(
                saga,
                "youtube_shorts",
                reason_code="provider_account_not_ready",
            )
            status = r34.saga_status(saga)
            self.assertEqual(status["state"], "TERMINAL_BLOCKED")
            self.assertFalse(status["globalSuccess"])
            self.assertEqual(
                status["perPlatform"]["youtube_shorts"]["state"],
                "ABORTED",
            )
            self.assertEqual(
                saga.child("youtube_shorts").state["commit"]["attemptNumber"],
                0,
            )

    def test_committed_platform_cannot_be_locally_aborted_or_rolled_back(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            provider = r33.FakeProviderHarness("clean_success")
            r34.commit_platform(
                saga,
                "instagram_reels",
                provider,
                at_time="2026-10-05T12:10:00Z",
            )
            with self.assertRaises(r33.InvalidTransition):
                r34.abort_platform(
                    saga,
                    "instagram_reels",
                    reason="cannot undo external post",
                )
            state = r34.record_compensation_metadata(
                saga,
                "instagram_reels",
                reason="workflow requests future manual compensation",
            )
            self.assertEqual(
                saga.child("instagram_reels").state["state"],
                "COMMITTED",
            )
            compensation = state["compensations"]["instagram_reels"]
            self.assertFalse(compensation["providerDeleteContractAvailable"])
            self.assertFalse(compensation["providerDeleteExecuted"])
            self.assertFalse(compensation["localRollbackClaimed"])
            self.assertTrue(compensation["externalPostStillCommitted"])

    def test_all_required_policy_global_success_only_after_three_commits(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            for index, platform in enumerate(r34.REQUIRED_PLATFORMS):
                r34.commit_platform(
                    saga,
                    platform,
                    r33.FakeProviderHarness("clean_success"),
                    at_time=f"2026-10-05T12:1{index}:00Z",
                )
                status = r34.saga_status(saga)
                if index < 2:
                    self.assertFalse(status["globalSuccess"])
                else:
                    self.assertTrue(status["globalSuccess"])
                    self.assertEqual(status["state"], "ALL_COMMITTED")

    def test_explicit_partial_release_policy_is_explicit_not_default(self):
        kwargs = self.kwargs()
        kwargs["release_policy"] = {
            "mode": "explicit_partial",
            "requiredPlatforms": list(r34.REQUIRED_PLATFORMS),
            "minimumCommittedPlatforms": 2,
        }
        with tempfile.TemporaryDirectory() as td:
            saga = r34.prepare_saga(Path(td), **kwargs)
            self.prepare_all(saga)
            for platform in ("instagram_reels", "tiktok"):
                r34.commit_platform(
                    saga,
                    platform,
                    r33.FakeProviderHarness("clean_success"),
                    at_time="2026-10-05T12:10:00Z",
                )
            status = r34.saga_status(saga)
            self.assertEqual(status["state"], "PARTIALLY_COMMITTED")
            self.assertTrue(status["globalSuccess"])
            self.assertEqual(
                status["releasePolicy"]["mode"],
                "explicit_partial",
            )

    def test_restart_at_each_child_boundary_preserves_exactly_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saga = self.prepare(root)
            r34.validate_platform(saga, "instagram_reels")
            saga = r34.SagaLedger(root)
            r34.mark_platform_commit_eligible(saga, "instagram_reels")
            saga = r34.SagaLedger(root)
            provider = r33.FakeProviderHarness("clean_success")
            r34.commit_platform(
                saga,
                "instagram_reels",
                provider,
                at_time="2026-10-05T12:10:00Z",
            )
            saga = r34.SagaLedger(root)
            calls = provider.commit_calls
            state = r34.commit_platform(
                saga,
                "instagram_reels",
                provider,
                at_time="2026-10-05T12:10:01Z",
            )
            self.assertEqual(state["state"], "COMMITTED")
            self.assertEqual(provider.commit_calls, calls)
            self.assertEqual(provider.effect_count, 1)

    def test_crash_after_child_commit_before_saga_sync_recovers_from_child_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saga = self.prepare(root)
            self.prepare_all(saga)
            child = saga.child("instagram_reels")
            provider = r33.FakeProviderHarness("clean_success")
            r33.commit_transaction(child, provider)
            # No R34 sync happened. A process restart must derive truth from R33.
            restarted = r34.SagaLedger(root)
            status = r34.saga_status(restarted)
            self.assertEqual(status["state"], "PARTIALLY_COMMITTED")
            self.assertEqual(
                status["perPlatform"]["instagram_reels"]["state"],
                "COMMITTED",
            )
            self.assertEqual(provider.effect_count, 1)

    def test_saga_ledger_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saga = self.prepare(root)
            lines = saga.path.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["newState"]["winner"]["sha256"] = "0" * 64
            saga.path.write_text(
                json.dumps(event, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(r34.SagaConflict):
                r34.SagaLedger(root)

    def test_child_r33_ledger_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saga = self.prepare(root)
            child_path = saga.child_path("tiktok")
            event = json.loads(child_path.read_text(encoding="utf-8").splitlines()[0])
            event["newState"]["requestDigest"] = "0" * 64
            child_path.write_text(
                json.dumps(event, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(r33.ReplayConflict):
                r34.saga_status(r34.SagaLedger(root))

    def test_status_has_exact_blocker_safe_action_and_replay_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            saga = self.prepare(Path(td))
            self.prepare_all(saga)
            provider = r33.FakeProviderHarness("unknown_no_lookup")
            r34.commit_platform(
                saga,
                "tiktok",
                provider,
                at_time="2026-10-05T12:10:00Z",
            )
            status = r34.saga_status(saga)
            item = status["perPlatform"]["tiktok"]
            self.assertEqual(item["nextSafeAction"], "READ_ONLY_RECONCILE_ONLY")
            self.assertFalse(item["replayAuthorized"])
            self.assertEqual(
                item["exactBlocker"]["code"],
                "RECONCILIATION_REQUIRED",
            )
            self.assertFalse(status["livePublish"])
            self.assertEqual(status["providerNetworkEffects"], 0)

    def test_no_secret_material_in_durable_saga_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saga = self.prepare(root)
            self.prepare_all(saga)
            durable = "\n".join(
                p.read_text(encoding="utf-8")
                for p in root.rglob("*.jsonl")
            ).lower()
            self.assertNotIn("access_token", durable)
            self.assertNotIn("refresh_token", durable)
            self.assertNotIn("bearer ", durable)
            self.assertNotIn("client_secret", durable)

    def test_deterministic_three_platform_chaos_rehearsal(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = r34.run_chaos_rehearsal(a)
            second = r34.run_chaos_rehearsal(b)
            self.assertEqual(first["reportDigest"], second["reportDigest"])
            self.assertEqual(first["state"], "SOURCE_READY_WAITING_PARENT_QA")
            self.assertFalse(first["parentQaAccepted"])
            self.assertTrue(first["crashBeforeWindowBlocked"])
            self.assertEqual(first["afterInstagramCommit"]["state"], "PARTIALLY_COMMITTED")
            self.assertEqual(
                first["afterInstagramCommit"]["committedPlatforms"],
                ["instagram_reels"],
            )
            self.assertEqual(first["partialUnknown"]["state"], "RECONCILIATION_REQUIRED")
            self.assertFalse(
                first["partialUnknown"]["perPlatform"]["tiktok"]["replayAuthorized"]
            )
            self.assertTrue(first["blindRetryBlocked"])
            self.assertEqual(
                first["afterTikTokDuplicateConfirmed"]["perPlatform"]["tiktok"]["state"],
                "COMMITTED",
            )
            self.assertEqual(first["allCommitted"]["state"], "ALL_COMMITTED")
            self.assertTrue(first["allCommitted"]["globalSuccess"])
            self.assertEqual(
                first["lookupUnavailable"]["perPlatform"]["tiktok"]["state"],
                "RECONCILIATION_REQUIRED",
            )
            self.assertTrue(first["lookupUnavailableBlindRetryBlocked"])
            self.assertEqual(first["validationRejected"]["state"], "TERMINAL_BLOCKED")
            self.assertTrue(
                first["compensationMetadata"]["externalPostStillCommitted"]
            )
            self.assertEqual(first["realProviderEffects"], 0)
            self.assertEqual(first["providerNetworkEffects"], 0)
            self.assertFalse(first["livePublish"])
            evidence = json.loads(
                (Path(a) / "evidence-manifest.r34.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(evidence["partialCommitObserved"])
            self.assertTrue(evidence["unknownOutcomeObserved"])
            self.assertTrue(evidence["tiktokDuplicateConfirmed"])
            self.assertTrue(evidence["outcomeLookupUnavailableRemainsBlocked"])
            self.assertTrue(evidence["validationRejectTerminalBlocked"])
            self.assertTrue(evidence["unknownOutcomeBlindRetryForbidden"])
            self.assertTrue(
                evidence["compensationNeverRewritesCommittedPost"]
            )
            self.assertEqual(evidence["realProviderEffects"], 0)


if __name__ == "__main__":
    unittest.main()
