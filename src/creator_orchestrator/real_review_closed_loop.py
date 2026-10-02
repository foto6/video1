from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_editor_loop as r22
from . import autonomous_reels as reels
from . import editor_publish_handoff as r23
from . import exact_pin_closed_loop as r24
from . import publish_execution as r21

CONTRACT_VERSION = "creator.real_review_closed_loop.r26.v1"
REVIEW_EVENT_VERSION = "creator.external_real_review_event.r26.v1"
LEDGER_VERSION = "creator.real_review_closed_loop_ledger.r26.v1"
MEDIA_REQUEST_VERSION = "creator.media_r15_real_review_request.r26.v1"

CREATOR_R24_SHA = "215dc6ef924da45072c9f2c648edd3b3d80e645c"
MEDIA_R15_SHA = "a17f782da8144d1e890ac83195396a3192df93c2"
MEDIA_R15_CI = 36860193113
MEDIA_MANIFEST_BLOB = "945acb01ff0269d89b91463aa8d862f500e055b2"
MEDIA_SCHEMA_BLOB = "6353d32d785a2a1f1441bac4cfd0271b46b41d4a"

GROWTH_R23_SHA = "26f769abceb43a63677ea8f7ba028369db371696"
GROWTH_R23_CI = 36981672628
GROWTH_R23_CONTRACT_BLOB = "ced853aad722aad4c7a88e9a41756baa1b2892a6"
GROWTH_R23_SCHEMA_BLOB = "ba9ada04488760147136dcaaf012206405c04653"
GROWTH_R23_ADAPTER_BLOB = "a4f5b1219c874ae13c05651e584dd7fbf5d4449a"

GROWTH_HANDOFF_VERSION = "growth.creator_reedit_handoff.v1"
GROWTH_ADAPTER_VERSION = "growth.web_video_critic_reedit_adapter.v1"
MAX_REEDIT_ROUNDS = 2
BRIDGE_FILE_CAP = 500_000_000

DECISION_STATES = {
    "winner",
    "targeted_reedit",
    "tie",
    "insufficient_evidence",
    "human_review",
}
SUPPORTED_EDIT_OPERATIONS = {
    "trim",
    "cut",
    "crop_scale_reframe",
    "speed_change",
    "fade_transition",
    "text_overlay",
    "subtitles_captions",
    "audio_duck_mix",
    "intro_outro_cta",
}
BINDING_KEYS = {
    "source_id",
    "source_sha256",
    "source_size",
    "media_repository",
    "media_producer_sha",
    "candidate_id",
    "render_sha256",
    "render_size",
    "render_export_sha256",
    "attachment_sha256",
    "attachment_size",
    "attachment_identity",
    "review_bundle_digest",
    "critic_input_digest",
    "critic_output_digest",
}
DIRECTIVE_KEYS = {
    "operation",
    "start_ms",
    "end_ms",
    "defect_category",
    "severity",
    "source_observation_id",
    "evidence",
    "confidence",
    "uncertainty",
    "upstream_proposed_edit",
    "upstream_proposed_edit_executable",
    "binding",
    "directive_id",
}

BRIDGE_R26_AUTHORITY = {
    "repository": "foto6/WebAIBridge",
    "branch": "agent/bridge-r26-file-attachment-rehearsal-20261002",
    "source_sha": "73c13f9eed2a2cbcea881dd8c5452d054bfef940",
    "attachment_contract": "bridge.chat_file_attachment.v1",
    "rehearsal_request_contract": "bridge.chat_file_attachment_rehearsal_request.v1",
    "rehearsal_result_contract": "bridge.chat_file_attachment_rehearsal_result.v1",
    "dom_probe_contract": "bridge.chat_file_attachment_dom_probe.v1",
    "operator_evidence_contract": "bridge.chat_file_attachment_operator_evidence.v1",
    "max_file_bytes": BRIDGE_FILE_CAP,
    "disposition": "READY_FOR_EXPLICIT_LIVE_REHEARSAL",
    "live_pass": False,
    "real_upload_proven": False,
    "real_prompt_send_proven": False,
    "no_live_deploy": True,
    "no_cutover": True,
}
MEDIA_R18_AUTHORITY = {
    "repository": "foto6/video2",
    "branch": "agent/media-r18-direct-model-review-package-20261002",
    "source_sha": "2c41f084e000eca5efd9a51d2d3752bec1bd1311",
    "ci_run_id": 36967381891,
    "contract": "media.direct_model_review_package.v1",
    "max_file_bytes": BRIDGE_FILE_CAP,
    "live_upload_performed": False,
    "model_judgment_performed": False,
}


class RealReviewError(ValueError):
    pass


class DependencyPinError(RealReviewError):
    pass


class ReviewLineageError(RealReviewError):
    pass


class ReviewReplayError(RealReviewError):
    pass


class UnsupportedDirective(RealReviewError):
    pass


class RoundRegression(RealReviewError):
    pass


class LiveReviewRequired(RealReviewError):
    pass


class InjectedLostAck(RuntimeError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _hex(value: Any, size: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != size
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReviewLineageError(f"{field} must be lowercase {size}-hex")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewLineageError(f"{field} must be non-empty")
    return value


def _git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True
    ).strip()


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def verify_dependency_pins(
    media_checkout: Path,
    growth_r23_checkout: Path,
) -> dict[str, Any]:
    media_checkout = Path(media_checkout).resolve()
    growth_r23_checkout = Path(growth_r23_checkout).resolve()
    if _git_head(media_checkout) != MEDIA_R15_SHA:
        raise DependencyPinError("Media checkout is not exact R15 producer SHA")
    if _git_head(growth_r23_checkout) != GROWTH_R23_SHA:
        raise DependencyPinError("Growth checkout is not exact R23 producer SHA")

    media_manifest = media_checkout / "conformance" / "media.render_export.v1" / "manifest.json"
    media_schema = media_checkout / "conformance" / "media.render_export.v1" / "schema.json"
    growth_contract = growth_r23_checkout / "conformance" / GROWTH_HANDOFF_VERSION / "contract.json"
    growth_schema = growth_r23_checkout / "conformance" / GROWTH_HANDOFF_VERSION / "schema.json"
    growth_adapter = growth_r23_checkout / "growth_analytics" / "critic_reedit_adapter.py"
    observed = {
        "creator": {
            "repository": "foto6/video1",
            "baseSha": CREATOR_R24_SHA,
            "contract": CONTRACT_VERSION,
        },
        "media": {
            "repository": "foto6/video2",
            "producerSha": _git_head(media_checkout),
            "ciRunId": MEDIA_R15_CI,
            "contract": "media.render_export.v1",
            "manifestBlobSha1": _git_blob_sha(media_manifest),
            "schemaBlobSha1": _git_blob_sha(media_schema),
        },
        "growth": {
            "repository": "foto6/video3",
            "producerSha": _git_head(growth_r23_checkout),
            "ciRunId": GROWTH_R23_CI,
            "contract": GROWTH_HANDOFF_VERSION,
            "adapterContract": GROWTH_ADAPTER_VERSION,
            "contractBlobSha1": _git_blob_sha(growth_contract),
            "schemaBlobSha1": _git_blob_sha(growth_schema),
            "adapterBlobSha1": _git_blob_sha(growth_adapter),
        },
    }
    if observed["media"]["manifestBlobSha1"] != MEDIA_MANIFEST_BLOB:
        raise DependencyPinError("Media R15 manifest blob drift")
    if observed["media"]["schemaBlobSha1"] != MEDIA_SCHEMA_BLOB:
        raise DependencyPinError("Media R15 schema blob drift")
    if observed["growth"]["contractBlobSha1"] != GROWTH_R23_CONTRACT_BLOB:
        raise DependencyPinError("Growth R23 contract blob drift")
    if observed["growth"]["schemaBlobSha1"] != GROWTH_R23_SCHEMA_BLOB:
        raise DependencyPinError("Growth R23 schema blob drift")
    if observed["growth"]["adapterBlobSha1"] != GROWTH_R23_ADAPTER_BLOB:
        raise DependencyPinError("Growth R23 adapter blob drift")
    return observed


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            event = json.loads(line)
            material = dict(event)
            digest = material.pop("eventDigest", None)
            if event.get("ledgerVersion") != LEDGER_VERSION or _sha(material) != digest:
                raise RealReviewError("R26 ledger corruption")
            if event.get("sequence") != len(self.events) + 1:
                raise RealReviewError("R26 ledger sequence mismatch")
            if event.get("eventKey") in self.by_key:
                raise RealReviewError("R26 duplicate durable key")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event

    def append_once(
        self,
        key: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if prior["eventType"] != event_type or prior["payload"] != normalized:
                raise ReviewReplayError("conflicting durable replay")
            return "duplicate"
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": key,
            "eventType": event_type,
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
        return _sha([
            event for event in self.events
            if event["eventKey"] != "terminal"
        ])


def _growth_producer_descriptor() -> dict[str, Any]:
    return {
        "repository": "foto6/video3",
        "sha": GROWTH_R23_SHA,
        "ciRunId": GROWTH_R23_CI,
        "contract": GROWTH_HANDOFF_VERSION,
        "adapterContract": GROWTH_ADAPTER_VERSION,
        "contractBlobSha1": GROWTH_R23_CONTRACT_BLOB,
        "schemaBlobSha1": GROWTH_R23_SCHEMA_BLOB,
        "adapterBlobSha1": GROWTH_R23_ADAPTER_BLOB,
    }


def parse_growth_r23_handoff(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version",
        "adapter_version",
        "handoff_id",
        "handoff_digest",
        "state",
        "reedit_round",
        "max_reedit_rounds",
        "binding",
        "pairwise",
        "coverage",
        "summary_uncertainty",
        "directives",
        "bridge_r26_authority",
        "media_r18_authority",
        "evidence_boundary",
        "authority",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise ReviewLineageError("Growth R23 handoff fields invalid")
    if payload["contract_version"] != GROWTH_HANDOFF_VERSION:
        raise ReviewLineageError("Growth R23 handoff contract mismatch")
    if payload["adapter_version"] != GROWTH_ADAPTER_VERSION:
        raise ReviewLineageError("Growth R23 adapter contract mismatch")
    state = payload["state"]
    if state not in DECISION_STATES:
        raise ReviewLineageError("Growth R23 state invalid")
    round_index = payload["reedit_round"]
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or not 0 <= round_index <= MAX_REEDIT_ROUNDS
        or payload["max_reedit_rounds"] != MAX_REEDIT_ROUNDS
    ):
        raise RoundRegression("Growth R23 re-edit round invalid")

    binding = payload["binding"]
    if not isinstance(binding, Mapping) or set(binding) != BINDING_KEYS:
        raise ReviewLineageError("Growth R23 binding fields invalid")
    for key in (
        "source_sha256",
        "render_sha256",
        "render_export_sha256",
        "attachment_sha256",
        "review_bundle_digest",
        "critic_input_digest",
        "critic_output_digest",
    ):
        _hex(binding[key], 64, f"binding.{key}")
    _nonempty(binding["source_id"], "binding.source_id")
    _nonempty(binding["candidate_id"], "binding.candidate_id")
    _nonempty(binding["attachment_identity"], "binding.attachment_identity")
    _hex(binding["media_producer_sha"], 40, "binding.media_producer_sha")
    if binding["media_repository"] != "foto6/video2":
        raise ReviewLineageError("Growth R23 media repository mismatch")
    for key in ("source_size", "render_size", "attachment_size"):
        value = binding[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ReviewLineageError(f"binding.{key} invalid")
    if (
        binding["render_sha256"] != binding["attachment_sha256"]
        or binding["render_size"] != binding["attachment_size"]
        or binding["attachment_size"] > BRIDGE_FILE_CAP
    ):
        raise ReviewLineageError("render/attachment identity mismatch")

    if payload["bridge_r26_authority"] != BRIDGE_R26_AUTHORITY:
        raise ReviewLineageError("Bridge R26 authority drift")
    if payload["media_r18_authority"] != MEDIA_R18_AUTHORITY:
        raise ReviewLineageError("Media R18 authority drift")

    pairwise = payload["pairwise"]
    if not isinstance(pairwise, Mapping) or set(pairwise) != {
        "selection", "mapped_candidate_id", "output_digest"
    }:
        raise ReviewLineageError("Growth R23 pairwise binding invalid")
    if pairwise["selection"] not in {None, "A", "B", "tie", "insufficient_evidence"}:
        raise ReviewLineageError("Growth R23 pairwise selection invalid")
    if pairwise["output_digest"] is not None:
        _hex(pairwise["output_digest"], 64, "pairwise.output_digest")

    coverage = payload["coverage"]
    if not isinstance(coverage, Mapping) or set(coverage) != {
        "method",
        "inspected_ranges",
        "uninspected_possible",
        "every_frame_inspected",
        "notes",
        "coverage_uncertainty_preserved",
    }:
        raise ReviewLineageError("Growth R23 coverage fields invalid")
    if (
        coverage["uninspected_possible"] is not True
        or coverage["every_frame_inspected"] is not False
        or coverage["coverage_uncertainty_preserved"] is not True
        or not isinstance(coverage["inspected_ranges"], list)
    ):
        raise ReviewLineageError("Growth R23 coverage uncertainty lost")
    _nonempty(coverage["notes"], "coverage.notes")
    _nonempty(payload["summary_uncertainty"], "summary_uncertainty")

    directives = payload["directives"]
    if not isinstance(directives, list):
        raise ReviewLineageError("Growth R23 directives must be an array")
    if state == "targeted_reedit" and not directives:
        raise ReviewLineageError("targeted_reedit requires directives")
    if state != "targeted_reedit" and directives:
        raise ReviewLineageError("non-targeted state cannot emit directives")
    seen_directives: set[str] = set()
    for row in directives:
        if not isinstance(row, Mapping) or set(row) != DIRECTIVE_KEYS:
            raise ReviewLineageError("Growth R23 directive fields invalid")
        if row["operation"] not in SUPPORTED_EDIT_OPERATIONS:
            raise UnsupportedDirective("unsupported Growth R23 edit operation")
        if row["binding"] != binding:
            raise ReviewLineageError("directive binding drift")
        if row["upstream_proposed_edit_executable"] is not False:
            raise UnsupportedDirective("freeform model edit cannot become executable")
        start = row["start_ms"]
        end = row["end_ms"]
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise ReviewLineageError("directive timestamp invalid")
        _nonempty(row["evidence"], "directive.evidence")
        _nonempty(row["uncertainty"], "directive.uncertainty")
        _nonempty(row["source_observation_id"], "directive.source_observation_id")
        directive_id = _nonempty(row["directive_id"], "directive.directive_id")
        if directive_id in seen_directives:
            raise ReviewReplayError("duplicate directive in Growth R23 handoff")
        seen_directives.add(directive_id)

    if payload["evidence_boundary"] != {
        "model_review_only": True,
        "human_ground_truth": False,
        "human_label": False,
        "live_platform_evidence": False,
        "live_video_review_fabricated": False,
    }:
        raise ReviewLineageError("Growth R23 evidence boundary drift")
    if payload["authority"] != {
        "advisory_only": True,
        "creator_mutation": False,
        "media_mutation": False,
        "provider_mutation": False,
        "upload_performed": False,
        "publish_authorized": False,
        "release_authorized": False,
    }:
        raise ReviewLineageError("Growth R23 authority drift")

    expected_id = "gcrh1:" + _sha({
        "critic_output_digest": binding["critic_output_digest"],
        "pairwise_output_digest": pairwise["output_digest"],
        "reedit_round": round_index,
    })
    if payload["handoff_id"] != expected_id:
        raise ReviewLineageError("Growth R23 handoff identity mismatch")
    material = dict(payload)
    material["handoff_digest"] = ""
    if payload["handoff_digest"] != _sha(material):
        raise ReviewLineageError("Growth R23 handoff digest mismatch")
    return _clone(payload)


def parse_review_event(
    payload: Mapping[str, Any],
    *,
    allow_test_fixture: bool,
) -> dict[str, Any]:
    required = {
        "contractVersion",
        "producer",
        "captureMode",
        "reviewIdentity",
        "handoff",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise ReviewLineageError("R26 review event fields invalid")
    if payload["contractVersion"] != REVIEW_EVENT_VERSION:
        raise ReviewLineageError("R26 review event contract mismatch")
    if payload["producer"] != _growth_producer_descriptor():
        raise DependencyPinError("R26 review event Growth R23 producer drift")
    mode = payload["captureMode"]
    if mode not in {"external_live_review", "test_fixture"}:
        raise ReviewLineageError("R26 review captureMode invalid")
    if mode == "test_fixture" and not allow_test_fixture:
        raise LiveReviewRequired("test fixture review is not a genuine external live review")
    handoff = parse_growth_r23_handoff(payload["handoff"])
    if payload["reviewIdentity"] != handoff["handoff_id"]:
        raise ReviewLineageError("R26 review identity mismatch")
    return _clone(payload)


def _validate_review_against_render(
    event: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    render_record: Mapping[str, Any],
    expected_round: int,
) -> None:
    handoff = event["handoff"]
    if handoff["reedit_round"] != expected_round:
        raise RoundRegression("review round does not match current candidate round")
    binding = handoff["binding"]
    render = render_record["render"]
    final_path = Path(render_record["renderPath"])
    if binding["source_id"] != source["sourceId"]:
        raise ReviewLineageError("stale review source id")
    if binding["source_sha256"] != source["sha256"]:
        raise ReviewLineageError("stale review source SHA")
    if binding["source_size"] != source["sizeBytes"]:
        raise ReviewLineageError("stale review source size")
    if binding["candidate_id"] != render_record["candidateId"]:
        raise ReviewLineageError("stale review candidate id")
    if binding["render_sha256"] != render["render_sha256"]:
        raise ReviewLineageError("stale review render SHA")
    if binding["render_size"] != final_path.stat().st_size:
        raise ReviewLineageError("stale review render size")
    if binding["attachment_sha256"] != render["render_sha256"]:
        raise ReviewLineageError("wrong review attachment SHA")
    if binding["attachment_size"] != final_path.stat().st_size:
        raise ReviewLineageError("wrong review attachment size")
    if binding["media_repository"] != "foto6/video2":
        raise ReviewLineageError("review media repository mismatch")
    if binding["media_producer_sha"] != MEDIA_R15_SHA:
        raise ReviewLineageError("review Media producer SHA mismatch")
    if (
        binding["render_export_sha256"]
        != render["render_provenance"]["mediaR15ExportDigest"]
    ):
        raise ReviewLineageError("stale review render-export digest")


def _review_event_digest(event: Mapping[str, Any]) -> str:
    return _sha(event)


def _review_map(
    review_paths: Sequence[Path],
    *,
    allow_test_fixture: bool,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    seen_identity: set[str] = set()
    last_round = -1
    for path in review_paths:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        event = parse_review_event(raw, allow_test_fixture=allow_test_fixture)
        identity = event["reviewIdentity"]
        if identity in seen_identity:
            raise ReviewReplayError("duplicate review event in one invocation")
        seen_identity.add(identity)
        round_index = event["handoff"]["reedit_round"]
        if round_index < last_round:
            raise RoundRegression("review events regress in round order")
        last_round = round_index
        if round_index in out:
            raise ReviewReplayError("multiple review events supplied for one round")
        out[round_index] = event
    if out and sorted(out) != list(range(min(out), max(out) + 1)):
        raise RoundRegression("review event rounds must be contiguous")
    if out and min(out) != 0:
        raise RoundRegression("review sequence must start at round 0")
    return out


def _initial_plan(
    *,
    source_sha: str,
    analysis: Mapping[str, Any],
    style: Mapping[str, Any],
    directives: Mapping[str, Any],
) -> dict[str, Any]:
    return r22.build_initial_plans(
        loop_id="r26:" + source_sha[:24],
        semantic_analysis=analysis,
        style_decision=style,
        directives=directives,
        count=2,
    )[0]


def build_reedit_plan_from_handoff(
    *,
    parent_plan: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    parsed = parse_growth_r23_handoff(handoff)
    if parsed["state"] != "targeted_reedit":
        raise RealReviewError("only targeted_reedit may create a re-edit plan")
    if parsed["reedit_round"] != parent_plan["roundIndex"]:
        raise RoundRegression("re-edit handoff round does not match parent plan")
    next_round = parsed["reedit_round"] + 1
    if next_round > MAX_REEDIT_ROUNDS:
        raise RoundRegression("maximum two re-edit rounds")
    deltas = [
        {
            "operation": row["operation"],
            "startMs": row["start_ms"],
            "endMs": row["end_ms"],
            "evidence": row["evidence"],
            "uncertainty": row["uncertainty"],
            "sourceObservationId": row["source_observation_id"],
            "directiveId": row["directive_id"],
            "criticOutputDigest": parsed["binding"]["critic_output_digest"],
        }
        for row in parsed["directives"]
    ]
    material = {
        "contractVersion": r22.PLAN_VERSION,
        "roundIndex": next_round,
        "parentCandidateId": parent_plan["candidateId"],
        "ordinal": parent_plan["ordinal"],
        "semanticAnalysisDigest": parent_plan["semanticAnalysisDigest"],
        "editorialMode": parent_plan["editorialMode"],
        "semanticDirectivesDigest": parent_plan["semanticDirectivesDigest"],
        "variant": _clone(parent_plan["variant"]),
        "targetedDeltas": deltas,
    }
    candidate_id = "candidate26r:" + _sha({
        "parentCandidateId": parent_plan["candidateId"],
        "roundIndex": next_round,
        "handoffDigest": parsed["handoff_digest"],
        "directives": deltas,
    })
    plan = {**material, "candidateId": candidate_id}
    plan["planDigest"] = _sha(plan)
    return plan


def _media_request(
    *,
    input_path: Path,
    original_source: Mapping[str, Any],
    plan: Mapping[str, Any],
    handoff: Mapping[str, Any] | None,
    parent_render_sha256: str | None,
) -> dict[str, Any]:
    asset = r21.probe_media(Path(input_path))
    review_directives = [] if handoff is None else _clone(handoff["directives"])
    request = {
        "contractVersion": MEDIA_REQUEST_VERSION,
        "mediaProducerSha": MEDIA_R15_SHA,
        "originalSource": {
            "sourceId": original_source["sourceId"],
            "sha256": original_source["sha256"],
            "sizeBytes": original_source["sizeBytes"],
        },
        "editInput": {
            "path": str(Path(input_path).resolve()),
            "sha256": asset.sha256,
            "sizeBytes": asset.size_bytes,
            "durationMs": int(round(asset.duration_seconds * 1000)),
            "hasAudio": asset.audio_codec is not None,
            "parentRenderSha256": parent_render_sha256,
        },
        "plan": _clone(plan),
        "reviewDirectives": review_directives,
    }
    request["requestDigest"] = _sha(request)
    return request


def _run_media(
    *,
    media_checkout: Path,
    request: Mapping[str, Any],
    candidate_dir: Path,
) -> dict[str, Any]:
    request_path = candidate_dir / "media-request-r26.json"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return r24._run_json([
        "node",
        str(Path(__file__).with_name("r26_media_bridge.mjs")),
        "--media-checkout",
        str(Path(media_checkout).resolve()),
        "--request",
        str(request_path),
        "--out",
        str(candidate_dir),
    ])


def _adapt_media_result(
    result: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    source: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    if result.get("contractVersion") != "creator.media_r15_real_review_result.r26.v1":
        raise RealReviewError("R26 Media bridge result contract mismatch")
    if result.get("requestDigest") != request["requestDigest"]:
        raise ReviewLineageError("R26 Media bridge request digest mismatch")
    if result.get("actualMediaProducerInvoked") is not True:
        raise RealReviewError("R26 Media bridge did not invoke exact Media runtime")
    export = result.get("renderExport")
    if not isinstance(export, Mapping) or export.get("contractVersion") != "media.render_export.v1":
        raise ReviewLineageError("Media R15 render export contract mismatch")
    if export.get("producer") != {
        "repository": "foto6/video2",
        "sha": MEDIA_R15_SHA,
    }:
        raise DependencyPinError("Media R15 render export producer drift")
    final_path = Path(result["finalPath"])
    actual_sha = hashlib.sha256(final_path.read_bytes()).hexdigest()
    actual_size = final_path.stat().st_size
    artifact = export["artifact"]
    if artifact["sha256"] != actual_sha or artifact["size"] != actual_size:
        raise ReviewLineageError("Media R15 final bytes do not match sidecar")
    if export["qa"]["technical"]["passed"] is not True:
        raise RealReviewError("Media R15 technical QA failed")

    directive_digest = _sha(request["reviewDirectives"])
    value = {
        "contract_version": r22.MEDIA_RENDER_EXPORT_VERSION,
        "repository": "foto6/video2",
        "commit_sha": MEDIA_R15_SHA,
        "source_class": "provider",
        "source_id": source["sourceId"],
        "source_sha256": source["sha256"],
        "candidate_id": plan["candidateId"],
        "round_index": plan["roundIndex"],
        "plan_digest": plan["planDigest"],
        "render_sha256": actual_sha,
        "timeline_digest": export["provenance"]["timelineDigest"],
        "artifact_manifest_digest": artifact["artifactManifestDigest"],
        "technical_qa": {
            "passed": True,
            "qa_digest": export["qa"]["technical"]["sha256"],
            "checks": export["qa"]["technical"]["value"]["checks"],
        },
        "render_provenance": {
            "adapter": "creator-r26-real-review-media-r15",
            "ordinal": plan["ordinal"],
            "roundIndex": plan["roundIndex"],
            "mediaR15ExportDigest": result["renderExportDigest"],
            "mediaR15ProducerSha": MEDIA_R15_SHA,
            "actualMediaProducerInvoked": True,
            "editInputSha256": request["editInput"]["sha256"],
            "editInputSizeBytes": request["editInput"]["sizeBytes"],
            "parentRenderSha256": request["editInput"]["parentRenderSha256"],
            "reviewDirectiveDigest": directive_digest,
            "originalSourceSha256": source["sha256"],
            "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
        },
        "human_ground_truth": False,
    }
    return r22.validate_media_render_export(
        value,
        expected_source_id=source["sourceId"],
        expected_source_sha256=source["sha256"],
        expected_candidate_id=plan["candidateId"],
        expected_plan_digest=plan["planDigest"],
        allow_synthetic=False,
    )


def _required_review_record(
    *,
    source: Mapping[str, Any],
    record: Mapping[str, Any],
    round_index: int,
) -> dict[str, Any]:
    render = record["render"]
    final_path = Path(record["renderPath"])
    required = {
        "contractVersion": "creator.real_review_request.r26.v1",
        "growthProducer": _growth_producer_descriptor(),
        "roundIndex": round_index,
        "source": {
            "sourceId": source["sourceId"],
            "sha256": source["sha256"],
            "sizeBytes": source["sizeBytes"],
        },
        "candidate": {
            "candidateId": record["candidateId"],
            "renderSha256": render["render_sha256"],
            "renderSizeBytes": final_path.stat().st_size,
            "renderExportSha256": render["render_provenance"]["mediaR15ExportDigest"],
            "mediaRepository": "foto6/video2",
            "mediaProducerSha": MEDIA_R15_SHA,
        },
        "requiredExternalContract": REVIEW_EVENT_VERSION,
        "requiredGrowthHandoffContract": GROWTH_HANDOFF_VERSION,
        "attachmentMustEqualRenderBytes": True,
        "liveReviewMustNotBeFabricated": True,
    }
    required["requestDigest"] = _sha(required)
    return required


def _terminal_review_validator(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_render_sha256: str,
) -> dict[str, Any]:
    parsed = parse_growth_r23_handoff(value)
    if parsed["state"] != "winner":
        raise r23.EditorOutcomeIneligible("only terminal Growth R23 winner may publish")
    binding = parsed["binding"]
    if binding["source_id"] != expected_source_id:
        raise r23.EditorPublishHandoffError("R26 terminal review source mismatch")
    if binding["render_sha256"] != expected_render_sha256:
        raise r23.EditorPublishHandoffError("R26 terminal review render mismatch")
    return parsed


def _winner_decision(
    *,
    candidate_id: str,
    render_sha256: str,
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    decision = {
        "contractVersion": r22.DECISION_VERSION,
        "roundIndex": handoff["reedit_round"],
        "state": "winner",
        "winnerCandidateId": candidate_id,
        "reason": "terminal externally captured Growth R23 real-review handoff",
        "evaluations": [{
            "candidateId": candidate_id,
            "renderSha256": render_sha256,
            "growthR23HandoffId": handoff["handoff_id"],
            "growthR23HandoffDigest": handoff["handoff_digest"],
            "criticOutputDigest": handoff["binding"]["critic_output_digest"],
        }],
        "humanLevelQualityClaimed": False,
        "aestheticSuperiorityClaimed": False,
    }
    decision["decisionDigest"] = _sha(decision)
    return decision


def _final_bundle(
    *,
    record: Mapping[str, Any],
    handoff: Mapping[str, Any],
    decision: Mapping[str, Any],
    source: Mapping[str, Any],
    analysis: Mapping[str, Any],
    directives: Mapping[str, Any],
    ledger: Ledger,
) -> dict[str, Any]:
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": record["candidateId"],
        "roundIndex": handoff["reedit_round"],
        "render": _clone(record["render"]),
        "critic": _clone(handoff),
        "decision": _clone(decision),
        "lineage": {
            "loopId": "r26:" + source["sha256"][:24],
            "sourceId": source["sourceId"],
            "sourceSha256": source["sha256"],
            "briefDigest": analysis["briefDigest"],
            "semanticAnalysisDigest": analysis["analysisDigest"],
            "semanticDirectivesDigest": directives["directivesDigest"],
            "ledgerDigest": ledger.preterminal_digest,
            "growthCriticPin": {
                **r22.GROWTH_CRITIC_PIN,
                "growthR23ProducerSha": GROWTH_R23_SHA,
                "growthR23CiRunId": GROWTH_R23_CI,
                "growthR23Contract": GROWTH_HANDOFF_VERSION,
                "growthR23ContractBlobSha1": GROWTH_R23_CONTRACT_BLOB,
                "growthR23SchemaBlobSha1": GROWTH_R23_SCHEMA_BLOB,
                "growthR23AdapterBlobSha1": GROWTH_R23_ADAPTER_BLOB,
                "criticOutputDigest": handoff["binding"]["critic_output_digest"],
                "attachmentIdentity": handoff["binding"]["attachment_identity"],
            },
            "mediaRenderExport": {
                **r22.MEDIA_RENDER_EXPORT_OBSERVED,
                "acceptedMediaR15ProducerSha": MEDIA_R15_SHA,
                "acceptedContract": "media.render_export.v1",
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def _report(
    *,
    state: str,
    source: Mapping[str, Any],
    pins: Mapping[str, Any],
    ledger: Ledger,
    round_index: int,
    real_review_executed: bool,
    total_media_effects: int,
    publish_handoff_effects: int,
    required_review: Mapping[str, Any] | None = None,
    final_bundle: Mapping[str, Any] | None = None,
    publish_handoff: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "contractVersion": CONTRACT_VERSION,
        "implementationStatus": "IMPLEMENTED",
        "realReviewExecutionStatus": (
            "REAL_REVIEW_EXECUTED"
            if real_review_executed
            else "BLOCKED_OR_TEST_ONLY"
        ),
        "state": state,
        "source": _clone(source),
        "dependencyEvidence": _clone(pins),
        "reeditRounds": min(round_index, MAX_REEDIT_ROUNDS),
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "realMediaRenderEffects": total_media_effects,
        "publishHandoffEffects": publish_handoff_effects,
        "requiredReview": None if required_review is None else _clone(required_review),
        "finalBundleDigest": None if final_bundle is None else final_bundle["bundleDigest"],
        "publishHandoffDigest": None if publish_handoff is None else publish_handoff["handoffDigest"],
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    report["reportDigest"] = _sha(report)
    return report


def run_real_review_closed_loop(
    *,
    source_path: Path,
    brief: str,
    media_checkout: Path,
    growth_r23_checkout: Path,
    out_dir: Path,
    review_paths: Sequence[Path] = (),
    allow_test_fixture: bool = False,
    inject_lost_ack_after_render: set[int] | None = None,
    inject_lost_ack_after_handoff: bool = False,
) -> dict[str, Any]:
    pins = verify_dependency_pins(media_checkout, growth_r23_checkout)
    source_path = Path(source_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    source_asset = r21.probe_media(source_path)
    analysis, style, semantic_directives = r24._source_context(source_path, brief)
    source = {
        "sourceId": analysis["source"]["sourceId"],
        "sha256": analysis["source"]["sha256"],
        "sizeBytes": source_asset.size_bytes,
        "durationMs": analysis["source"]["durationMs"],
    }
    review_by_round = _review_map(
        [Path(path) for path in review_paths],
        allow_test_fixture=allow_test_fixture,
    )
    ledger = Ledger(out_dir / "real-review-ledger.jsonl")
    ledger.append_once("start", "real_review_loop_started", {
        "source": source,
        "briefDigest": analysis["briefDigest"],
        "semanticAnalysisDigest": analysis["analysisDigest"],
        "semanticDirectivesDigest": semantic_directives["directivesDigest"],
        "dependencyEvidence": pins,
    })

    plan = _initial_plan(
        source_sha=source["sha256"],
        analysis=analysis,
        style=style,
        directives=semantic_directives,
    )
    input_path = source_path
    parent_render_sha256: str | None = None
    parent_handoff: Mapping[str, Any] | None = None
    total_media_effects = 0
    real_review_executed = True
    injected_rounds = set(inject_lost_ack_after_render or ())
    seen_invocation_reviews: set[str] = set()

    for round_index in range(MAX_REEDIT_ROUNDS + 1):
        if plan["roundIndex"] != round_index:
            raise RoundRegression("deterministic plan round regression")
        candidate_dir = out_dir / "candidates" / plan["candidateId"].replace(":", "_")
        request = _media_request(
            input_path=input_path,
            original_source=source,
            plan=plan,
            handoff=parent_handoff,
            parent_render_sha256=parent_render_sha256,
        )
        render_key = "render:" + plan["candidateId"]
        render_was_durable = render_key in ledger.by_key
        result = _run_media(
            media_checkout=media_checkout,
            request=request,
            candidate_dir=candidate_dir,
        )
        total_media_effects += int(result["logicalEffects"])
        if (
            round_index in injected_rounds
            and not render_was_durable
            and int(result["logicalEffects"]) == 1
        ):
            raise InjectedLostAck(
                f"injected lost ACK after Media accepted round {round_index}"
            )
        render = _adapt_media_result(
            result,
            request=request,
            source=source,
            plan=plan,
        )
        record = {
            "candidateId": plan["candidateId"],
            "plan": _clone(plan),
            "render": render,
            "renderPath": result["finalPath"],
            "mediaResultDigest": result["renderExportDigest"],
        }
        ledger.append_once(render_key, "media_r15_render", {
            "candidateId": plan["candidateId"],
            "roundIndex": round_index,
            "planDigest": plan["planDigest"],
            "editInputSha256": request["editInput"]["sha256"],
            "parentRenderSha256": parent_render_sha256,
            "renderSha256": render["render_sha256"],
            "renderSizeBytes": Path(result["finalPath"]).stat().st_size,
            "mediaResultDigest": result["renderExportDigest"],
            "reviewDirectiveDigest": _sha(request["reviewDirectives"]),
        })

        required_review = _required_review_record(
            source=source,
            record=record,
            round_index=round_index,
        )
        required_path = out_dir / f"review-request-r{round_index}.json"
        required_path.write_text(
            json.dumps(required_review, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        event = review_by_round.get(round_index)
        if event is None:
            report = _report(
                state="WAITING_FOR_REAL_REVIEW",
                source=source,
                pins=pins,
                ledger=ledger,
                round_index=round_index,
                real_review_executed=False,
                total_media_effects=total_media_effects,
                publish_handoff_effects=0,
                required_review=required_review,
            )
            (out_dir / "real_review_closed_loop.r26.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return report

        identity = event["reviewIdentity"]
        if identity in seen_invocation_reviews:
            raise ReviewReplayError("duplicate review event in one invocation")
        seen_invocation_reviews.add(identity)
        _validate_review_against_render(
            event,
            source=source,
            render_record=record,
            expected_round=round_index,
        )
        if event["captureMode"] != "external_live_review":
            real_review_executed = False
        handoff = event["handoff"]
        review_key = f"review:{round_index}"
        review_status = ledger.append_once(
            review_key,
            "growth_r23_real_review",
            {
                "reviewIdentity": identity,
                "reviewEventDigest": _review_event_digest(event),
                "handoffId": handoff["handoff_id"],
                "handoffDigest": handoff["handoff_digest"],
                "criticOutputDigest": handoff["binding"]["critic_output_digest"],
                "attachmentIdentity": handoff["binding"]["attachment_identity"],
                "renderSha256": handoff["binding"]["render_sha256"],
                "captureMode": event["captureMode"],
                "state": handoff["state"],
                "roundIndex": round_index,
            },
        )
        if review_status == "duplicate":
            prior = ledger.by_key[review_key]["payload"]
            if prior["reviewEventDigest"] != _review_event_digest(event):
                raise ReviewReplayError("conflicting recovered review event")

        if handoff["state"] == "targeted_reedit":
            if round_index >= MAX_REEDIT_ROUNDS:
                raise RoundRegression("targeted re-edit requested beyond round-2 boundary")
            next_plan = build_reedit_plan_from_handoff(
                parent_plan=plan,
                handoff=handoff,
            )
            input_path = Path(record["renderPath"])
            parent_render_sha256 = render["render_sha256"]
            parent_handoff = handoff
            plan = next_plan
            continue

        if handoff["state"] != "winner":
            terminal_state = (
                "human_review_required"
                if handoff["state"] == "human_review"
                else handoff["state"]
            )
            ledger.append_once("terminal", "nonpublishable_review_outcome", {
                "state": terminal_state,
                "roundIndex": round_index,
                "handoffDigest": handoff["handoff_digest"],
                "renderSha256": render["render_sha256"],
            })
            report = _report(
                state=terminal_state,
                source=source,
                pins=pins,
                ledger=ledger,
                round_index=round_index,
                real_review_executed=real_review_executed,
                total_media_effects=total_media_effects,
                publish_handoff_effects=0,
            )
            (out_dir / "real_review_closed_loop.r26.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return report

        if handoff["pairwise"]["mapped_candidate_id"] not in {
            None,
            record["candidateId"],
        }:
            raise ReviewLineageError("winner handoff maps to a different candidate")
        final_path = out_dir / "final.mp4"
        if Path(record["renderPath"]).resolve() != final_path.resolve():
            shutil.copyfile(Path(record["renderPath"]), final_path)
        final_asset = r21.probe_media(final_path)
        if final_asset.sha256 != render["render_sha256"]:
            raise ReviewLineageError("final.mp4 bytes differ from reviewed winner")
        if final_asset.size_bytes != Path(record["renderPath"]).stat().st_size:
            raise ReviewLineageError("final.mp4 size differs from reviewed winner")

        decision = _winner_decision(
            candidate_id=record["candidateId"],
            render_sha256=render["render_sha256"],
            handoff=handoff,
        )
        bundle = _final_bundle(
            record=record,
            handoff=handoff,
            decision=decision,
            source=source,
            analysis=analysis,
            directives=semantic_directives,
            ledger=ledger,
        )
        authorization = r23.synthetic_release_authorization(
            bundle=bundle,
            platform="tiktok",
            destination="privacy:SELF_ONLY",
        )
        publish_handoff = r23.build_editor_publish_handoff(
            editor_bundle=bundle,
            media_asset=final_asset,
            release_authorization=authorization,
            platform="tiktok",
            account_id="r26-no-live-account",
            destination="privacy:SELF_ONLY",
            credential_ref="vault-ref://r26/not-resolved",
            authorization_ref="oauth-grant-ref://r26/not-resolved",
            caption="R26 real-review closed-loop handoff",
            cta="Learn more",
            allow_synthetic_editor=False,
            growth_critic_validator=_terminal_review_validator,
        )
        bundle_path = out_dir / "editor-final-bundle.json"
        handoff_path = out_dir / "editor-publish-handoff.json"
        bundle_path.write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        handoff_path.write_text(
            json.dumps(publish_handoff, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if inject_lost_ack_after_handoff and "terminal" not in ledger.by_key:
            raise InjectedLostAck("injected lost ACK after publish handoff materialization")
        terminal_status = ledger.append_once("terminal", "publish_handoff_ready", {
            "winnerCandidateId": record["candidateId"],
            "roundIndex": round_index,
            "finalRenderSha256": final_asset.sha256,
            "finalRenderSizeBytes": final_asset.size_bytes,
            "growthR23HandoffDigest": handoff["handoff_digest"],
            "criticOutputDigest": handoff["binding"]["critic_output_digest"],
            "bundleDigest": bundle["bundleDigest"],
            "publishHandoffDigest": publish_handoff["handoffDigest"],
        })
        report = _report(
            state="publish_handoff_ready",
            source=source,
            pins=pins,
            ledger=ledger,
            round_index=round_index,
            real_review_executed=real_review_executed,
            total_media_effects=total_media_effects,
            publish_handoff_effects=1 if terminal_status == "committed" else 0,
            final_bundle=bundle,
            publish_handoff=publish_handoff,
        )
        report["winnerCandidateId"] = record["candidateId"]
        report["finalRenderSha256"] = final_asset.sha256
        report["finalRenderSizeBytes"] = final_asset.size_bytes
        report["growthR23HandoffDigest"] = handoff["handoff_digest"]
        report["criticOutputDigest"] = handoff["binding"]["critic_output_digest"]
        report["reportDigest"] = _sha({
            k: v for k, v in report.items() if k != "reportDigest"
        })
        (out_dir / "real_review_closed_loop.r26.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    raise RealReviewError("closed loop exhausted without terminal outcome")


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": "creator.real_review_closed_loop_r26.readiness.v1",
        "implementationStatus": "IMPLEMENTED",
        "realReviewExecutionStatus": "BLOCKED",
        "blocker": {
            "code": "MISSING_EXTERNAL_GROWTH_R23_REAL_REVIEW_EVENT",
            "requiredContract": REVIEW_EVENT_VERSION,
            "requiredGrowthHandoff": GROWTH_HANDOFF_VERSION,
            "requiredGrowthProducerSha": GROWTH_R23_SHA,
            "requiredEvidence": [
                "exact source SHA/size",
                "exact candidate render SHA/size",
                "exact attachment identity/SHA/size",
                "critic input/output digests",
                "Growth R23 handoff id/digest",
                "round index 0..2",
            ],
            "reason": (
                "No genuine externally captured Growth R23 attached-video review "
                "artifact is available in this agent chat."
            ),
        },
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "mediaProducerSha": MEDIA_R15_SHA,
        "growthProducer": _growth_producer_descriptor(),
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanLevelQualityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-real-review-r26")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--source", required=True)
    run.add_argument("--brief", required=True)
    run.add_argument("--media-checkout", required=True)
    run.add_argument("--growth-r23-checkout", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--review", action="append", default=[])
    run.add_argument("--allow-test-fixture", action="store_true")
    ready = sub.add_parser("readiness")
    ready.add_argument("--out")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        report = readiness_report()
        if args.out:
            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, sort_keys=True))
        return 2
    try:
        report = run_real_review_closed_loop(
            source_path=Path(args.source),
            brief=args.brief,
            media_checkout=Path(args.media_checkout),
            growth_r23_checkout=Path(args.growth_r23_checkout),
            out_dir=Path(args.out),
            review_paths=[Path(item) for item in args.review],
            allow_test_fixture=bool(args.allow_test_fixture),
        )
    except Exception as exc:
        blocked = {
            "contractVersion": CONTRACT_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanLevelQualityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
