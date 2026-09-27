from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.checkpoint import (
    export_campaign_checkpoint,
    import_campaign_checkpoint,
    load_campaign_checkpoint,
)
from creator_orchestrator.orchestrator import JsonJobStore
from creator_orchestrator.release_authorization import (
    RELEASE_AUTHORIZATION_VERSION,
    RELEASE_DRY_RUN_PLAN_VERSION,
    RELEASE_DRY_RUN_RESULT_VERSION,
    RELEASE_SIDE_EFFECT_RECEIPT_VERSION,
    FakeLocalReleaseAdapter,
    LiveReleaseDisabled,
    ReleaseArtifactMutationError,
    ReleaseAuthorizationConflictError,
    ReleaseAuthorizationDenied,
    ReleaseAuthorizationError,
    ReleaseAuthorizationExpired,
    ReleaseAuthorizationLedger,
    ReleaseAuthorizationRevoked,
    ReleaseBoundaryCrash,
    ReleaseDestinationScopeError,
    ReleaseExternalInputRequired,
    validate_release_authorization,
)

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_CHECKPOINT = ROOT / "fixtures" / "checkpoints" / "10_terminal.checkpoint.json"
SOURCE_CONFIG = ROOT / "fixtures" / "campaign.checkpoint.v1.source.json"
DRY_RUN_FIXTURE = ROOT / "fixtures" / "release.authorization.v1.dry_run.expected.json"

CREATED_AT = "2026-09-27T12:00:00+00:00"
DECIDED_AT = "2026-09-27T12:05:00+00:00"
EXPIRES_AT = "2026-09-28T12:05:00+00:00"
EXECUTE_AT = "2026-09-27T12:10:00+00:00"
SCOPE = {
    "provider": "local-release-sim",
    "destination": "sim://release/channel/demo",
    "action": "release",
}


class CrashOnce:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.triggered = False

    def __call__(self, name, _payload) -> None:
        if name == self.boundary and not self.triggered:
            self.triggered = True
            raise ReleaseBoundaryCrash(name)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _release_setup(root: str, *, boundary_hook=None):
    checkpoint = load_campaign_checkpoint(TERMINAL_CHECKPOINT, repo_root=ROOT)
    imported = import_campaign_checkpoint(checkpoint, root, repo_root=ROOT)
    assert imported.status in {"imported", "duplicate"}
    job_id = checkpoint["jobs"][0]["jobId"]
    job_store = JsonJobStore(Path(root) / "jobs")
    job = job_store.load(job_id)
    queue = next(
        artifact for artifact in job.artifacts if artifact.kind == "publish_queue_item"
    )
    ledger = ReleaseAuthorizationLedger(
        Path(root) / "release-authorizations",
        job_store,
        boundary_hook=boundary_hook,
    )
    return checkpoint, job_store, ledger, job_id, queue.id


def _prepare(ledger, campaign_id, job_id, queue_id):
    return ledger.prepare_request(
        campaign_id=campaign_id,
        job_id=job_id,
        queued_artifact_id=queue_id,
        destination_scope=SCOPE,
        created_at=CREATED_AT,
    )


def _decision(
    request_receipt,
    *,
    decision="approved",
    decision_id="decision-001",
    idempotency_key="human-decision-001",
    authorization_id="authorization-001",
    expires_at=EXPIRES_AT,
    source="external",
    scope=None,
):
    request = request_receipt.request
    if decision == "denied":
        authorization_id = None
        expires_at = None
    return {
        "contractVersion": RELEASE_AUTHORIZATION_VERSION,
        "decisionId": decision_id,
        "idempotencyKey": idempotency_key,
        "requestId": request["requestId"],
        "campaignId": request["campaignId"],
        "candidateId": request["candidateId"],
        "artifactId": request["artifactId"],
        "artifactHash": request["artifactHash"],
        "lineageHash": request["lineageHash"],
        "destinationScope": copy.deepcopy(scope or request["destinationScope"]),
        "decision": decision,
        "authorizationId": authorization_id,
        "expiresAt": expires_at,
        "decidedAt": DECIDED_AT,
        "decisionSource": source,
        "approverRef": "human:release-reviewer",
    }


class ReleaseAuthorizationTests(unittest.TestCase):
    def test_pending_denied_expired_revoked_and_wrong_scope_have_zero_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            adapter = FakeLocalReleaseAdapter()

            with self.assertRaises(ReleaseAuthorizationDenied):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(adapter.accepted_side_effects, 0)

            denied = _decision(
                request,
                decision="denied",
                decision_id="decision-denied",
                idempotency_key="human-denied-001",
            )
            ledger.record_external_decision(denied)
            with self.assertRaises(ReleaseAuthorizationDenied):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)

        with tempfile.TemporaryDirectory() as td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            adapter = FakeLocalReleaseAdapter()
            approved = _decision(request)
            ledger.record_external_decision(approved)

            wrong_scope = {
                **SCOPE,
                "destination": "sim://release/channel/wrong",
            }
            with self.assertRaises(ReleaseDestinationScopeError):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=wrong_scope,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            with self.assertRaises(ReleaseAuthorizationExpired):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now="2026-09-29T00:00:00+00:00",
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)

            revoked = _decision(
                request,
                decision="revoked",
                decision_id="decision-revoke",
                idempotency_key="human-revoke-001",
                authorization_id=approved["authorizationId"],
                expires_at=approved["expiresAt"],
            )
            ledger.record_external_decision(revoked)
            self.assertEqual(ledger.snapshot(request.request_id)["state"], "revoked")
            with self.assertRaises(ReleaseAuthorizationRevoked):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(adapter.accepted_side_effects, 0)

    def test_approval_is_explicit_external_input_and_strict_schema(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            internal = _decision(request, source="creator")
            with self.assertRaises(ReleaseExternalInputRequired):
                ledger.record_external_decision(internal)

            future = _decision(request)
            future["contractVersion"] = "release.authorization.v2"
            with self.assertRaises(ReleaseAuthorizationError):
                validate_release_authorization(future)

            extra = _decision(request)
            extra["unexpected"] = True
            with self.assertRaises(ReleaseAuthorizationError):
                validate_release_authorization(extra)

            wrong_scope = _decision(
                request,
                decision_id="decision-wrong-scope",
                idempotency_key="human-wrong-scope-001",
                scope={
                    **SCOPE,
                    "destination": "sim://release/channel/other",
                },
            )
            with self.assertRaises(ReleaseDestinationScopeError):
                ledger.record_external_decision(wrong_scope)

    def test_duplicate_decision_is_idempotent_conflicting_reuse_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            approved = _decision(request)
            first = ledger.record_external_decision(approved)
            duplicate = ledger.record_external_decision(copy.deepcopy(approved))
            self.assertEqual(first.status, "committed")
            self.assertEqual(duplicate.status, "duplicate")
            self.assertEqual(duplicate.state, "approved")

            conflicting = copy.deepcopy(approved)
            conflicting["approverRef"] = "human:different-reviewer"
            with self.assertRaises(ReleaseAuthorizationConflictError):
                ledger.record_external_decision(conflicting)

    def test_artifact_mutation_after_approval_fails_before_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))

            job_path = job_store.directory / f"{job_id}.json"
            raw = _load_json(job_path)
            target = next(item for item in raw["artifacts"] if item["id"] == queue_id)
            target["metadata"]["tampered"] = True
            job_path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")

            adapter = FakeLocalReleaseAdapter()
            with self.assertRaises(ReleaseArtifactMutationError):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)

    def test_live_adapter_mode_is_disabled_even_with_valid_approval(self):
        class NotLocal:
            execution_mode = "external-live"
            provider = "local-release-sim"

            def __init__(self):
                self.calls = 0

            def release(self, plan, *, idempotency_key):
                self.calls += 1
                return {}

        with tempfile.TemporaryDirectory() as td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))
            adapter = NotLocal()
            with self.assertRaises(LiveReleaseDisabled):
                ledger.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)

    def test_dry_run_plan_and_result_are_deterministic_and_side_effect_free(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            adapter = FakeLocalReleaseAdapter()
            first_plan, first_result = ledger.build_dry_run(
                request.request_id,
                destination_scope=SCOPE,
                planned_at="2026-09-27T12:03:00+00:00",
            )
            second_plan, second_result = ledger.build_dry_run(
                request.request_id,
                destination_scope=SCOPE,
                planned_at="2026-09-27T12:03:00+00:00",
            )
            self.assertEqual(first_plan, second_plan)
            self.assertEqual(first_result, second_result)
            self.assertEqual(
                first_plan["contractVersion"],
                RELEASE_DRY_RUN_PLAN_VERSION,
            )
            self.assertEqual(
                first_result["contractVersion"],
                RELEASE_DRY_RUN_RESULT_VERSION,
            )
            self.assertFalse(first_plan["externalSideEffects"])
            self.assertEqual(first_result["externalSideEffects"], 0)
            self.assertEqual(
                {"plan": first_plan, "result": first_result},
                _load_json(DRY_RUN_FIXTURE),
            )
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(adapter.accepted_side_effects, 0)

    def test_request_commit_crash_recovers_same_pending_request(self):
        with tempfile.TemporaryDirectory() as td:
            crash = CrashOnce("after_request_commit")
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(
                td,
                boundary_hook=crash,
            )
            with self.assertRaises(ReleaseBoundaryCrash):
                _prepare(
                    ledger,
                    checkpoint["campaignIdentity"]["campaignId"],
                    job_id,
                    queue_id,
                )

            recovered = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
            )
            job = job_store.load(job_id)
            request_id = next(
                artifact.metadata["requestId"]
                for artifact in job.artifacts
                if artifact.kind == "release_approval_request"
            )
            snapshot = recovered.snapshot(request_id)
            self.assertEqual(snapshot["state"], "pending")
            duplicate = recovered.prepare_request(
                campaign_id=checkpoint["campaignIdentity"]["campaignId"],
                job_id=job_id,
                queued_artifact_id=queue_id,
                destination_scope=SCOPE,
                created_at=CREATED_AT,
            )
            self.assertEqual(duplicate.status, "duplicate")
            self.assertEqual(duplicate.request_id, request_id)
            self.assertEqual(
                sum(a.kind == "release_approval_request" for a in job_store.load(job_id).artifacts),
                1,
            )

    def test_approval_commit_crash_recovers_same_approved_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            approved = _decision(request)
            crash = CrashOnce("after_approval_commit")
            crashing = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
                boundary_hook=crash,
            )
            with self.assertRaises(ReleaseBoundaryCrash):
                crashing.record_external_decision(approved)

            recovered = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
            )
            self.assertEqual(recovered.snapshot(request.request_id)["state"], "approved")
            duplicate = recovered.record_external_decision(copy.deepcopy(approved))
            self.assertEqual(duplicate.status, "duplicate")

    def test_final_check_crash_preserves_prepared_execution_and_never_submits_before_restart(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))
            adapter = FakeLocalReleaseAdapter()
            crash = CrashOnce("after_final_authorization_check")
            crashing = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
                boundary_hook=crash,
            )
            with self.assertRaises(ReleaseBoundaryCrash):
                crashing.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(
                crashing.snapshot(request.request_id)["executionState"],
                "prepared",
            )

            recovered = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
            )
            result = recovered.execute_authorized(
                request.request_id,
                destination_scope=SCOPE,
                now=EXECUTE_AT,
                adapter=adapter,
            )
            self.assertEqual(result.status, "committed")
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.accepted_side_effects, 1)

    def test_side_effect_crash_replays_same_idempotency_and_commits_one_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))
            adapter = FakeLocalReleaseAdapter()
            crash = CrashOnce("after_side_effect_before_receipt_commit")
            crashing = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
                boundary_hook=crash,
            )
            with self.assertRaises(ReleaseBoundaryCrash):
                crashing.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.accepted_side_effects, 1)
            self.assertEqual(
                crashing.snapshot(request.request_id)["executionState"],
                "prepared",
            )

            recovered = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
            )
            result = recovered.execute_authorized(
                request.request_id,
                destination_scope=SCOPE,
                now=EXECUTE_AT,
                adapter=adapter,
            )
            self.assertEqual(result.status, "committed")
            self.assertEqual(
                result.receipt["contractVersion"],
                RELEASE_SIDE_EFFECT_RECEIPT_VERSION,
            )
            self.assertEqual(adapter.calls, 2)
            self.assertEqual(adapter.accepted_side_effects, 1)
            snapshot = recovered.snapshot(request.request_id)
            self.assertEqual(snapshot["executionState"], "committed")
            self.assertEqual(
                sum(
                    event["eventType"] == "receipt_committed"
                    for event in snapshot["events"]
                ),
                1,
            )

    def test_receipt_commit_crash_restart_is_noop_and_does_not_call_adapter_again(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))
            adapter = FakeLocalReleaseAdapter()
            crash = CrashOnce("after_receipt_commit")
            crashing = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
                boundary_hook=crash,
            )
            with self.assertRaises(ReleaseBoundaryCrash):
                crashing.execute_authorized(
                    request.request_id,
                    destination_scope=SCOPE,
                    now=EXECUTE_AT,
                    adapter=adapter,
                )
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.accepted_side_effects, 1)

            recovered = ReleaseAuthorizationLedger(
                Path(td) / "release-authorizations",
                job_store,
            )
            duplicate = recovered.execute_authorized(
                request.request_id,
                destination_scope=SCOPE,
                now=EXECUTE_AT,
                adapter=adapter,
            )
            self.assertEqual(duplicate.status, "duplicate")
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.accepted_side_effects, 1)

    def test_checkpoint_round_trip_preserves_pending_approved_and_revoked_authorizations(self):
        for state in ("pending", "approved", "revoked"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as source_td, tempfile.TemporaryDirectory() as restored_td:
                checkpoint, _, ledger, job_id, queue_id = _release_setup(source_td)
                request = _prepare(
                    ledger,
                    checkpoint["campaignIdentity"]["campaignId"],
                    job_id,
                    queue_id,
                )
                approved = _decision(request)
                if state in {"approved", "revoked"}:
                    ledger.record_external_decision(approved)
                if state == "revoked":
                    ledger.record_external_decision(
                        _decision(
                            request,
                            decision="revoked",
                            decision_id="decision-revoke",
                            idempotency_key="human-revoke-001",
                            authorization_id=approved["authorizationId"],
                            expires_at=approved["expiresAt"],
                        )
                    )

                config = _load_json(SOURCE_CONFIG)
                exported = export_campaign_checkpoint(
                    source_td,
                    campaign_id=config["campaignId"],
                    campaign_config=config,
                    repo_root=ROOT,
                )
                release_kinds = {
                    record["artifact"]["kind"]
                    for job in exported["jobs"]
                    for record in job["artifacts"]
                    if record["artifact"]["kind"].startswith("release_")
                }
                self.assertIn("release_candidate", release_kinds)
                self.assertIn("release_approval_request", release_kinds)
                if state != "pending":
                    self.assertIn("release_authorization_decision", release_kinds)

                import_campaign_checkpoint(
                    exported,
                    restored_td,
                    repo_root=ROOT,
                )
                restored_store = JsonJobStore(Path(restored_td) / "jobs")
                restored_ledger = ReleaseAuthorizationLedger(
                    Path(restored_td) / "release-authorizations",
                    restored_store,
                )
                restored = restored_ledger.snapshot(request.request_id)
                self.assertEqual(restored["state"], state)
                self.assertEqual(
                    restored["candidate"]["artifactHash"],
                    request.candidate["artifactHash"],
                )
                self.assertEqual(
                    restored["candidate"]["lineageHash"],
                    request.candidate["lineageHash"],
                )

    def test_checkpoint_export_rejects_tampered_authorization_parent_chain(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint, job_store, ledger, job_id, queue_id = _release_setup(td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))

            job_path = job_store.directory / f"{job_id}.json"
            raw = _load_json(job_path)
            candidate = next(
                item for item in raw["artifacts"] if item["kind"] == "release_candidate"
            )
            decision = next(
                item
                for item in raw["artifacts"]
                if item["kind"] == "release_authorization_decision"
            )
            decision["parents"] = [candidate["id"]]
            job_path.write_text(
                json.dumps(raw, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            config = _load_json(SOURCE_CONFIG)
            with self.assertRaises(ReleaseAuthorizationConflictError):
                export_campaign_checkpoint(
                    td,
                    campaign_id=config["campaignId"],
                    campaign_config=config,
                    repo_root=ROOT,
                )

    def test_checkpoint_approved_restore_can_execute_once_without_creator_approval(self):
        with tempfile.TemporaryDirectory() as source_td, tempfile.TemporaryDirectory() as restored_td:
            checkpoint, _, ledger, job_id, queue_id = _release_setup(source_td)
            request = _prepare(
                ledger,
                checkpoint["campaignIdentity"]["campaignId"],
                job_id,
                queue_id,
            )
            ledger.record_external_decision(_decision(request))
            config = _load_json(SOURCE_CONFIG)
            exported = export_campaign_checkpoint(
                source_td,
                campaign_id=config["campaignId"],
                campaign_config=config,
                repo_root=ROOT,
            )
            import_campaign_checkpoint(exported, restored_td, repo_root=ROOT)

            restored_store = JsonJobStore(Path(restored_td) / "jobs")
            restored_ledger = ReleaseAuthorizationLedger(
                Path(restored_td) / "release-authorizations",
                restored_store,
            )
            adapter = FakeLocalReleaseAdapter()
            committed = restored_ledger.execute_authorized(
                request.request_id,
                destination_scope=SCOPE,
                now=EXECUTE_AT,
                adapter=adapter,
            )
            duplicate = restored_ledger.execute_authorized(
                request.request_id,
                destination_scope=SCOPE,
                now=EXECUTE_AT,
                adapter=adapter,
            )
            self.assertEqual(committed.status, "committed")
            self.assertEqual(duplicate.status, "duplicate")
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.accepted_side_effects, 1)


if __name__ == "__main__":
    unittest.main()
