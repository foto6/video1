from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import publish_transaction_r33 as r33


class ForgedPostIdAdapter(r33.FakeProviderHarness):
    def __init__(self) -> None:
        super().__init__("clean_success")

    def commit(self, state):
        value = super().commit(state)
        forged = copy.deepcopy(value)
        forged["externalPostId"] = "fakepost:forged"
        return forged


class NotFakeAdapter:
    is_fake = False


class R33PublishTransactionTests(unittest.TestCase):
    def kwargs(self, platform: str = "instagram_reels") -> dict:
        upstream, handoff = r33._fixture_upstream()
        target = r33._target(platform)
        return {
            "upstream_state": upstream,
            "handoff": handoff,
            "upstream_outcome": "winner",
            "media_metadata": r33._fixture_media(handoff, platform),
            "caption": "Caption A",
            "title": "Title A",
            "thumbnail_sha256": "e" * 64,
            "publish_policy": {
                "comments": "provider_default",
                "visibilityPolicy": target["destination"],
            },
            "planned_publish_at": "2026-10-05T12:00:00Z",
            **target,
        }

    def prepared(self, root: Path, platform: str = "instagram_reels", name: str = "tx.jsonl"):
        return r33.prepare_transaction(root / name, **self.kwargs(platform))

    def eligible(self, root: Path, platform: str = "instagram_reels", name: str = "tx.jsonl"):
        ledger = self.prepared(root, platform, name)
        r33.validate_prepared(ledger)
        r33.mark_commit_eligible(ledger)
        return ledger

    def test_readiness_exact_r32_authority_and_no_live_publish(self):
        ready = r33.readiness()
        self.assertEqual(ready["state"], "SOURCE_READY_NO_LIVE_PUBLISH")
        self.assertTrue(ready["SOURCE_READY"])
        self.assertFalse(ready["LIVE_PUBLISH_ENABLED"])
        self.assertEqual(
            ready["creatorR32Authority"]["producerSha"],
            "f0dc1d27da6452f1de32cd887651805b47a1735d",
        )
        self.assertEqual(ready["creatorR32Authority"]["ciRunId"], 37199512624)
        self.assertEqual(ready["creatorR32Authority"]["artifactId"], 11302367811)
        self.assertEqual(
            ready["creatorR32Authority"]["artifactDigest"],
            "sha256:6803db334974b8dbea1c30c107ec5af00fe2cb892ed67e68540c2b2d74b18599",
        )
        self.assertFalse(ready["safety"]["realSideEffectPermitted"])
        self.assertFalse(ready["safety"]["networkPermitted"])

    def test_prepare_binds_winner_lineage_content_policy_and_target(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.prepared(Path(td))
            state = ledger.state
            self.assertEqual(state["state"], "PREPARED")
            self.assertEqual(state["winner"]["sha256"], "d" * 64)
            self.assertEqual(state["winner"]["size"], 646823)
            self.assertEqual(state["lineage"]["reviewRound"], 1)
            self.assertEqual(state["r32Authority"], r33.CREATOR_R32_AUTHORITY)
            self.assertEqual(state["contentHashes"]["captionSha256"], r33._sha_text("Caption A"))
            self.assertEqual(state["contentHashes"]["titleSha256"], r33._sha_text("Title A"))
            self.assertTrue(state["publishPolicyHash"])
            self.assertTrue(state["requestDigest"])
            self.assertFalse(state["dryRunRequest"]["networkEnabled"])
            durable = ledger.path.read_text(encoding="utf-8").lower()
            self.assertNotIn("access_token", durable)
            self.assertNotIn("refresh_token", durable)
            self.assertNotIn("bearer ", durable)

    def test_stale_r32_authority_rejected(self):
        kwargs = self.kwargs()
        authority = copy.deepcopy(r33.CREATOR_R32_AUTHORITY)
        authority["producerSha"] = "0" * 40
        kwargs["r32_authority"] = authority
        with self.assertRaises(r33.AuthorityDrift):
            r33.build_prepare_spec(**kwargs)

    def test_upstream_handoff_tamper_and_nonwinner_states_fail_closed(self):
        for outcome in ("tie", "insufficient_evidence", "human_review"):
            kwargs = self.kwargs()
            kwargs["upstream_outcome"] = outcome
            with self.assertRaises(r33.UpstreamIneligible):
                r33.build_prepare_spec(**kwargs)

        kwargs = self.kwargs()
        kwargs["handoff"] = copy.deepcopy(kwargs["handoff"])
        kwargs["handoff"]["finalArtifact"]["sha256"] = "f" * 64
        with self.assertRaises(r33.UpstreamIneligible):
            r33.build_prepare_spec(**kwargs)

        kwargs = self.kwargs()
        kwargs["upstream_state"] = copy.deepcopy(kwargs["upstream_state"])
        kwargs["upstream_state"]["reconciliationRequired"] = True
        with self.assertRaises(r33.UpstreamIneligible):
            r33.build_prepare_spec(**kwargs)

    def test_provider_media_constraints_and_account_presence(self):
        kwargs = self.kwargs("instagram_reels")
        kwargs["media_metadata"] = copy.deepcopy(kwargs["media_metadata"])
        kwargs["media_metadata"]["publicHttpsUrlAvailable"] = False
        with self.assertRaises(r33.ValidationFailed):
            r33.build_prepare_spec(**kwargs)

        kwargs = self.kwargs("tiktok")
        kwargs["media_metadata"] = copy.deepcopy(kwargs["media_metadata"])
        kwargs["media_metadata"]["fps"] = 120.0
        with self.assertRaises(r33.ValidationFailed):
            r33.build_prepare_spec(**kwargs)

        kwargs = self.kwargs("youtube_shorts")
        kwargs["account_ref"] = ""
        with self.assertRaises(r33.PublishTransactionError):
            r33.build_prepare_spec(**kwargs)

    def test_state_machine_cannot_skip_validation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.prepared(Path(td))
            with self.assertRaises(r33.InvalidTransition):
                r33.mark_commit_eligible(ledger)
            with self.assertRaises(r33.InvalidTransition):
                r33.begin_commit(ledger)
            r33.validate_prepared(ledger)
            with self.assertRaises(r33.InvalidTransition):
                r33.commit_transaction(ledger, r33.FakeProviderHarness("clean_success"))
            r33.mark_commit_eligible(ledger)
            state = r33.begin_commit(ledger)
            self.assertEqual(state["state"], "COMMITTING")
            self.assertFalse(state["commit"]["invocationStarted"])

    def test_duplicate_commit_is_exactly_once_and_committed_never_invokes_again(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("clean_success")
            first = r33.commit_transaction(ledger, provider)
            self.assertEqual(first["state"], "COMMITTED")
            calls = provider.commit_calls
            effects = provider.effect_count
            second = r33.commit_transaction(ledger, provider)
            self.assertEqual(second, first)
            self.assertEqual(provider.commit_calls, calls)
            self.assertEqual(provider.effect_count, effects)
            restarted = r33.TransactionLedger(ledger.path)
            third = r33.commit_transaction(restarted, provider)
            self.assertEqual(third["transactionId"], first["transactionId"])
            self.assertEqual(provider.commit_calls, calls)

    def test_same_key_changed_caption_or_mp4_hard_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            kwargs = self.kwargs()
            spec = r33.build_prepare_spec(**kwargs)
            kwargs["explicit_idempotency_key"] = spec["idempotencyKey"]
            ledger = r33.prepare_transaction(root / "tx.jsonl", **kwargs)

            changed_caption = self.kwargs()
            changed_caption["caption"] = "Changed caption"
            changed_caption["explicit_idempotency_key"] = ledger.state["idempotencyKey"]
            with self.assertRaises(r33.ReplayConflict):
                r33.prepare_transaction(root / "tx.jsonl", **changed_caption)

            changed_media = self.kwargs()
            changed_media["handoff"] = copy.deepcopy(changed_media["handoff"])
            changed_media["upstream_state"] = copy.deepcopy(changed_media["upstream_state"])
            changed_media["handoff"]["finalArtifact"]["sha256"] = "9" * 64
            changed_media["media_metadata"] = copy.deepcopy(changed_media["media_metadata"])
            changed_media["media_metadata"]["sha256"] = "9" * 64
            material = copy.deepcopy(changed_media["handoff"])
            material["handoffDigest"] = ""
            changed_media["handoff"]["handoffDigest"] = r33._sha(material)
            changed_media["upstream_state"]["publishHandoffDigest"] = changed_media["handoff"]["handoffDigest"]
            changed_media["explicit_idempotency_key"] = ledger.state["idempotencyKey"]
            with self.assertRaises(r33.ReplayConflict):
                r33.prepare_transaction(root / "tx.jsonl", **changed_media)

    def test_timeout_before_dispatch_is_safe_to_resume(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            timeout = r33.FakeProviderHarness("timeout_before_dispatch")
            state = r33.commit_transaction(ledger, timeout)
            self.assertEqual(state["state"], "COMMIT_ELIGIBLE")
            self.assertEqual(timeout.effect_count, 0)
            self.assertEqual(state["commit"]["attemptNumber"], 1)
            success = r33.FakeProviderHarness("clean_success")
            state = r33.commit_transaction(ledger, success)
            self.assertEqual(state["state"], "COMMITTED")
            self.assertEqual(state["commit"]["attemptNumber"], 2)
            self.assertEqual(success.effect_count, 1)

    def test_timeout_after_dispatch_requires_read_only_reconcile_and_never_blind_retries(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("timeout_after_dispatch")
            state = r33.commit_transaction(ledger, provider)
            self.assertEqual(state["state"], "RECONCILIATION_REQUIRED")
            calls = provider.commit_calls
            effects = provider.effect_count
            restarted = r33.TransactionLedger(ledger.path)
            with self.assertRaises(r33.ReconciliationRequired):
                r33.commit_transaction(restarted, provider)
            self.assertEqual(provider.commit_calls, calls)
            self.assertEqual(provider.effect_count, effects)
            committed = r33.reconcile_transaction(restarted, provider)
            self.assertEqual(committed["state"], "COMMITTED")
            self.assertTrue(committed["commit"]["externalPostId"])

    def test_unknown_no_lookup_stays_reconciliation_required(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("unknown_no_lookup")
            r33.commit_transaction(ledger, provider)
            calls = provider.commit_calls
            state = r33.reconcile_transaction(ledger, provider)
            self.assertEqual(state["state"], "RECONCILIATION_REQUIRED")
            self.assertFalse(r33.transaction_status(ledger)["blindRetryPermitted"])
            with self.assertRaises(r33.ReconciliationRequired):
                r33.commit_transaction(ledger, provider)
            self.assertEqual(provider.commit_calls, calls)

    def test_provider_duplicate_already_exists_is_confirmed_without_new_effect(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            provider = r33.FakeProviderHarness("duplicate_confirmed")
            state = r33.commit_transaction(ledger, provider)
            self.assertEqual(state["state"], "COMMITTED")
            self.assertEqual(state["commit"]["providerOutcome"], "duplicate_confirmed")
            self.assertEqual(provider.effect_count, 0)
            self.assertIsNotNone(state["commit"]["externalPostId"])

    def test_fake_provider_post_id_with_stale_proof_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            with self.assertRaises(r33.OutcomeProofError):
                r33.commit_transaction(ledger, ForgedPostIdAdapter())
            self.assertNotEqual(ledger.state["state"], "COMMITTED")

    def test_restart_at_every_state_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = self.prepared(root)
            ledger = r33.TransactionLedger(ledger.path)
            r33.validate_prepared(ledger)
            ledger = r33.TransactionLedger(ledger.path)
            r33.mark_commit_eligible(ledger)
            ledger = r33.TransactionLedger(ledger.path)
            r33.begin_commit(ledger)
            ledger = r33.TransactionLedger(ledger.path)
            self.assertEqual(ledger.state["state"], "COMMITTING")
            self.assertFalse(ledger.state["commit"]["invocationStarted"])
            provider = r33.FakeProviderHarness("clean_success")
            r33.commit_transaction(ledger, provider)
            ledger = r33.TransactionLedger(ledger.path)
            self.assertEqual(ledger.state["state"], "COMMITTED")
            self.assertEqual(provider.effect_count, 1)

    def test_restart_after_invocation_intent_is_conservatively_reconciled(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            r33.begin_commit(ledger)
            state = copy.deepcopy(ledger.state)
            invoking = copy.deepcopy(state)
            invoking["commit"]["invocationStarted"] = True
            invoking["blockers"] = [{"code": "PROVIDER_INVOCATION_IN_PROGRESS", "blindRetryForbiddenOnRestart": True}]
            ledger._append(
                event_key=f"provider-invocation-intent:{state['commit']['attemptNumber']}",
                event_type="PROVIDER_INVOCATION_INTENT",
                operation_id=state["commit"]["attemptId"],
                request={
                    "transactionId": state["transactionId"],
                    "idempotencyKey": state["idempotencyKey"],
                    "requestDigest": state["requestDigest"],
                    "networkEnabled": False,
                },
                new_state=invoking,
                input_artifacts={"requestDigest": state["requestDigest"], "winnerSha256": state["winner"]["sha256"]},
                output_artifacts={},
                timestamp_metadata="2026-10-04T00:00:05Z",
            )
            restarted = r33.TransactionLedger(ledger.path)
            provider = r33.FakeProviderHarness("clean_success")
            with self.assertRaises(r33.ReconciliationRequired):
                r33.commit_transaction(restarted, provider)
            self.assertEqual(provider.commit_calls, 0)
            self.assertEqual(restarted.state["state"], "RECONCILIATION_REQUIRED")

    def test_abort_rules_and_authoritative_absence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prepared = self.prepared(root, name="prepared.jsonl")
            self.assertEqual(r33.abort_transaction(prepared, reason="operator stop")["state"], "ABORTED")

            validated = self.prepared(root, name="validated.jsonl")
            r33.validate_prepared(validated)
            self.assertEqual(r33.abort_transaction(validated, reason="operator stop")["state"], "ABORTED")

            committing = self.eligible(root, name="committing.jsonl")
            r33.begin_commit(committing)
            with self.assertRaises(r33.InvalidTransition):
                r33.abort_transaction(committing, reason="unsafe stop")

    def test_schedule_change_requires_new_revision_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = self.prepared(root)
            revision = r33.schedule_revision_spec(
                ledger,
                new_planned_publish_at="2026-10-06T12:00:00Z",
            )
            self.assertTrue(revision["requiresNewLedger"])
            self.assertEqual(revision["revision"], 1)
            self.assertNotEqual(revision["newTransactionId"], ledger.state["transactionId"])
            self.assertNotEqual(revision["newIdempotencyKey"], ledger.state["idempotencyKey"])

            changed = self.kwargs()
            changed["planned_publish_at"] = "2026-10-06T12:00:00Z"
            changed["explicit_idempotency_key"] = ledger.state["idempotencyKey"]
            with self.assertRaises(r33.ReplayConflict):
                r33.prepare_transaction(root / "tx.jsonl", **changed)

    def test_multi_platform_partial_success_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            instagram = self.eligible(root, "instagram_reels", "ig.jsonl")
            tiktok = self.eligible(root, "tiktok", "tt.jsonl")
            youtube = self.prepared(root, "youtube_shorts", "yt.jsonl")
            r33.validate_prepared(youtube)
            r33.abort_transaction(youtube, reason="operator disabled youtube")

            igp = r33.FakeProviderHarness("clean_success")
            ttp = r33.FakeProviderHarness("unknown_no_lookup")
            r33.commit_transaction(instagram, igp)
            r33.commit_transaction(tiktok, ttp)
            batch = r33.batch_status([instagram, tiktok, youtube])
            self.assertEqual(batch["committedPlatforms"], ["instagram_reels"])
            self.assertEqual(batch["blockedPlatforms"], ["tiktok"])
            self.assertEqual(batch["abortedPlatforms"], ["youtube_shorts"])
            self.assertEqual(igp.effect_count, 1)
            calls = igp.commit_calls
            with self.assertRaises(r33.ReconciliationRequired):
                r33.commit_transaction(tiktok, ttp)
            self.assertEqual(igp.commit_calls, calls)

    def test_live_adapter_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.eligible(Path(td))
            with self.assertRaises(r33.LivePublishForbidden):
                r33.commit_transaction(ledger, NotFakeAdapter())
            self.assertEqual(ledger.state["state"], "COMMITTING")
            self.assertFalse(ledger.state["commit"]["invocationStarted"])

    def test_secret_bearing_config_is_rejected(self):
        kwargs = self.kwargs()
        kwargs["publish_policy"] = {"access_token": "never-store-this"}
        with self.assertRaises(r33.PublishTransactionError):
            r33.build_prepare_spec(**kwargs)

    def test_deterministic_rehearsal_proves_reconciliation_and_no_live_publish(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = r33.run_rehearsal(a)
            second = r33.run_rehearsal(b)
            self.assertEqual(first["reportDigest"], second["reportDigest"])
            self.assertEqual(first["state"], "SOURCE_READY_NO_LIVE_PUBLISH")
            self.assertEqual(first["cleanSuccess"]["state"], "COMMITTED")
            self.assertEqual(first["timeoutAfterDispatchReconciled"]["state"], "COMMITTED")
            self.assertEqual(first["unknownNoLookup"]["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(first["timeoutBeforeDispatchSafeRetry"]["state"], "COMMITTED")
            self.assertFalse(first["unknownOutcomeBlindRetryAttempted"])
            self.assertEqual(first["effects"]["realProvider"], 0)
            self.assertFalse(first["networkUsed"])
            self.assertFalse(first["livePublish"])
            self.assertFalse(first["credentialsStored"])
            evidence = json.loads(
                (Path(a) / "evidence-manifest.r33.json").read_text(encoding="utf-8")
            )
            self.assertTrue(evidence["unknownOutcomeBlindRetryForbidden"])
            self.assertEqual(evidence["realProviderEffects"], 0)

    def test_status_reports_allowed_action_and_real_side_effect_false(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.prepared(Path(td))
            status = r33.transaction_status(ledger)
            self.assertEqual(status["allowedNextAction"], "VALIDATE_OR_ABORT")
            self.assertFalse(status["realSideEffectPermitted"])
            self.assertFalse(status["networkPermitted"])


if __name__ == "__main__":
    unittest.main()
