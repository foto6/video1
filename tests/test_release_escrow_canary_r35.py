from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import multiplatform_publish_saga_r34 as r34
from creator_orchestrator import publish_transaction_r33 as r33
from creator_orchestrator import release_escrow_canary_r35 as r35


class R35ReleaseEscrowCanaryTests(unittest.TestCase):
    def kwargs(self) -> dict:
        return r35._fixture_release_kwargs()

    def spec(self) -> dict:
        return r35.build_release_spec(**self.kwargs())

    def prepared(self, root: Path) -> tuple[r35.ReleaseLedger, dict]:
        spec = self.spec()
        return r35.ReleaseLedger(root, release_spec=spec), spec

    def escrowed(self, root: Path) -> tuple[r35.ReleaseLedger, dict]:
        return r35._prepare_escrowed(root)

    def preflight(self, root: Path) -> tuple[r35.ReleaseLedger, dict]:
        return r35._prepare_preflight(root)

    def eligible(self, root: Path) -> tuple[r35.ReleaseLedger, dict]:
        return r35._prepare_canary_eligible(root)

    def test_readiness_freezes_exact_accepted_authorities_and_no_live_provider(self):
        value = r35.readiness()
        self.assertEqual(value["state"], "SOURCE_READY_NO_LIVE_PROVIDER")
        self.assertTrue(value["SOURCE_READY"])
        self.assertFalse(value["LIVE_PROVIDER_ENABLED"])
        self.assertEqual(
            value["r34Authority"]["producerSha"],
            "77dfe83d582eac98e60728974efc77345612b364",
        )
        self.assertEqual(value["r34Authority"]["ciRunId"], 37209289425)
        self.assertEqual(value["r34Authority"]["artifactId"], 11305609870)
        self.assertEqual(
            value["r34Authority"]["artifactDigest"],
            "sha256:366dc6b7f43982c23489f7119a04805b4be9b8eed2717f61a9db3a0e6ece1032",
        )
        self.assertEqual(
            value["r34Authority"]["qaR5"]["producerSha"],
            "1583c853108b0fb88507448eb8b4c61f0f07b0bc",
        )
        self.assertEqual(value["r34Authority"]["qaR5"]["ciRunId"], 37211964139)
        self.assertEqual(value["r34Authority"]["qaR5"]["artifactId"], 11306289580)
        self.assertEqual(
            value["r34Authority"]["qaR5"]["artifactDigest"],
            "sha256:846c97206fb332d0ffa1011f44b884b3148736ba9ca96a756b4ae585eab50bfa",
        )
        self.assertEqual(
            value["growthR33Authority"]["producerSha"],
            "8bedb5ad79023006b87b17933863ff915ab5e046",
        )
        self.assertEqual(value["growthR33Authority"]["ciRunId"], 37210963972)
        self.assertEqual(value["growthR33Authority"]["artifactId"], 11306727215)
        self.assertEqual(
            value["growthR33Authority"]["artifactDigest"],
            "sha256:132845c0aaa6d4fec5aaf60e1ade60d779183f2a637a9513e4176bd2ee569660",
        )
        self.assertTrue(value["safety"]["fakeProviderOnly"])
        self.assertEqual(value["safety"]["providerNetworkEffects"], 0)
        self.assertEqual(value["safety"]["realProviderEffects"], 0)
        self.assertFalse(value["safety"]["realProviderEffectAuthorized"])
        self.assertFalse(value["safety"]["livePublish"])
        self.assertFalse(value["safety"]["blindRetryAfterUnknown"])

    def test_release_intent_binds_source_tournament_winner_authorities_policy_and_schedule(self):
        spec = self.spec()
        self.assertEqual(spec["contractVersion"], r35.CONTRACT_VERSION)
        self.assertEqual(spec["r34Authority"], r35.R34_AUTHORITY)
        self.assertEqual(spec["growthR33Authority"], r35.GROWTH_R33_AUTHORITY)
        self.assertEqual(spec["r34SagaSpec"]["contractVersion"], r34.CONTRACT_VERSION)
        self.assertEqual(
            spec["releasePolicy"]["requiredPlatforms"],
            ["instagram_reels", "tiktok", "youtube_shorts"],
        )
        self.assertEqual(spec["releasePolicy"]["canaryPlatform"], "instagram_reels")
        self.assertEqual(
            spec["releasePolicy"]["expansionOrder"],
            ["tiktok", "youtube_shorts"],
        )
        self.assertTrue(spec["releaseOperationId"].startswith("r35release:"))
        self.assertEqual(len(spec["releaseOperationId"].split(":", 1)[1]), 64)
        self.assertEqual(spec["scheduleWindow"]["revision"], spec["revisionId"])
        self.assertEqual(spec["policyDigest"], r35._sha(spec["releasePolicy"]))
        self.assertEqual(
            spec["growthDecisionDigest"],
            spec["growthAdvisory"]["decisionDigest"],
        )

    def test_wrong_r34_authority_tuple_fails_closed(self):
        for field, value in (
            ("producerSha", "0" * 40),
            ("ciRunId", 1),
            ("artifactId", 1),
            ("artifactDigest", "sha256:" + "0" * 64),
        ):
            kwargs = self.kwargs()
            authority = copy.deepcopy(r35.R34_AUTHORITY)
            authority[field] = value
            kwargs["r34_authority"] = authority
            with self.subTest(field=field):
                with self.assertRaises(r35.AuthorityDrift):
                    r35.build_release_spec(**kwargs)

    def test_wrong_r34_qa_r5_evidence_fails_closed(self):
        mutations = [
            ("qa_sha", "producerSha", "0" * 40),
            ("qa_run", "ciRunId", 1),
            ("qa_artifact", "artifactId", 1),
            ("qa_digest", "artifactDigest", "sha256:" + "0" * 64),
        ]
        for name, field, value in mutations:
            kwargs = self.kwargs()
            authority = copy.deepcopy(r35.R34_AUTHORITY)
            authority["qaR5"][field] = value
            kwargs["r34_authority"] = authority
            with self.subTest(name=name):
                with self.assertRaises(r35.AuthorityDrift):
                    r35.build_release_spec(**kwargs)

    def test_wrong_growth_r33_authority_tuple_fails_closed(self):
        for field, value in (
            ("producerSha", "0" * 40),
            ("ciRunId", 1),
            ("artifactId", 1),
            ("artifactDigest", "sha256:" + "0" * 64),
        ):
            kwargs = self.kwargs()
            authority = copy.deepcopy(r35.GROWTH_R33_AUTHORITY)
            authority[field] = value
            kwargs["growth_authority"] = authority
            with self.subTest(field=field):
                with self.assertRaises(r35.AuthorityDrift):
                    r35.build_release_spec(**kwargs)

    def test_growth_advisory_is_read_only_and_cannot_authorize_mutation(self):
        advisory = r35._fixture_growth_advisory()
        self.assertFalse(advisory["evidenceBoundary"]["creatorMutation"])
        self.assertFalse(advisory["evidenceBoundary"]["providerMutation"])
        self.assertFalse(advisory["evidenceBoundary"]["livePublish"])

        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.preflight(Path(td))
            state = r35.mark_canary_eligible(
                ledger,
                at_time="2026-10-05T12:01:00Z",
                operator_authorization_digest=spec["growthDecisionDigest"],
            )
            self.assertEqual(state["state"], "HUMAN_REVIEW_REQUIRED")
            self.assertEqual(
                state["blockers"][0]["code"],
                "OPERATOR_AUTHORIZATION_MISMATCH",
            )

    def test_phase_skips_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.prepared(Path(td))
            with self.assertRaises(r35.IllegalTransition):
                r35.preflight_release(
                    ledger,
                    started_at="2026-10-05T11:30:00Z",
                    completed_at="2026-10-05T11:45:00Z",
                    observed_policy_digest=spec["policyDigest"],
                    observed_growth_decision_digest=spec["growthDecisionDigest"],
                )
            with self.assertRaises(r35.IllegalTransition):
                r35.mark_canary_eligible(
                    ledger,
                    at_time="2026-10-05T12:01:00Z",
                    operator_authorization_digest=spec["releasePolicy"]["operatorAuthorizationDigest"],
                )
            with self.assertRaises(r35.IllegalTransition):
                r35.commit_canary(
                    ledger,
                    r33.FakeProviderHarness("clean_success"),
                    at_time="2026-10-05T12:02:00Z",
                    observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
                )
            with self.assertRaises(r35.IllegalTransition):
                r35.mark_expansion_eligible(ledger, at_time="2026-10-05T12:03:00Z")

    def test_escrow_freezes_exact_render_bytes_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.prepared(Path(td))
            metadata_digest = r35._fixture_metadata_digest(spec)
            state = r35.escrow_release(
                ledger,
                observed_render_sha256=spec["winner"]["sha256"],
                observed_render_size=spec["winner"]["size"],
                metadata_digest=metadata_digest,
            )
            self.assertEqual(state["state"], "ESCROWED")
            self.assertEqual(state["escrow"]["renderSha256"], spec["winner"]["sha256"])
            self.assertEqual(state["escrow"]["renderSize"], spec["winner"]["size"])
            self.assertEqual(state["escrow"]["metadataDigest"], metadata_digest)
            self.assertEqual(state["fakeProviderEffects"], 0)
            self.assertEqual(state["providerNetworkEffects"], 0)

    def test_escrow_render_or_metadata_drift_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.escrowed(Path(td))
            with self.assertRaises(r35.ReleaseConflict):
                r35.verify_frozen_identity(ledger, render_sha256="0" * 64)
            with self.assertRaises(r35.ReleaseConflict):
                r35.verify_frozen_identity(ledger, render_size=spec["winner"]["size"] + 1)
            with self.assertRaises(r35.ReleaseConflict):
                r35.verify_frozen_identity(ledger, metadata_digest="1" * 64)

    def test_same_release_replayed_with_changed_payload_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec = self.spec()
            first = r35.ReleaseLedger(root, release_spec=spec)
            changed = copy.deepcopy(spec)
            changed["winner"]["sha256"] = "0" * 64
            with self.assertRaises(r35.ReleaseConflict):
                r35.ReleaseLedger(root, release_spec=changed)
            self.assertEqual(first.state["state"], "PREPARED")

    def test_changed_platform_set_or_canary_policy_fails_closed(self):
        kwargs = self.kwargs()
        kwargs["release_policy"] = copy.deepcopy(r35.DEFAULT_RELEASE_POLICY)
        kwargs["release_policy"]["requiredPlatforms"] = ["instagram_reels", "tiktok"]
        with self.assertRaises(r35.ReleaseError):
            r35.build_release_spec(**kwargs)

        kwargs = self.kwargs()
        kwargs["release_policy"] = copy.deepcopy(r35.DEFAULT_RELEASE_POLICY)
        kwargs["release_policy"]["canaryPlatform"] = "other"
        with self.assertRaises(r35.ReleaseError):
            r35.build_release_spec(**kwargs)

    def test_stale_growth_decision_or_policy_after_escrow_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, _ = self.escrowed(Path(td))
            with self.assertRaises(r35.ReleaseConflict):
                r35.verify_frozen_identity(
                    ledger,
                    growth_decision_digest="2" * 64,
                )
            with self.assertRaises(r35.ReleaseConflict):
                r35.verify_frozen_identity(
                    ledger,
                    policy_digest="3" * 64,
                )

    def test_preflight_validates_all_three_r34_children_without_provider_effect(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.preflight(Path(td))
            self.assertEqual(ledger.state["state"], "PREFLIGHT_GREEN")
            self.assertEqual(
                set(ledger.state["preflight"]["validationDigests"]),
                set(r34.REQUIRED_PLATFORMS),
            )
            self.assertFalse(ledger.state["preflight"]["growthAdvisoryAuthorizesMutation"])
            self.assertFalse(ledger.state["preflight"]["realProviderEffectAuthorized"])
            for platform in r34.REQUIRED_PLATFORMS:
                self.assertEqual(
                    ledger.r34_saga.child(platform).state["state"],
                    "VALIDATED",
                )
            self.assertEqual(ledger.state["fakeProviderEffects"], 0)

    def test_preflight_crossing_deadline_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.escrowed(Path(td))
            state = r35.preflight_release(
                ledger,
                started_at="2026-10-05T12:59:59Z",
                completed_at="2026-10-05T13:00:01Z",
                observed_policy_digest=spec["policyDigest"],
                observed_growth_decision_digest=spec["growthDecisionDigest"],
            )
            self.assertEqual(state["state"], "TERMINALLY_BLOCKED")
            self.assertEqual(
                state["blockers"][0]["code"],
                "PREFLIGHT_CROSSED_RELEASE_DEADLINE",
            )

    def test_canary_platform_is_deterministic_from_policy(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            self.assertEqual(spec["releasePolicy"]["canaryPlatform"], "instagram_reels")
            self.assertEqual(ledger.state["state"], "CANARY_ELIGIBLE")
            self.assertEqual(
                ledger.state["platforms"]["instagram_reels"]["operationState"],
                "ELIGIBLE",
            )
            self.assertEqual(
                ledger.r34_saga.child("instagram_reels").state["state"],
                "COMMIT_ELIGIBLE",
            )
            self.assertEqual(
                ledger.r34_saga.child("tiktok").state["state"],
                "VALIDATED",
            )

    def test_canary_unknown_outcome_never_blind_retries(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("timeout_after_dispatch")
            state = r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            self.assertEqual(state["state"], "RECONCILIATION_REQUIRED")
            calls = provider.commit_calls
            restarted = r35.ReleaseLedger(Path(td))
            with self.assertRaises(r35.ReconciliationRequired):
                r35.commit_canary(
                    restarted,
                    provider,
                    at_time="2026-10-05T12:03:00Z",
                    observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
                )
            self.assertEqual(provider.commit_calls, calls)
            status = r35.release_status(restarted)
            self.assertEqual(status["nextPermittedAction"], "READ_ONLY_RECONCILE_ONLY")
            self.assertFalse(status["realProviderEffectAuthorized"])
            self.assertFalse(
                status["platforms"]["instagram_reels"]["replayAuthorized"]
            )

    def test_canary_timeout_before_dispatch_is_safe_and_effect_free(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("timeout_before_dispatch")
            state = r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            self.assertEqual(state["state"], "CANARY_ELIGIBLE")
            self.assertEqual(provider.effect_count, 0)
            self.assertTrue(state["platforms"]["instagram_reels"]["replayAuthorized"])

    def test_duplicate_confirmed_canary_requires_read_only_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            provider = r34.DuplicateConfirmedAfterDispatch()
            r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            self.assertEqual(ledger.state["state"], "RECONCILIATION_REQUIRED")
            calls = provider.commit_calls
            state = r35.reconcile_operation(
                ledger,
                "instagram_reels",
                provider,
                at_time="2026-10-05T12:03:00Z",
            )
            self.assertEqual(state["state"], "CANARY_CONFIRMED")
            self.assertEqual(provider.commit_calls, calls)
            self.assertEqual(
                ledger.r34_saga.child("instagram_reels").state["commit"]["providerOutcome"],
                "duplicate_confirmed",
            )

    def test_delayed_canary_confirmation_stays_unknown_until_provider_proves_outcome(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            provider = r35.DelayedConfirmationProvider()
            r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            first = r35.reconcile_operation(
                ledger,
                "instagram_reels",
                provider,
                at_time="2026-10-05T12:03:00Z",
            )
            self.assertEqual(first["state"], "RECONCILIATION_REQUIRED")
            second = r35.reconcile_operation(
                ledger,
                "instagram_reels",
                provider,
                at_time="2026-10-05T12:04:00Z",
            )
            self.assertEqual(second["state"], "CANARY_CONFIRMED")

    def test_conflicting_provider_id_never_becomes_confirmed(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            provider = r35.ConflictingProviderId()
            state = r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            self.assertEqual(state["state"], "RECONCILIATION_REQUIRED")
            self.assertIsNone(
                ledger.r34_saga.child("instagram_reels").state["commit"]["externalPostId"]
            )

    def test_wrong_account_before_canary_commit_requires_human_review_without_provider_call(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, _ = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("clean_success")
            state = r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref="wrong",
            )
            self.assertEqual(state["state"], "HUMAN_REVIEW_REQUIRED")
            self.assertEqual(provider.commit_calls, 0)
            self.assertEqual(provider.effect_count, 0)

    def test_stale_schedule_after_restart_blocks_before_provider(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger, spec = self.eligible(root)
            restarted = r35.ReleaseLedger(root)
            provider = r33.FakeProviderHarness("clean_success")
            state = r35.commit_canary(
                restarted,
                provider,
                at_time="2026-10-05T13:00:01Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            self.assertEqual(state["state"], "TERMINALLY_BLOCKED")
            self.assertEqual(provider.commit_calls, 0)

    def test_expansion_cannot_start_before_canary_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, _ = self.eligible(Path(td))
            with self.assertRaises(r35.IllegalTransition):
                r35.mark_expansion_eligible(
                    ledger,
                    at_time="2026-10-05T12:03:00Z",
                )

    def test_expansion_after_canary_confirmation_preserves_platform_identity(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec, _ = r35._confirm_canary(Path(td))
            state = r35.mark_expansion_eligible(
                ledger,
                at_time="2026-10-05T12:03:00Z",
            )
            self.assertEqual(state["state"], "EXPANSION_ELIGIBLE")
            for platform in ("tiktok", "youtube_shorts"):
                self.assertEqual(
                    state["platforms"][platform]["accountIdentity"],
                    spec["platformAccounts"][platform],
                )
                self.assertEqual(
                    ledger.r34_saga.child(platform).state["state"],
                    "COMMIT_ELIGIBLE",
                )

    def test_one_expansion_unknown_blocks_other_platform_without_retargeting(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec, _ = r35._confirm_canary(Path(td))
            r35.mark_expansion_eligible(ledger, at_time="2026-10-05T12:03:00Z")
            tiktok = r33.FakeProviderHarness("timeout_after_dispatch")
            r35.commit_expansion_platform(
                ledger,
                "tiktok",
                tiktok,
                at_time="2026-10-05T12:04:00Z",
                observed_account_ref=spec["platformAccounts"]["tiktok"]["accountRef"],
            )
            self.assertEqual(ledger.state["state"], "RECONCILIATION_REQUIRED")
            youtube = r33.FakeProviderHarness("clean_success")
            with self.assertRaises(r35.ReconciliationRequired):
                r35.commit_expansion_platform(
                    ledger,
                    "youtube_shorts",
                    youtube,
                    at_time="2026-10-05T12:05:00Z",
                    observed_account_ref=spec["platformAccounts"]["youtube_shorts"]["accountRef"],
                )
            self.assertEqual(youtube.commit_calls, 0)
            self.assertEqual(youtube.effect_count, 0)

    def test_restart_after_canary_confirmation_and_mid_expansion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger, spec, canary = r35._confirm_canary(root)
            canary_calls = canary.commit_calls
            restarted = r35.ReleaseLedger(root)
            r35.mark_expansion_eligible(restarted, at_time="2026-10-05T12:03:00Z")
            self.assertEqual(canary.commit_calls, canary_calls)

            tiktok = r33.FakeProviderHarness("clean_success")
            r35.commit_expansion_platform(
                restarted,
                "tiktok",
                tiktok,
                at_time="2026-10-05T12:04:00Z",
                observed_account_ref=spec["platformAccounts"]["tiktok"]["accountRef"],
            )
            tiktok_effects = tiktok.effect_count
            restarted = r35.ReleaseLedger(root)
            youtube = r33.FakeProviderHarness("clean_success")
            state = r35.commit_expansion_platform(
                restarted,
                "youtube_shorts",
                youtube,
                at_time="2026-10-05T12:05:00Z",
                observed_account_ref=spec["platformAccounts"]["youtube_shorts"]["accountRef"],
            )
            self.assertEqual(state["state"], "FULLY_CONFIRMED")
            self.assertEqual(tiktok.effect_count, tiktok_effects)
            self.assertEqual(youtube.effect_count, 1)

    def test_metadata_compensation_does_not_rewrite_external_commit(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, _, _ = r35._confirm_canary(Path(td))
            with self.assertRaises(r35.CompensationForbidden):
                r35.record_compensation_metadata(
                    ledger,
                    "instagram_reels",
                    reason="delete/repost request",
                    provider_contract_proves_reversible_metadata=False,
                )
            state = r35.record_compensation_metadata(
                ledger,
                "instagram_reels",
                reason="metadata marker only",
                provider_contract_proves_reversible_metadata=True,
            )
            comp = state["compensations"]["instagram_reels"]
            self.assertTrue(comp["metadataOnly"])
            self.assertFalse(comp["providerDeleteExecuted"])
            self.assertFalse(comp["repostExecuted"])
            self.assertTrue(comp["externalPostStillCommitted"])
            self.assertEqual(
                ledger.r34_saga.child("instagram_reels").state["state"],
                "COMMITTED",
            )

    def test_status_reports_durable_evidence_unresolved_operations_and_real_effect_false(self):
        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("unknown_no_lookup")
            r35.commit_canary(
                ledger,
                provider,
                at_time="2026-10-05T12:02:00Z",
                observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
            )
            status = r35.release_status(ledger)
            self.assertEqual(status["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(status["nextPermittedAction"], "READ_ONLY_RECONCILE_ONLY")
            self.assertEqual(len(status["unresolvedOperations"]), 1)
            self.assertFalse(status["unresolvedOperations"][0]["replayAuthorized"])
            self.assertTrue(status["durableEvidence"]["r35LedgerDigest"])
            self.assertTrue(status["durableEvidence"]["r34SagaLedgerDigest"])
            self.assertFalse(status["realProviderEffectAuthorized"])
            self.assertEqual(status["providerNetworkEffects"], 0)
            self.assertFalse(status["livePublish"])

    def test_non_fake_provider_is_forbidden(self):
        class LiveLike:
            is_fake = False

        with tempfile.TemporaryDirectory() as td:
            ledger, spec = self.eligible(Path(td))
            with self.assertRaises(r35.LiveProviderForbidden):
                r35.commit_canary(
                    ledger,
                    LiveLike(),
                    at_time="2026-10-05T12:02:00Z",
                    observed_account_ref=spec["platformAccounts"]["instagram_reels"]["accountRef"],
                )

    def test_deterministic_chaos_harness_executes_at_least_25_cases(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = r35.run_chaos_rehearsal(a)
            second = r35.run_chaos_rehearsal(b)
            self.assertEqual(first["reportDigest"], second["reportDigest"])
            self.assertEqual(first["state"], "SOURCE_READY_NO_LIVE_PROVIDER")
            self.assertGreaterEqual(first["caseCount"], 25)
            self.assertTrue(first["allCasesPassed"])
            self.assertTrue(all(case["passed"] for case in first["cases"].values()))
            self.assertEqual(first["providerNetworkEffects"], 0)
            self.assertEqual(first["realProviderEffects"], 0)
            self.assertFalse(first["realProviderEffectAuthorized"])
            self.assertFalse(first["livePublish"])
            proof = first["unknownEffectReconciliationProof"]
            self.assertEqual(proof["unknownState"], "RECONCILIATION_REQUIRED")
            self.assertFalse(proof["blindRetry"])
            self.assertEqual(
                proof["nextPermittedAction"],
                "READ_ONLY_RECONCILE_ONLY",
            )

    def test_chaos_evidence_manifest_is_source_bound_and_no_network(self):
        with tempfile.TemporaryDirectory() as td:
            report = r35.run_chaos_rehearsal(td)
            evidence = json.loads(
                (Path(td) / "evidence-manifest.r35.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["chaosReportDigest"], report["reportDigest"])
            self.assertEqual(
                evidence["r34Authority"]["producerSha"],
                "77dfe83d582eac98e60728974efc77345612b364",
            )
            self.assertEqual(
                evidence["growthR33Authority"]["producerSha"],
                "8bedb5ad79023006b87b17933863ff915ab5e046",
            )
            self.assertGreaterEqual(evidence["caseCount"], 25)
            self.assertTrue(evidence["allCasesPassed"])
            self.assertTrue(evidence["unknownEffectNeverBlindRetried"])
            self.assertEqual(evidence["providerNetworkEffects"], 0)
            self.assertEqual(evidence["realProviderEffects"], 0)
            self.assertFalse(evidence["realProviderEffectAuthorized"])
            self.assertFalse(evidence["livePublish"])


if __name__ == "__main__":
    unittest.main()
