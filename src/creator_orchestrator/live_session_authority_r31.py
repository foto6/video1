from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import dynamic_live_review_loop as r28
from . import editor_publish_handoff as r23
from . import exact_dynamic_e2e_r29 as r29
from . import publish_execution as r21

CONTRACT_VERSION = "creator.live_session_authority.r31.v1"
JOURNAL_VERSION = "creator.live_session_authority_journal.r31.v1"
RESULT_VERSION = "creator.live_session_authority_result.r31.v1"
READINESS_VERSION = "creator.live_session_authority.r31.readiness.v1"
CREATOR_BASE_SHA = "50c17852a910c57f0894dcdb356d4d4923edb62b"
MAX_REEDIT_ROUNDS = 2
MAX_REVIEW_ROUNDS = 3

MEDIA_R23_AUTHORITY = {
    "repository": "foto6/video2",
    "producerSha": "78c6982a91d7e3e8c037cd9ce740ee077babdccc",
    "ciRunId": 37007419237,
    "contract": "media.review_session_package.r23.v1",
    "requestContract": "media.review_session_request.r23.v1",
    "blobs": {
        "contract": "63f863493054dea4ad0e2ebf3a996137602f8940",
        "schema": "92470d29b4a524ee6d797194f023a20c5b0dbaa6",
        "manifest": "09564e2d530a7315f58856c55b33bb52534e05c1",
        "implementation": "442ca6a46cbf107d29e6cd320fbb1a4cb38951b0",
        "exporter": "4799338cf58edee89bebd773eb544719cdb7f56d",
        "r19Implementation": "8110a086b5b319bd2601860845c6afbf97681921",
        "r19Runner": "7dbec612621aa42baaf2946cdac61d070e3ff41f",
        "applicationContract": "6b3350c5f1524fe49a49d5637514e2fb1a808bcf",
        "applicationManifest": "502c32253d370e9b4e3d53f4a70de317f89dd21b",
        "applicationSchema": "7cabf91f08ae11b68cc4a7eec88d358a46730289",
        "renderManifest": "945acb01ff0269d89b91463aa8d862f500e055b2",
        "renderSchema": "6353d32d785a2a1f1441bac4cfd0271b46b41d4a",
        "r20Contract": "bf650ad1552686d830965edad3fd62451ec0ec22",
        "r20Manifest": "da4af21cae8dffacb9cc303576fb08cb671e02ce",
        "r20Schema": "680aa69dfb595f31e93fb2bdfe0fdae2ac5ca25b",
        "r20Implementation": "cebaa1083d121844b5f7d5a78196d201f860d8a8",
        "r20Runner": "33c742f1e0314e462fb3e97337bf82883ec80f00",
        "r21Contract": "65358261775f0fcd2ab9e21f3f621aee977f29da",
        "r21Schema": "f04925e317d849434852e6b706533f909da47b22",
        "r21Implementation": "c6f556b8a177b6182d787356625094cdcad5a58e",
        "r21Runner": "c93e9a69de31b66189031932ccfa7f2c83cf043c",
        "r22Implementation": "31845333a6919364d81a7c2bc52aad1cb3ae82ed",
        "r22Materializer": "ade9e7181ecccf8e78e7dd966240618c872c9b26",
        "r22Verifier": "86b0a53eed6959af805fd0c492620eb037071e25",
        "r22Extractor": "dc45ee753480fc62249bd69ca209b994d680d08a",
    },
}

GROWTH_R28_AUTHORITY = {
    "repository": "foto6/video3",
    "producerSha": "629a2b9ddf59b84eee4e87b257c161dad42831dc",
    "ciRunId": 37006476121,
    "sessionContract": "growth.multiround_review_session.r28.v1",
    "roundResultContract": "growth.multiround_review_round_result.r28.v1",
    "selectedResultContract": "growth.creator_r30_selected_review_result.r28.v1",
    "authorityContract": "growth.multiround_session_authorities.r28.v1",
    "blobs": {
        "contract": "d7ec52f25fa1ff12e633f2ac3ba042265f93fe51",
        "roundResultSchema": "8eb405c42a4fea6a354cf7e3afcbd1774b542e75",
        "authorityProfiles": "5799d71528ec4e94f922b43cfb2db70b54e00206",
        "implementation": "8d75e086c5db161124d487a885b95999081e2521",
        "tests": "0d38e864f0d8e1d319c09f442c938cc51a930751",
    },
}

BRIDGE_R32_AUTHORITY = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "805bf628d3d2844549b54db1112736fae0200fc7",
    "ciRunId": 37006524677,
    "roundResultContract": "bridge.r32_live_review_session_round_result.v1",
    "journalContract": "bridge.r32_multiround_live_review_session_journal.v1",
    "sessionResultContract": "bridge.r32_multiround_live_review_session_result.v1",
    "blobs": {
        "roundResultSchema": "bff0985b243650ad5f40954234646da9c2d9c074",
        "journalSchema": "3b39faa9e8a1de5baf297f85640d36907aa06db1",
        "requestSchema": "3d6943806d7542eddb59813459e34136d5187050",
        "resultSchema": "152fd55f783a0798eab040bfb4fc84b2d5e01d01",
        "implementation": "91cf49ce6e856c5d975a4c7c9daef88b13165fa1",
        "driver": "df2b27b1bc2240fc2ba651404b13ca202d0f5ed7",
        "fixture": "e052c0ba8ea26cec7a26d8ab9340d744e5d69fbe",
    },
}

MEDIA_R23_RUNTIME_PROFILE = {
    "authorityVersion": r28.AUTHORITY_VERSION,
    "family": "media_r19_r20_editorial_dynamic_review",
    "repository": "foto6/video2",
    "producerSha": MEDIA_R23_AUTHORITY["producerSha"],
    "ciRunId": MEDIA_R23_AUTHORITY["ciRunId"],
    "applicationContract": "media.editorial_reedit_application.v1",
    "applicationContractBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["applicationContract"],
    "applicationManifestBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["applicationManifest"],
    "applicationSchemaBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["applicationSchema"],
    "r19ImplementationBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r19Implementation"],
    "r19RunnerBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r19Runner"],
    "renderExportContract": "media.render_export.v1",
    "renderExportManifestBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["renderManifest"],
    "renderExportSchemaBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["renderSchema"],
    "dynamicPackageContract": "media.dynamic_review_package.r20.v1",
    "dynamicRequestContract": "media.dynamic_review_request.r20.v1",
    "dynamicBridgeHandoffContract": "media.bridge_live_review_handoff.r20.v1",
    "dynamicContractBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r20Contract"],
    "dynamicManifestBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r20Manifest"],
    "dynamicSchemaBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r20Schema"],
    "dynamicImplementationBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r20Implementation"],
    "dynamicRunnerBlobSha1": MEDIA_R23_AUTHORITY["blobs"]["r20Runner"],
    "testFixture": False,
}


class R31Error(ValueError):
    pass


class AuthorityDrift(R31Error):
    pass


class SessionDrift(R31Error):
    pass


class ReplayConflict(R31Error):
    pass


class RoundOverflow(R31Error):
    pass


class PackageDrift(R31Error):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _hex(value: Any, size: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != size or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise R31Error(f"{field} must be lowercase {size}-hex")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R31Error(f"{field} must be positive integer")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R31Error(f"{field} must be non-empty")
    return value


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_blob_sha(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def _git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(root).resolve(),
        text=True,
    ).strip()


def authority_profiles() -> dict[str, Any]:
    value = {
        "contractVersion": "creator.live_session_authorities.r31.v1",
        "mediaR23": _clone(MEDIA_R23_AUTHORITY),
        "growthR28": _clone(GROWTH_R28_AUTHORITY),
        "bridgeR32": _clone(BRIDGE_R32_AUTHORITY),
    }
    value["authorityDigest"] = _sha(value)
    return value


def validate_media_authority_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if value != MEDIA_R23_AUTHORITY:
        raise AuthorityDrift("Media R23 authority profile drift")
    return _clone(value)


def _verify_checkout(
    root: Path,
    *,
    producer_sha: str,
    checks: Mapping[str, tuple[str, str]],
    label: str,
) -> dict[str, Any]:
    root = Path(root).resolve()
    if _git_head(root) != producer_sha:
        raise AuthorityDrift(f"{label} producer SHA drift")
    observed = {}
    for key, (rel, expected) in checks.items():
        path = root / rel
        if not path.is_file():
            raise AuthorityDrift(f"{label} missing {rel}")
        actual = _git_blob_sha(path)
        if actual != expected:
            raise AuthorityDrift(f"{label} blob drift: {key}")
        observed[key] = actual
    return {"checkoutSha": producer_sha, "observedBlobs": observed}


def verify_media_r23_checkout(root: Path) -> dict[str, Any]:
    b = MEDIA_R23_AUTHORITY["blobs"]
    result = _verify_checkout(
        root,
        producer_sha=MEDIA_R23_AUTHORITY["producerSha"],
        label="Media R23",
        checks={
            "contract": ("conformance/media.review_session_package.r23.v1/contract.json", b["contract"]),
            "schema": ("conformance/media.review_session_package.r23.v1/schema.json", b["schema"]),
            "manifest": ("conformance/media.review_session_package.r23.v1/manifest.json", b["manifest"]),
            "implementation": ("src/review-session-r23.js", b["implementation"]),
            "exporter": ("tools/export-r23-next-round.mjs", b["exporter"]),
            "r19Implementation": ("src/editorial-reedit-r19.js", b["r19Implementation"]),
            "r19Runner": ("tools/run-r19-editorial-reedit.mjs", b["r19Runner"]),
            "r21Implementation": ("src/review-round-r21.js", b["r21Implementation"]),
            "r22Implementation": ("src/live-review-artifact-r22.js", b["r22Implementation"]),
        },
    )
    r28.verify_media_checkout(root, MEDIA_R23_RUNTIME_PROFILE)
    result["profileDigest"] = _sha(MEDIA_R23_AUTHORITY)
    return result


def verify_growth_r28_checkout(root: Path) -> dict[str, Any]:
    b = GROWTH_R28_AUTHORITY["blobs"]
    result = _verify_checkout(
        root,
        producer_sha=GROWTH_R28_AUTHORITY["producerSha"],
        label="Growth R28",
        checks={
            "contract": ("conformance/growth.multiround_session_ingest.r28.v1/contract.json", b["contract"]),
            "roundResultSchema": ("conformance/growth.multiround_session_ingest.r28.v1/round-result.schema.json", b["roundResultSchema"]),
            "authorityProfiles": ("conformance/growth.multiround_session_ingest.r28.v1/authority-profiles.json", b["authorityProfiles"]),
            "implementation": ("growth_analytics/multiround_session_ingest_r28.py", b["implementation"]),
        },
    )
    result["profileDigest"] = _sha(GROWTH_R28_AUTHORITY)
    return result


def verify_bridge_r32_checkout(root: Path) -> dict[str, Any]:
    b = BRIDGE_R32_AUTHORITY["blobs"]
    result = _verify_checkout(
        root,
        producer_sha=BRIDGE_R32_AUTHORITY["producerSha"],
        label="Bridge R32",
        checks={
            "roundResultSchema": ("app/contracts/r32/bridge.r32_live_review_session_round_result.v1.schema.json", b["roundResultSchema"]),
            "journalSchema": ("app/contracts/r32/bridge.r32_multiround_live_review_session_journal.v1.schema.json", b["journalSchema"]),
            "requestSchema": ("app/contracts/r32/bridge.r32_multiround_live_review_session_request.v1.schema.json", b["requestSchema"]),
            "resultSchema": ("app/contracts/r32/bridge.r32_multiround_live_review_session_result.v1.schema.json", b["resultSchema"]),
            "implementation": ("app/r32-multiround-session.js", b["implementation"]),
            "driver": ("app/r32-session-driver.js", b["driver"]),
        },
    )
    result["profileDigest"] = _sha(BRIDGE_R32_AUTHORITY)
    return result


def validate_bridge_r32_round(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract", "state", "sessionId", "round", "conversation",
        "packageDigest", "promptDigest", "attachments", "requestId",
        "operationId", "responseDigest", "model_evidence",
        "human_ground_truth",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise SessionDrift("Bridge R32 round result fields missing")
    if value["contract"] != BRIDGE_R32_AUTHORITY["roundResultContract"]:
        raise AuthorityDrift("Bridge R32 round contract drift")
    if value["state"] != "LIVE_REVIEW_PASS":
        raise SessionDrift("Bridge R32 round is not LIVE_REVIEW_PASS")
    round_index = value["round"]
    if isinstance(round_index, bool) or not isinstance(round_index, int) or not 0 <= round_index <= 2:
        raise RoundOverflow("Bridge R32 round must be 0..2")
    for key in ("packageDigest", "promptDigest", "responseDigest"):
        _hex(value[key], 64, f"bridge.{key}")
    if "captureDigest" in value:
        _hex(value["captureDigest"], 64, "bridge.captureDigest")
    if value["model_evidence"] is not True or value["human_ground_truth"] is not False:
        raise SessionDrift("Bridge R32 evidence boundary drift")
    if value.get("retryUploadAuthorized", False) is not False or value.get("retrySendAuthorized", False) is not False:
        raise SessionDrift("Bridge R32 retry authorization drift")
    if not isinstance(value["attachments"], list) or len(value["attachments"]) != 2:
        raise SessionDrift("Bridge R32 requires exactly two attachments")
    for item in value["attachments"]:
        if not isinstance(item, Mapping):
            raise SessionDrift("Bridge R32 attachment invalid")
        _hex(item.get("sha256"), 64, "bridge.attachment.sha256")
        _positive(item.get("size"), "bridge.attachment.size")
    _nonempty(value["requestId"], "bridge.requestId")
    _nonempty(value["operationId"], "bridge.operationId")
    return _clone(value)


def validate_growth_round_result(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "round_result_id", "round_result_digest",
        "session_id", "review_round", "package", "capture", "pairwise",
        "outcome", "selected_result", "candidate_envelopes",
        "terminal_winner", "creator_executable_handoff_emitted",
        "evidence_boundary",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise SessionDrift("Growth R28 round result fields mismatch")
    if value["contract_version"] != GROWTH_R28_AUTHORITY["roundResultContract"]:
        raise AuthorityDrift("Growth R28 round result contract drift")
    round_index = value["review_round"]
    if isinstance(round_index, bool) or not isinstance(round_index, int) or not 0 <= round_index <= 2:
        raise RoundOverflow("Growth R28 review round must be 0..2")
    material = copy.deepcopy(value)
    digest = material["round_result_digest"]
    material["round_result_digest"] = ""
    _hex(digest, 64, "growth.round_result_digest")
    if _sha(material) != digest:
        raise SessionDrift("Growth R28 round result digest mismatch")
    if value["round_result_id"] != "gr28rr1:" + _sha({
        "session_id": value["session_id"],
        "review_round": round_index,
        "capture_digest": value["capture"]["capture_digest"],
        "package_digest": value["package"]["package_digest"],
    }):
        raise SessionDrift("Growth R28 round result identity drift")
    for key in ("operator_manifest_sha256", "archive_sha256", "package_digest", "sealed_mapping_digest", "prompt_digest"):
        _hex(value["package"].get(key), 64, f"growth.package.{key}")
    for key in ("capture_digest", "assistant_response_digest"):
        _hex(value["capture"].get(key), 64, f"growth.capture.{key}")
    if value["outcome"] not in {"winner", "tie", "insufficient_evidence", "human_review"}:
        raise SessionDrift("Growth R28 outcome invalid")
    if value["creator_executable_handoff_emitted"] is not True:
        raise SessionDrift("Growth R28 did not emit Creator handoff")
    if value["evidence_boundary"] != {
        "model_evidence": True,
        "human_ground_truth": False,
        "human_rating_evidence": False,
        "human_parity_inferred": False,
        "browser_mutation": False,
        "provider_mutation": False,
    }:
        raise SessionDrift("Growth R28 evidence boundary drift")
    selected = value["selected_result"]
    if selected is not None:
        if selected.get("contract_version") != GROWTH_R28_AUTHORITY["selectedResultContract"]:
            raise SessionDrift("Growth R28 selected result contract drift")
        sm = copy.deepcopy(selected)
        sd = sm["result_digest"]
        sm["result_digest"] = ""
        _hex(sd, 64, "growth.selected_result.result_digest")
        if _sha(sm) != sd:
            raise SessionDrift("Growth R28 selected result digest mismatch")
        if selected.get("review_round") != round_index:
            raise SessionDrift("Growth R28 selected result round drift")
    return _clone(value)


def load_growth_session_round(session_dir: Path, review_round: int) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(session_dir).resolve()
    ledger_path = root / "growth-r28-session-ledger.json"
    if not ledger_path.is_file():
        raise SessionDrift("Growth R28 session ledger missing")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    required = {"version", "session_id", "identity", "rounds", "requests", "closed", "terminal_round"}
    if not isinstance(ledger, Mapping) or set(ledger) != required:
        raise SessionDrift("Growth R28 session ledger fields mismatch")
    if ledger["version"] != "growth.multiround_review_session_ledger.r28.v1":
        raise AuthorityDrift("Growth R28 ledger version drift")
    if review_round < 0 or review_round > 2:
        raise RoundOverflow("review round must be 0..2")
    row = ledger["rounds"].get(str(review_round))
    if not isinstance(row, Mapping) or "round_result" not in row:
        raise SessionDrift("Growth R28 requested round absent from ledger")
    result = validate_growth_round_result(row["round_result"])
    if result["session_id"] != ledger["session_id"]:
        raise SessionDrift("Growth R28 ledger/session result identity drift")
    completed = sorted(int(k) for k in ledger["rounds"])
    if completed and completed != list(range(completed[-1] + 1)):
        raise RoundOverflow("Growth R28 ledger has round gap")
    if completed and completed[-1] > 2:
        raise RoundOverflow("Growth R28 ledger exceeds three review rounds")
    return _clone(ledger), result


def validate_session_continuity(
    *,
    growth_round: Mapping[str, Any],
    bridge_round: Mapping[str, Any],
    envelope: Mapping[str, Any],
    context: Mapping[str, Any],
    candidate_root: Path,
) -> dict[str, Any]:
    growth = validate_growth_round_result(growth_round)
    bridge = validate_bridge_r32_round(bridge_round)
    if bridge["round"] != growth["review_round"]:
        raise SessionDrift("Bridge/Growth review round drift")
    if bridge["packageDigest"] != growth["package"]["package_digest"]:
        raise PackageDrift("Bridge/Growth package digest drift")
    if bridge["promptDigest"] != growth["package"]["prompt_digest"]:
        raise PackageDrift("Bridge/Growth prompt digest drift")
    if bridge["responseDigest"] != growth["capture"]["assistant_response_digest"]:
        raise SessionDrift("Bridge/Growth response digest drift")
    if "captureDigest" in bridge and bridge["captureDigest"] != growth["capture"]["capture_digest"]:
        raise SessionDrift("Bridge/Growth capture digest drift")
    conversation = growth["capture"].get("conversation", {})
    if bridge["requestId"] != conversation.get("request_id") or bridge["operationId"] != conversation.get("operation_id"):
        raise SessionDrift("Bridge/Growth request/operation identity drift")
    bridge_conv = bridge.get("conversation", {})
    if isinstance(bridge_conv, Mapping) and conversation.get("conversation_id") and bridge_conv.get("conversationId") != conversation.get("conversation_id"):
        raise SessionDrift("Bridge/Growth conversation identity drift")

    envelope = r29.validate_growth_r26_envelope(envelope)
    candidate_id = envelope["candidate"]["candidate_id"]
    row = growth["candidate_envelopes"].get(candidate_id)
    if not isinstance(row, Mapping):
        raise SessionDrift("selected Creator envelope absent from Growth R28 result")
    expected = {
        "envelope_digest": envelope["envelope_digest"],
        "handoff_digest": envelope["candidate"]["handoff_digest"],
        "state": envelope["candidate"]["state"],
        "candidate_round": envelope["candidate"]["candidate_round"],
        "render_sha256": envelope["candidate"]["render_sha256"],
    }
    for key, val in expected.items():
        if row.get(key) != val:
            raise SessionDrift(f"Growth R28 envelope lineage drift: {key}")
    selected = growth["selected_result"]
    envelope_state = envelope["candidate"]["state"]
    if envelope_state == "winner":
        if (
            growth["outcome"] != "winner"
            or not isinstance(selected, Mapping)
            or selected.get("candidate_id") != candidate_id
        ):
            raise SessionDrift("Growth R28 winner selected-result drift")
    elif envelope_state == "targeted_reedit":
        if (
            growth["outcome"] != "winner"
            or not isinstance(selected, Mapping)
            or selected.get("candidate_id") == candidate_id
        ):
            raise SessionDrift(
                "Growth R28 targeted re-edit must be the non-selected reviewed candidate"
            )
    elif growth["outcome"] != envelope_state:
        raise SessionDrift("Growth R28 nonwinner outcome/envelope drift")
    if (
        envelope["review"]["review_round"] != growth["review_round"]
        or envelope["review"]["package_digest"] != growth["package"]["package_digest"]
        or envelope["review"]["sealed_mapping_digest"] != growth["package"]["sealed_mapping_digest"]
        or envelope["capture"]["capture_digest"] != growth["capture"]["capture_digest"]
        or envelope["capture"]["assistant_response_digest"]
        != growth["capture"]["assistant_response_digest"]
    ):
        raise SessionDrift(
            "Growth R28 round and selected Creator envelope capture/package lineage drift"
        )
    envelope = r29.validate_review_against_context(
        envelope, context, candidate_root=candidate_root
    )
    render_sha = context["candidate"]["renderSha256"]
    render_size = context["candidate"]["renderSize"]
    attachment_matches = [
        x for x in bridge["attachments"]
        if x.get("sha256") == render_sha and x.get("size") == render_size
    ]
    if not attachment_matches:
        raise SessionDrift("Bridge R32 attachments do not contain reviewed candidate bytes")
    return envelope


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                event = json.loads(line)
                material = dict(event)
                digest = material.pop("eventDigest")
                if (
                    event.get("journalVersion") != JOURNAL_VERSION
                    or event.get("sequence") != len(self.events) + 1
                    or _sha(material) != digest
                    or event.get("eventKey") in self.by_key
                ):
                    raise ReplayConflict("R31 journal corruption")
                self.events.append(event)
                self.by_key[event["eventKey"]] = event

    def append_once(self, key: str, kind: str, payload: Mapping[str, Any]) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if prior["kind"] != kind or prior["payload"] != normalized:
                raise ReplayConflict(f"conflicting replay for {key}")
            return "duplicate"
        event = {
            "journalVersion": JOURNAL_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": key,
            "kind": kind,
            "payload": normalized,
        }
        event["eventDigest"] = _sha(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self.by_key[key] = event
        return "committed"

    @property
    def digest(self) -> str:
        return _sha(self.events)

    @property
    def preterminal_digest(self) -> str:
        return _sha([x for x in self.events if x["eventKey"] != "terminal"])


def execute_media_r23_reedit(
    *,
    media_checkout: Path,
    candidate_root: Path,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = r29.validate_review_against_context(
        envelope, context, candidate_root=candidate_root
    )
    if envelope["candidate"]["state"] != "targeted_reedit":
        raise R31Error("real Media edit requires targeted_reedit")
    if envelope["review"]["review_round"] >= MAX_REEDIT_ROUNDS:
        raise RoundOverflow("third re-edit attempt rejected")
    verify_media_r23_checkout(media_checkout)
    review, adapter = r29._normalized_review(envelope, context)
    result = r28.execute_media_reedit(
        media_checkout=media_checkout,
        media_profile=MEDIA_R23_RUNTIME_PROFILE,
        candidate_root=candidate_root,
        context=context,
        review=review,
        out_dir=Path(candidate_root).resolve(),
    )
    application = result["application"]
    if (
        application.get("contractVersion") != "media.editorial_reedit_application.v1"
        or application.get("producer") != {
            "repository": MEDIA_R23_AUTHORITY["repository"],
            "sha": MEDIA_R23_AUTHORITY["producerSha"],
        }
        or application.get("handoff", {}).get("digest") != adapter["mediaR19CompatibilityHandoffDigest"]
        or application.get("qa", {}).get("technicalPassed") is not True
    ):
        raise SessionDrift("Media R23 re-edit application lineage drift")
    result["r31AdapterDigest"] = _sha({
        "growthEnvelopeDigest": envelope["envelope_digest"],
        "growthHandoffDigest": envelope["candidate"]["handoff_digest"],
        "mediaProducerSha": MEDIA_R23_AUTHORITY["producerSha"],
        "applicationDigest": result["evidence"]["after"]["applicationDigest"],
        "renderSha256": result["evidence"]["after"]["sha256"],
    })
    return result


def build_next_context(
    *,
    prior: Mapping[str, Any],
    media_result: Mapping[str, Any],
    candidate_root: Path,
) -> dict[str, Any]:
    prior = r28.validate_candidate_context(prior)
    after = media_result["evidence"]["after"]
    root = Path(candidate_root).resolve()
    final_path = Path(media_result["finalPath"]).resolve()
    app_path = Path(media_result["applicationPath"]).resolve()
    export_path = Path(media_result["renderExportPath"]).resolve()
    for path in (final_path, app_path, export_path):
        path.relative_to(root)
    candidate = {
        "candidateId": after["candidateId"].replace(":r28:", ":r31:"),
        "roundIndex": media_result["evidence"]["nextRoundIndex"],
        "finalPath": final_path.relative_to(root).as_posix(),
        "renderSha256": after["sha256"],
        "renderSize": after["size"],
        "renderExportPath": export_path.relative_to(root).as_posix(),
        "renderExportSha256": after["renderExportSha256"],
        "renderExportDigest": after["renderExportDigest"],
        "renderProducerSha": MEDIA_R23_AUTHORITY["producerSha"],
        "editorialApplication": {
            "path": app_path.relative_to(root).as_posix(),
            "fileSha256": after["applicationSidecarSha256"],
            "digest": after["applicationDigest"],
        },
    }
    return r28.build_candidate_context(
        loop_id=prior["loopId"],
        brief_digest=prior["briefDigest"],
        semantic_analysis_digest=prior["semanticAnalysisDigest"],
        semantic_directives_digest=prior["semanticDirectivesDigest"],
        ledger_digest=prior["ledgerDigest"],
        source=prior["source"],
        candidate=candidate,
        timeline=_clone(media_result["plan"]["timeline"]),
        export_spec=_clone(media_result["plan"]["exportSpec"]),
    )


def export_media_r23_next_round(
    *,
    media_checkout: Path,
    authority_profile: Mapping[str, Any],
    candidate_root: Path,
    before_context: Mapping[str, Any],
    after_context: Mapping[str, Any],
    growth_round: Mapping[str, Any],
    envelope: Mapping[str, Any],
    session_id: str,
    out_dir: Path,
) -> dict[str, Any]:
    validate_media_authority_profile(authority_profile)
    verify_media_r23_checkout(media_checkout)
    before = r28.validate_candidate_context(before_context)
    after = r28.validate_candidate_context(after_context)
    next_round = after["candidate"]["roundIndex"]
    if next_round != before["candidate"]["roundIndex"] + 1 or not 1 <= next_round <= 2:
        raise RoundOverflow("Media R23 next review round must be N+1 within 1..2")
    request = {
        "contractVersion": MEDIA_R23_AUTHORITY["requestContract"],
        "sessionId": "cr31-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32],
        "mode": "targeted_reedit",
        "reviewRound": next_round,
        "source": {
            "sourceId": before["source"]["sourceId"],
            "sha256": before["source"]["sha256"],
            "size": before["source"]["size"],
        },
        "briefLineageDigest": before["briefDigest"],
        "growthSelectedEnvelopeDigest": envelope["envelope_digest"],
        "growthHandoffDigest": envelope["candidate"]["handoff_digest"],
        "baseline": {
            "candidate": r28._dynamic_descriptor(before),
            "priorReviewPackageDigest": growth_round["package"]["package_digest"],
            "priorSealedMappingDigest": growth_round["package"]["sealed_mapping_digest"],
        },
        "challenger": r28._dynamic_descriptor(after),
    }
    work = Path(out_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    request_path = work / "media.review_session_request.r23.v1.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["GITHUB_SHA"] = MEDIA_R23_AUTHORITY["producerSha"]
    proc = subprocess.run(
        [
            "node",
            str(Path(media_checkout).resolve() / "tools/export-r23-next-round.mjs"),
            "--request",
            str(request_path),
            "--sandbox-root",
            str(Path(candidate_root).resolve()),
            "--output-dir",
            str(work / "session-package"),
            "--producer-ci-run-id",
            str(MEDIA_R23_AUTHORITY["ciRunId"]),
        ],
        cwd=Path(media_checkout).resolve(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=240,
    )
    if proc.returncode != 0:
        raise PackageDrift("Media R23 exporter failed: " + proc.stderr[-5000:])
    lines = [x for x in proc.stdout.splitlines() if x.startswith("R23_REVIEW_SESSION ")]
    if not lines:
        raise PackageDrift("Media R23 result line missing")
    log = json.loads(lines[-1].split(" ", 1)[1])
    package_path = work / "session-package" / "media.review_session_package.r23.v1.json"
    if not package_path.is_file():
        raise PackageDrift("Media R23 package file missing")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if (
        package.get("contractVersion") != MEDIA_R23_AUTHORITY["contract"]
        or package.get("state") != "REVIEW_SESSION_PACKAGE_READY"
        or package.get("producer") != {
            "repository": MEDIA_R23_AUTHORITY["repository"],
            "sha": MEDIA_R23_AUTHORITY["producerSha"],
            "ciRunId": MEDIA_R23_AUTHORITY["ciRunId"],
        }
        or package.get("reviewRound") != next_round
        or package.get("growthSelectedEnvelopeDigest") != envelope["envelope_digest"]
        or package.get("growthHandoffDigest") != envelope["candidate"]["handoff_digest"]
        or package.get("baseline", {}).get("render", {}).get("sha256") != before["candidate"]["renderSha256"]
        or package.get("challenger", {}).get("render", {}).get("sha256") != after["candidate"]["renderSha256"]
    ):
        raise PackageDrift("Media R23 package lineage drift")
    if _file_sha(package_path) != log.get("sessionPackageSha256"):
        raise PackageDrift("Media R23 package file hash drift")
    evidence = {
        "contractVersion": "creator.media_r23_next_round_result.r31.v1",
        "sessionPackageSha256": log["sessionPackageSha256"],
        "sessionIdentity": package["sessionIdentity"],
        "reviewRound": next_round,
        "r21PackageDigest": package["r21"]["packageDigest"],
        "r22DirectoryDigest": package["r22"]["directoryDigest"],
        "r22ArchiveSha256": package["r22"]["archiveSha256"],
        "promptDigest": package["promptDigest"],
        "sealedMappingDigest": package["sealedMappingDigest"],
        "baselineRenderSha256": before["candidate"]["renderSha256"],
        "challengerRenderSha256": after["candidate"]["renderSha256"],
        "producerSha": MEDIA_R23_AUTHORITY["producerSha"],
        "producerCiRunId": MEDIA_R23_AUTHORITY["ciRunId"],
        "modelReviewPerformed": False,
        "providerMutation": False,
        "humanLevelQualityClaimed": False,
    }
    evidence["resultDigest"] = _sha(evidence)
    (work / "creator.media_r23_next_round_result.r31.v1.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"package": package, "evidence": evidence, "packagePath": str(package_path), "outputDir": str(work / "session-package")}


def _terminal_growth_validator(value: Mapping[str, Any], *, expected_source_id: str, expected_render_sha256: str) -> dict[str, Any]:
    envelope = r29.validate_growth_r26_envelope(value)
    if envelope["candidate"]["state"] != "winner":
        raise r23.EditorOutcomeIneligible("only terminal winner may publish")
    if envelope["candidate"]["source_id"] != expected_source_id or envelope["candidate"]["render_sha256"] != expected_render_sha256:
        raise r23.EditorPublishHandoffError("R31 terminal review lineage mismatch")
    return envelope


def _build_final_bundle(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    growth_round: Mapping[str, Any],
    bridge_round: Mapping[str, Any],
    journal: Journal,
) -> dict[str, Any]:
    render = r28._media_render_from_context(context)
    decision = r28._winner_decision(context=context, envelope=envelope)
    bundle = {
        "contractVersion": r28.r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": context["candidate"]["candidateId"],
        "roundIndex": context["candidate"]["roundIndex"],
        "render": render,
        "critic": _clone(envelope),
        "decision": decision,
        "lineage": {
            "loopId": context["loopId"],
            "sourceId": context["source"]["sourceId"],
            "sourceSha256": context["source"]["sha256"],
            "briefDigest": context["briefDigest"],
            "semanticAnalysisDigest": context["semanticAnalysisDigest"],
            "semanticDirectivesDigest": context["semanticDirectivesDigest"],
            "ledgerDigest": journal.preterminal_digest,
            "growthCriticPin": {
                "producerSha": GROWTH_R28_AUTHORITY["producerSha"],
                "roundResultDigest": growth_round["round_result_digest"],
                "envelopeDigest": envelope["envelope_digest"],
                "captureDigest": growth_round["capture"]["capture_digest"],
                "bridgeR32ResponseDigest": bridge_round["responseDigest"],
            },
            "mediaRenderExport": {
                "producerSha": context["candidate"]["renderProducerSha"],
                "renderExportDigest": context["candidate"]["renderExportDigest"],
                "mediaR23AuthorityDigest": _sha(MEDIA_R23_AUTHORITY),
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def _write_result(out: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(result)
    value["resultDigest"] = _sha(value)
    (out / "creator.live_session_authority_result.r31.v1.json").write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return _clone(value)


def run_continuation(
    *,
    media_r23_checkout: Path,
    growth_r28_checkout: Path,
    bridge_r32_checkout: Path | None,
    media_r23_authority: Mapping[str, Any],
    growth_session_dir: Path,
    review_round: int,
    bridge_round_path: Path | None,
    selected_envelope_path: Path | None,
    candidate_root: Path,
    candidate_context_path: Path,
    out_dir: Path,
    release_authorization_path: Path | None = None,
    publish_target: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    media_pin = verify_media_r23_checkout(media_r23_checkout)
    growth_pin = verify_growth_r28_checkout(growth_r28_checkout)
    validate_media_authority_profile(media_r23_authority)
    bridge_pin = (
        {"checkoutSha": BRIDGE_R32_AUTHORITY["producerSha"], "profileDigest": _sha(BRIDGE_R32_AUTHORITY), "verificationMode": "pinned_round_identity"}
        if bridge_r32_checkout is None else verify_bridge_r32_checkout(bridge_r32_checkout)
    )
    context = r28.validate_candidate_context(json.loads(Path(candidate_context_path).read_text(encoding="utf-8")))
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    journal = Journal(out / "live-session-journal.r31.jsonl")
    ledger, growth_round = load_growth_session_round(growth_session_dir, review_round)
    journal.append_once("session", "session_authorities_bound", {
        "growthSessionId": ledger["session_id"],
        "sourceId": context["source"]["sourceId"],
        "sourceSha256": context["source"]["sha256"],
        "mediaR23AuthorityDigest": media_pin["profileDigest"],
        "growthR28AuthorityDigest": growth_pin["profileDigest"],
        "bridgeR32AuthorityDigest": bridge_pin["profileDigest"],
        "reviewRound": review_round,
        "maxReviewRounds": MAX_REVIEW_ROUNDS,
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
    })
    if bridge_round_path is None or selected_envelope_path is None:
        return _write_result(out, {
            "contractVersion": RESULT_VERSION,
            "state": "WAITING_GENUINE_CAPTURE",
            "SOURCE_READY": True,
            "growthSessionId": ledger["session_id"],
            "reviewRound": review_round,
            "sourceId": context["source"]["sourceId"],
            "sourceSha256": context["source"]["sha256"],
            "journalDigest": journal.digest,
            "providerMutation": False,
            "browserMutation": False,
            "humanParityClaimed": False,
        })

    bridge_round = validate_bridge_r32_round(json.loads(Path(bridge_round_path).read_text(encoding="utf-8")))
    envelope = validate_session_continuity(
        growth_round=growth_round,
        bridge_round=bridge_round,
        envelope=json.loads(Path(selected_envelope_path).read_text(encoding="utf-8")),
        context=context,
        candidate_root=candidate_root,
    )
    review_payload = {
        "growthSessionId": ledger["session_id"],
        "growthRoundResultDigest": growth_round["round_result_digest"],
        "bridgeSessionId": bridge_round["sessionId"],
        "bridgeResponseDigest": bridge_round["responseDigest"],
        "bridgeCaptureDigest": bridge_round.get("captureDigest", growth_round["capture"]["capture_digest"]),
        "requestId": bridge_round["requestId"],
        "operationId": bridge_round["operationId"],
        "packageDigest": growth_round["package"]["package_digest"],
        "envelopeDigest": envelope["envelope_digest"],
        "handoffDigest": envelope["candidate"]["handoff_digest"],
        "candidateId": envelope["candidate"]["candidate_id"],
        "renderSha256": envelope["candidate"]["render_sha256"],
        "reviewRound": review_round,
        "state": envelope["candidate"]["state"],
    }
    review_replay = journal.append_once(
        f"review:{review_round}", "growth_r28_bridge_r32_review_accepted", review_payload
    ) == "duplicate"

    state = envelope["candidate"]["state"]
    if state == "targeted_reedit":
        if review_round >= MAX_REEDIT_ROUNDS:
            raise RoundOverflow("third re-edit attempt rejected")
        edit_key = f"edit:{review_round}:{envelope['envelope_digest']}"
        prior_edit = journal.by_key.get(edit_key)
        media_result = execute_media_r23_reedit(
            media_checkout=media_r23_checkout,
            candidate_root=candidate_root,
            context=context,
            envelope=envelope,
        )
        journal.append_once(edit_key, "media_r23_real_reedit", {
            "reviewRound": review_round,
            "envelopeDigest": envelope["envelope_digest"],
            "handoffDigest": envelope["candidate"]["handoff_digest"],
            "mediaResultDigest": media_result["evidence"]["resultDigest"],
            "applicationDigest": media_result["evidence"]["after"]["applicationDigest"],
            "applicationSidecarSha256": media_result["evidence"]["after"]["applicationSidecarSha256"],
            "beforeRenderSha256": media_result["evidence"]["before"]["sha256"],
            "afterRenderSha256": media_result["evidence"]["after"]["sha256"],
            "afterRenderSize": media_result["evidence"]["after"]["size"],
        })
        next_context = build_next_context(
            prior=context, media_result=media_result, candidate_root=candidate_root
        )
        next_round = next_context["candidate"]["roundIndex"]
        if next_round > MAX_REEDIT_ROUNDS:
            raise RoundOverflow("next candidate exceeds two re-edits")
        next_context_path = out / "next-candidate-context.json"
        next_context_path.write_text(json.dumps(next_context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        package_key = f"package:{next_round}"
        prior_package = journal.by_key.get(package_key)
        pkg = export_media_r23_next_round(
            media_checkout=media_r23_checkout,
            authority_profile=media_r23_authority,
            candidate_root=candidate_root,
            before_context=context,
            after_context=next_context,
            growth_round=growth_round,
            envelope=envelope,
            session_id=ledger["session_id"],
            out_dir=Path(candidate_root).resolve() / ".creator-r31-packages" / envelope["envelope_digest"][:24],
        )
        journal.append_once(package_key, "media_r23_next_round_package", {
            "reviewRound": next_round,
            "sessionPackageSha256": pkg["evidence"]["sessionPackageSha256"],
            "sessionIdentity": pkg["evidence"]["sessionIdentity"],
            "resultDigest": pkg["evidence"]["resultDigest"],
            "r21PackageDigest": pkg["evidence"]["r21PackageDigest"],
            "r22DirectoryDigest": pkg["evidence"]["r22DirectoryDigest"],
            "r22ArchiveSha256": pkg["evidence"]["r22ArchiveSha256"],
            "challengerRenderSha256": pkg["evidence"]["challengerRenderSha256"],
        })
        (out / "next-review-package.json").write_text(
            json.dumps(pkg["evidence"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return _write_result(out, {
            "contractVersion": RESULT_VERSION,
            "state": "NEXT_REVIEW_PACKAGE_READY",
            "stateHistory": ["REVIEW_ACCEPTED", "REAL_REEDIT_EXECUTED", "NEXT_REVIEW_PACKAGE_READY"],
            "growthSessionId": ledger["session_id"],
            "reviewRound": review_round,
            "nextReviewRound": next_round,
            "reviewReplay": review_replay,
            "mediaReplay": bool(media_result["evidence"]["replayed"]),
            "packageReplay": prior_package is not None,
            "beforeRenderSha256": media_result["evidence"]["before"]["sha256"],
            "afterRenderSha256": media_result["evidence"]["after"]["sha256"],
            "afterRenderSize": media_result["evidence"]["after"]["size"],
            "mediaApplicationDigest": media_result["evidence"]["after"]["applicationDigest"],
            "mediaR23SessionPackageSha256": pkg["evidence"]["sessionPackageSha256"],
            "mediaR23SessionIdentity": pkg["evidence"]["sessionIdentity"],
            "mediaR23PackageDigest": pkg["evidence"]["r21PackageDigest"],
            "mediaR23ArchiveSha256": pkg["evidence"]["r22ArchiveSha256"],
            "journalDigest": journal.digest,
            "providerMutation": False,
            "browserMutation": False,
            "humanParityClaimed": False,
        })

    if state != "winner" or growth_round["outcome"] != "winner" or growth_round["terminal_winner"] is not True:
        journal.append_once("terminal", "non_publishable_review_result", {
            "state": state,
            "growthOutcome": growth_round["outcome"],
            "terminalWinner": growth_round["terminal_winner"],
            "envelopeDigest": envelope["envelope_digest"],
        })
        return _write_result(out, {
            "contractVersion": RESULT_VERSION,
            "state": "NON_PUBLISHABLE_REVIEW_RESULT",
            "stateHistory": ["REVIEW_ACCEPTED", "NON_PUBLISHABLE_REVIEW_RESULT"],
            "reviewOutcome": state,
            "growthSessionId": ledger["session_id"],
            "reviewRound": review_round,
            "journalDigest": journal.digest,
            "providerMutation": False,
            "browserMutation": False,
            "humanParityClaimed": False,
        })

    if release_authorization_path is None or publish_target is None:
        raise R31Error("terminal winner requires release authorization and publish target")
    root = Path(candidate_root).resolve()
    src = (root / context["candidate"]["finalPath"]).resolve()
    src.relative_to(root)
    final_path = out / "final.mp4"
    shutil.copyfile(src, final_path)
    asset = r21.probe_media(final_path)
    if asset.sha256 != context["candidate"]["renderSha256"] or asset.size_bytes != context["candidate"]["renderSize"]:
        raise SessionDrift("winner final.mp4 bytes drift")
    bundle = _build_final_bundle(
        context=context, envelope=envelope, growth_round=growth_round,
        bridge_round=bridge_round, journal=journal
    )
    (out / "editor-final-bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    auth = json.loads(Path(release_authorization_path).read_text(encoding="utf-8"))
    handoff = r23.build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=asset,
        release_authorization=auth,
        platform=publish_target["platform"],
        account_id=publish_target["accountId"],
        destination=publish_target["destination"],
        credential_ref=publish_target["credentialRef"],
        authorization_ref=publish_target["authorizationRef"],
        caption=publish_target["caption"],
        cta=publish_target["cta"],
        allow_synthetic_editor=False,
        media_render_validator=r28._validate_terminal_media,
        growth_critic_validator=_terminal_growth_validator,
    )
    (out / "editor-publish-handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    journal.append_once("terminal", "winner_handoff_ready", {
        "growthSessionId": ledger["session_id"],
        "reviewRound": review_round,
        "responseDigest": bridge_round["responseDigest"],
        "candidateId": context["candidate"]["candidateId"],
        "renderSha256": asset.sha256,
        "bundleDigest": bundle["bundleDigest"],
        "publishHandoffDigest": handoff["handoffDigest"],
    })
    return _write_result(out, {
        "contractVersion": RESULT_VERSION,
        "state": "WINNER_HANDOFF_READY",
        "stateHistory": ["REVIEW_ACCEPTED", "WINNER_HANDOFF_READY"],
        "growthSessionId": ledger["session_id"],
        "reviewRound": review_round,
        "winnerCandidateId": context["candidate"]["candidateId"],
        "finalRenderSha256": asset.sha256,
        "finalRenderSize": asset.size_bytes,
        "bundleDigest": bundle["bundleDigest"],
        "publishHandoffDigest": handoff["handoffDigest"],
        "journalDigest": journal.digest,
        "providerMutation": False,
        "browserMutation": False,
        "humanParityClaimed": False,
    })


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": READINESS_VERSION,
        "creatorBaseSha": CREATOR_BASE_SHA,
        "state": "WAITING_GENUINE_CAPTURE",
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": False,
        "REAL_REEDIT_EXECUTED": False,
        "NEXT_REVIEW_PACKAGE_READY": False,
        "PUBLISH_HANDOFF_READY": False,
        "mediaR23Authority": _clone(MEDIA_R23_AUTHORITY),
        "growthR28Authority": _clone(GROWTH_R28_AUTHORITY),
        "bridgeR32Authority": _clone(BRIDGE_R32_AUTHORITY),
        "authorityDigest": authority_profiles()["authorityDigest"],
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "reviewRounds": [0, 1, 2],
        "genuineCaptureSuppliedInRepository": False,
        "providerMutation": False,
        "browserMutation": False,
        "humanParityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    return report


def run_real_mp4_rehearsal(out_dir: Path) -> dict[str, Any]:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    video = out / "source-ready.mp4"
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=360x640:r=30:d=15.2",
            "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-map_metadata", "-1", str(video),
        ],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=60,
    )
    if proc.returncode != 0:
        raise R31Error("real-MP4 rehearsal failed: " + proc.stderr[-2000:])
    asset = r21.probe_media(video)
    report = {
        "contractVersion": "creator.live_session_real_mp4_rehearsal.r31.v1",
        "state": "WAITING_GENUINE_CAPTURE",
        "sourceReadyMp4": {
            "path": str(video), "sha256": asset.sha256, "size": asset.size_bytes,
            "durationSeconds": asset.duration_seconds, "width": asset.width, "height": asset.height,
        },
        "mediaR23AuthorityDigest": _sha(MEDIA_R23_AUTHORITY),
        "growthR28AuthorityDigest": _sha(GROWTH_R28_AUTHORITY),
        "bridgeR32AuthorityDigest": _sha(BRIDGE_R32_AUTHORITY),
        "nextExternalReviewBoundaryReached": True,
        "liveReviewIngested": False,
        "modelEvidenceSynthesized": False,
        "providerMutation": False,
        "browserMutation": False,
        "humanLevelQualityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    (out / "real-mp4-rehearsal.r31.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _load_json_arg(value: str) -> dict[str, Any]:
    path = Path(value)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else json.loads(value)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="creator-live-session-r31")
    sub = p.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("readiness")
    ready.add_argument("--out")
    reh = sub.add_parser("rehearsal")
    reh.add_argument("--out", required=True)
    run = sub.add_parser("continue")
    run.add_argument("--media-r23-checkout", required=True)
    run.add_argument("--media-r23-authority", required=True)
    run.add_argument("--growth-r28-checkout", required=True)
    run.add_argument("--bridge-r32-checkout")
    run.add_argument("--growth-session-dir", required=True)
    run.add_argument("--review-round", type=int, required=True)
    run.add_argument("--bridge-r32-round-result")
    run.add_argument("--selected-envelope")
    run.add_argument("--candidate-root", required=True)
    run.add_argument("--candidate-context", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--release-authorization")
    run.add_argument("--publish-target")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        report = readiness_report()
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 2
    if args.command == "rehearsal":
        try:
            report = run_real_mp4_rehearsal(Path(args.out))
        except Exception as exc:
            print(json.dumps({"state": "BLOCKED", "reason": type(exc).__name__, "detail": str(exc)}, sort_keys=True))
            return 2
        print(json.dumps(report, sort_keys=True))
        return 0
    try:
        report = run_continuation(
            media_r23_checkout=Path(args.media_r23_checkout),
            growth_r28_checkout=Path(args.growth_r28_checkout),
            bridge_r32_checkout=None if not args.bridge_r32_checkout else Path(args.bridge_r32_checkout),
            media_r23_authority=_load_json_arg(args.media_r23_authority),
            growth_session_dir=Path(args.growth_session_dir),
            review_round=args.review_round,
            bridge_round_path=None if not args.bridge_r32_round_result else Path(args.bridge_r32_round_result),
            selected_envelope_path=None if not args.selected_envelope else Path(args.selected_envelope),
            candidate_root=Path(args.candidate_root),
            candidate_context_path=Path(args.candidate_context),
            out_dir=Path(args.out),
            release_authorization_path=None if not args.release_authorization else Path(args.release_authorization),
            publish_target=None if not args.publish_target else _load_json_arg(args.publish_target),
        )
    except Exception as exc:
        blocked = {
            "contractVersion": RESULT_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "providerMutation": False,
            "browserMutation": False,
            "humanParityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
