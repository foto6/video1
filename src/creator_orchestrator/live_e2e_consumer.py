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

from . import autonomous_editor_loop as r22
from . import autonomous_reels as reels
from . import dynamic_live_review_loop as r28
from . import editor_publish_handoff as r23
from . import publish_execution as publish_exec
from . import real_review_closed_loop as r26

CONTRACT_VERSION = "creator.live_e2e_consumer.r29.v1"
LEDGER_VERSION = "creator.live_e2e_consumer_ledger.r29.v1"
REPORT_VERSION = "creator.live_e2e_consumer.r29.readiness.v1"
CREATOR_R28_BASE_SHA = "0d670abd4b5f04391fd1e6e1af4836a9fc92c8f3"
MAX_REEDIT_ROUNDS = 2

MEDIA_R21 = {
    "repository": "foto6/video2",
    "producerSha": "d753e9e4c1f4448386608a1425232dbc1dba87ea",
    "ciRunId": 36994000619,
    "reviewRoundContract": "media.review_round_bundle.r21.v1",
    "reviewRoundRequestContract": "media.review_round_request.r21.v1",
    "reviewRoundContractBlobSha1": "65358261775f0fcd2ab9e21f3f621aee977f29da",
    "reviewRoundSchemaBlobSha1": "f04925e317d849434852e6b706533f909da47b22",
    "reviewRoundManifestBlobSha1": "f76033375e7ee03b56491722e2e99e7334bd2cad",
    "reviewRoundImplementationBlobSha1": "c6f556b8a177b6182d787356625094cdcad5a58e",
    "reviewRoundRunnerBlobSha1": "c93e9a69de31b66189031932ccfa7f2c83cf043c",
    "applicationContract": "media.editorial_reedit_application.v1",
    "applicationContractBlobSha1": "6b3350c5f1524fe49a49d5637514e2fb1a808bcf",
    "applicationManifestBlobSha1": "502c32253d370e9b4e3d53f4a70de317f89dd21b",
    "applicationSchemaBlobSha1": "7cabf91f08ae11b68cc4a7eec88d358a46730289",
    "r19ImplementationBlobSha1": "8110a086b5b319bd2601860845c6afbf97681921",
    "r19RunnerBlobSha1": "7dbec612621aa42baaf2946cdac61d070e3ff41f",
    "renderExportContract": "media.render_export.v1",
    "renderExportManifestBlobSha1": "945acb01ff0269d89b91463aa8d862f500e055b2",
    "renderExportSchemaBlobSha1": "6353d32d785a2a1f1441bac4cfd0271b46b41d4a",
    "artifactId": 11221240371,
    "artifactName": "media-r21-round-pair-review",
    "artifactDigest": "sha256:1036800923196882590ace62edbaa123ab4250b9d242e14adba909ba256ab022",
}

GROWTH_R26 = {
    "repository": "foto6/video3",
    "producerSha": "e844ed2daaaca9e9694fe1e0fb6b8b7bfac69cbc",
    "ciRunId": 36994388154,
    "captureContract": "growth.dynamic_live_review_capture.r26.v1",
    "creatorEnvelopeContract": "growth.dynamic_creator_external_review_envelope.r26.v1",
    "dynamicHandoffContract": "growth.dynamic_creator_reedit_handoff.r26.v1",
    "contractBlobSha1": "700c942c4e9375eab5748f873d15f29f4b3f3826",
    "schemaBlobSha1": "de5f2d600cfece9829cf2b26ce1827516c7038c3",
    "implementationBlobSha1": "71fc2e372401ebf65d603681101eb1d7d0c520d7",
    "artifactId": 11220348361,
    "artifactName": "growth-r26-dynamic-review-capture",
    "artifactDigest": "sha256:011163ccff4ca89e4cbb32eee8dd74467ad02eb11c1970c9eb37868e2feecf4a",
}

BRIDGE_R30 = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "ceaee873231a8552c5b7324083baa800eec566a8",
    "ciRunId": 36993885456,
    "captureContract": "bridge.dynamic_existing_chat_video_review_capture.v1",
    "captureSchemaId": "bridge://bridge.dynamic_existing_chat_video_review_capture.v1",
    "handoffContract": "media.dynamic_review_handoff.v1",
    "handoffSchemaBlobSha1": "93968dc1fb65a334493acdb587b20753f0a8494a",
    "captureSchemaBlobSha1": "2cbe22ad6c7fe877764bad8dcfc1496aef3f3737",
    "implementationBlobSha1": "c5bd2f95a6d58a86cddd9a6fdc127e68e3346c20",
    "contractTestBlobSha1": "7e233ac8cc8107a9b0f7106d5118f02d328d40d0",
    "ubuntuArtifactId": 11220801997,
    "ubuntuArtifactDigest": "sha256:5712290e088d28539aae077bdc2c9f809931c21c2ef8e7ac55175fdb4acdf840",
    "windowsArtifactId": 11220977361,
    "windowsArtifactDigest": "sha256:58037c4a368a04e5c890c32b528bde965b792c31c04a7461f937ff8e6dc6bbb6",
}

MEDIA_R21_COMPAT = {
    **r28.MEDIA_R20_AUTHORITY,
    "producerSha": MEDIA_R21["producerSha"],
    "ciRunId": MEDIA_R21["ciRunId"],
}

SUPPORTED_STATES = {
    "targeted_reedit",
    "winner",
    "tie",
    "insufficient_evidence",
    "human_review",
    "reedit_limit_reached",
}
SUPPORTED_OPERATIONS = {
    "trim", "cut", "crop_scale_reframe", "speed_change",
    "fade_transition", "text_overlay", "subtitles_captions",
    "audio_duck_mix", "intro_outro_cta",
}


class R29Error(ValueError):
    pass


class AuthorityDrift(R29Error):
    pass


class EnvelopeDrift(R29Error):
    pass


class ReviewConflict(R29Error):
    pass


class RoundError(R29Error):
    pass


class MediaEvidenceError(R29Error):
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
        raise R29Error(f"{field} must be lowercase {size}-hex")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R29Error(f"{field} must be positive integer")
    return value


def _git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path(path).resolve(), text=True
    ).strip()


def _git_blob(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file_size(path: Path) -> int:
    return Path(path).stat().st_size


def verify_media_r21_checkout(path: Path) -> dict[str, Any]:
    root = Path(path).resolve()
    if _git_head(root) != MEDIA_R21["producerSha"]:
        raise AuthorityDrift("Media checkout producer SHA drift")
    checks = {
        "reviewRoundContractBlobSha1": root / "conformance/media.review_round_bundle.r21.v1/contract.json",
        "reviewRoundSchemaBlobSha1": root / "conformance/media.review_round_bundle.r21.v1/schema.json",
        "reviewRoundManifestBlobSha1": root / "conformance/media.review_round_bundle.r21.v1/manifest.json",
        "reviewRoundImplementationBlobSha1": root / "src/review-round-r21.js",
        "reviewRoundRunnerBlobSha1": root / "tools/build-r21-review-round.mjs",
        "applicationContractBlobSha1": root / "conformance/media.editorial_reedit_application.v1/contract.json",
        "applicationManifestBlobSha1": root / "conformance/media.editorial_reedit_application.v1/manifest.json",
        "applicationSchemaBlobSha1": root / "conformance/media.editorial_reedit_application.v1/schema.json",
        "r19ImplementationBlobSha1": root / "src/editorial-reedit-r19.js",
        "r19RunnerBlobSha1": root / "tools/run-r19-editorial-reedit.mjs",
        "renderExportManifestBlobSha1": root / "conformance/media.render_export.v1/manifest.json",
        "renderExportSchemaBlobSha1": root / "conformance/media.render_export.v1/schema.json",
    }
    observed = {}
    for key, file_path in checks.items():
        if not file_path.is_file():
            raise AuthorityDrift(f"Media authority file missing: {file_path}")
        observed[key] = _git_blob(file_path)
        if observed[key] != MEDIA_R21[key]:
            raise AuthorityDrift(f"Media authority blob drift: {key}")
    return {
        "authority": _clone(MEDIA_R21),
        "authorityDigest": _sha(MEDIA_R21),
        "checkoutSha": _git_head(root),
        "observedBlobs": observed,
    }


def verify_growth_r26_checkout(path: Path) -> dict[str, Any]:
    root = Path(path).resolve()
    if _git_head(root) != GROWTH_R26["producerSha"]:
        raise AuthorityDrift("Growth checkout producer SHA drift")
    checks = {
        "contractBlobSha1": root / "conformance/growth.dynamic_live_review_capture.r26.v1/contract.json",
        "schemaBlobSha1": root / "conformance/growth.dynamic_live_review_capture.r26.v1/schema.json",
        "implementationBlobSha1": root / "growth_analytics/dynamic_review_capture_r26.py",
    }
    observed = {}
    for key, file_path in checks.items():
        if not file_path.is_file():
            raise AuthorityDrift(f"Growth authority file missing: {file_path}")
        observed[key] = _git_blob(file_path)
        if observed[key] != GROWTH_R26[key]:
            raise AuthorityDrift(f"Growth authority blob drift: {key}")
    return {
        "authority": _clone(GROWTH_R26),
        "authorityDigest": _sha(GROWTH_R26),
        "checkoutSha": _git_head(root),
        "observedBlobs": observed,
    }


def verify_bridge_r30_checkout(path: Path) -> dict[str, Any]:
    root = Path(path).resolve()
    if _git_head(root) != BRIDGE_R30["producerSha"]:
        raise AuthorityDrift("Bridge checkout producer SHA drift")
    checks = {
        "handoffSchemaBlobSha1": root / "app/contracts/r30/media.dynamic_review_handoff.v1.schema.json",
        "captureSchemaBlobSha1": root / "app/contracts/r30/bridge.dynamic_existing_chat_video_review_capture.v1.schema.json",
        "implementationBlobSha1": root / "app/r30-dynamic-review.js",
        "contractTestBlobSha1": root / "app/r30-dynamic-review-contract.test.js",
    }
    observed = {}
    for key, file_path in checks.items():
        if not file_path.is_file():
            raise AuthorityDrift(f"Bridge authority file missing: {file_path}")
        observed[key] = _git_blob(file_path)
        if observed[key] != BRIDGE_R30[key]:
            raise AuthorityDrift(f"Bridge authority blob drift: {key}")
    return {
        "authority": _clone(BRIDGE_R30),
        "authorityDigest": _sha(BRIDGE_R30),
        "checkoutSha": _git_head(root),
        "observedBlobs": observed,
    }


def _expected_bridge_authority() -> dict[str, Any]:
    return {
        "contract_version": "growth.bridge_dynamic_capture_authority.r26.v1",
        "repository": BRIDGE_R30["repository"],
        "producer_sha": BRIDGE_R30["producerSha"],
        "ci_run_id": BRIDGE_R30["ciRunId"],
        "capture_contract": BRIDGE_R30["captureContract"],
        "capture_schema_id": BRIDGE_R30["captureSchemaId"],
        "contract_blob_sha1": BRIDGE_R30["handoffSchemaBlobSha1"],
        "schema_blob_sha1": BRIDGE_R30["captureSchemaBlobSha1"],
        "implementation_blob_sha1": BRIDGE_R30["implementationBlobSha1"],
    }


def _validate_media_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "repository", "producer_sha", "ci_run_id",
        "package_contract", "contract_blob_sha1", "schema_blob_sha1",
        "implementation_blob_sha1", "artifact_id", "artifact_name",
        "artifact_digest", "package_digest", "package_file_sha256",
        "evidence_file_sha256", "prompt_digest", "prompt_file_sha256",
        "sealed_mapping_digest", "sealed_mapping_file_sha256",
        "review_round", "source", "attachments",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EnvelopeDrift("Growth media authority fields mismatch")
    if value["contract_version"] != "growth.media_dynamic_review_authority.r26.v1":
        raise EnvelopeDrift("Growth media authority contract mismatch")
    if (
        value["repository"] != MEDIA_R21["repository"]
        or value["producer_sha"] != MEDIA_R21["producerSha"]
        or value["ci_run_id"] != MEDIA_R21["ciRunId"]
    ):
        raise AuthorityDrift("Growth envelope Media R21 producer drift")
    if value["package_contract"] != "media.dynamic_review_package.r21.v1":
        raise AuthorityDrift("Growth envelope is not an R21 dynamic package")
    expected_blobs = {
        "contract_blob_sha1": MEDIA_R21["reviewRoundContractBlobSha1"],
        "schema_blob_sha1": MEDIA_R21["reviewRoundSchemaBlobSha1"],
        "implementation_blob_sha1": MEDIA_R21["reviewRoundImplementationBlobSha1"],
    }
    for key, expected in expected_blobs.items():
        _hex(value[key], 40, f"media_authority.{key}")
        if value[key] != expected:
            raise AuthorityDrift(f"Growth envelope Media R21 blob drift: {key}")
    if (
        value["artifact_id"] != MEDIA_R21["artifactId"]
        or value["artifact_name"] != MEDIA_R21["artifactName"]
        or value["artifact_digest"] != MEDIA_R21["artifactDigest"]
    ):
        raise AuthorityDrift("Growth envelope Media R21 artifact authority drift")
    for key in (
        "package_digest", "package_file_sha256", "evidence_file_sha256",
        "prompt_digest", "prompt_file_sha256", "sealed_mapping_digest",
        "sealed_mapping_file_sha256",
    ):
        _hex(value[key], 64, f"media_authority.{key}")
    round_index = value["review_round"]
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or not 0 <= round_index <= MAX_REEDIT_ROUNDS
    ):
        raise RoundError("Media review round invalid")
    return _clone(value)


def _validate_dynamic_handoff(
    handoff: Mapping[str, Any],
    *,
    media_authority: Mapping[str, Any],
    bridge_authority: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "contract_version", "handoff_id", "handoff_digest", "state",
        "review_round", "max_reedit_rounds", "binding", "pairwise",
        "coverage", "summary_uncertainty", "directives",
        "evidence_boundary", "authority",
    }
    if not isinstance(handoff, Mapping) or set(handoff) != required:
        raise EnvelopeDrift("Growth dynamic handoff fields mismatch")
    if handoff["contract_version"] != GROWTH_R26["dynamicHandoffContract"]:
        raise EnvelopeDrift("Growth dynamic handoff contract mismatch")
    state = handoff["state"]
    if state not in SUPPORTED_STATES:
        raise EnvelopeDrift("Growth dynamic handoff state invalid")
    round_index = handoff["review_round"]
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or not 0 <= round_index <= MAX_REEDIT_ROUNDS
        or handoff["max_reedit_rounds"] != MAX_REEDIT_ROUNDS
    ):
        raise RoundError("Growth dynamic handoff round invalid")
    binding = handoff["binding"]
    binding_keys = {
        "source_id", "source_sha256", "source_size", "media_repository",
        "media_producer_sha", "package_digest", "sealed_mapping_digest",
        "review_round", "candidate_id", "candidate_round", "render_sha256",
        "render_size", "render_export_sha256", "attachment_sha256",
        "attachment_size", "attachment_mime_type", "critic_input_digest",
        "critic_output_digest", "capture_digest",
    }
    if not isinstance(binding, Mapping) or set(binding) != binding_keys:
        raise EnvelopeDrift("Growth dynamic binding fields mismatch")
    if (
        binding["media_repository"] != MEDIA_R21["repository"]
        or binding["media_producer_sha"] != MEDIA_R21["producerSha"]
        or binding["package_digest"] != media_authority["package_digest"]
        or binding["sealed_mapping_digest"] != media_authority["sealed_mapping_digest"]
        or binding["review_round"] != round_index
        or binding["candidate_round"] != round_index
    ):
        raise EnvelopeDrift("Growth dynamic binding authority/round drift")
    for key in (
        "source_sha256", "package_digest", "sealed_mapping_digest",
        "render_sha256", "render_export_sha256", "attachment_sha256",
        "critic_input_digest", "critic_output_digest", "capture_digest",
    ):
        _hex(binding[key], 64, f"binding.{key}")
    if (
        binding["render_sha256"] != binding["attachment_sha256"]
        or binding["render_size"] != binding["attachment_size"]
        or binding["attachment_mime_type"] != "video/mp4"
    ):
        raise EnvelopeDrift("reviewed render/attachment lineage mismatch")
    pairwise = handoff["pairwise"]
    if not isinstance(pairwise, Mapping) or set(pairwise) != {
        "model_facing_selection", "selected_candidate_id", "output_digest"
    }:
        raise EnvelopeDrift("Growth pairwise fields mismatch")
    if pairwise["model_facing_selection"] not in {
        "A", "B", "tie", "insufficient_evidence"
    }:
        raise EnvelopeDrift("Growth pairwise selection invalid")
    if pairwise["selected_candidate_id"] is not None and not isinstance(
        pairwise["selected_candidate_id"], str
    ):
        raise EnvelopeDrift("Growth pairwise selected candidate invalid")
    _hex(pairwise["output_digest"], 64, "pairwise.output_digest")

    coverage = handoff["coverage"]
    if (
        not isinstance(coverage, Mapping)
        or coverage.get("uninspected_possible") is not True
        or coverage.get("every_frame_inspected") is not False
        or coverage.get("coverage_uncertainty_preserved") is not True
        or not isinstance(coverage.get("inspected_ranges"), list)
    ):
        raise EnvelopeDrift("Growth coverage uncertainty drift")
    if not isinstance(handoff["summary_uncertainty"], str) or not handoff[
        "summary_uncertainty"
    ].strip():
        raise EnvelopeDrift("Growth summary uncertainty missing")

    directives = handoff["directives"]
    if not isinstance(directives, list):
        raise EnvelopeDrift("Growth directives must be array")
    if state == "targeted_reedit" and not directives:
        raise EnvelopeDrift("targeted_reedit requires directives")
    if state != "targeted_reedit" and directives:
        raise EnvelopeDrift("terminal/nonwinner state cannot carry directives")
    seen = set()
    directive_fields = {
        "operation", "start_ms", "end_ms", "defect_category", "severity",
        "source_observation_id", "evidence", "confidence", "uncertainty",
        "upstream_proposed_edit", "upstream_proposed_edit_executable",
        "binding", "directive_id",
    }
    for row in directives:
        if not isinstance(row, Mapping) or set(row) != directive_fields:
            raise EnvelopeDrift("Growth directive fields mismatch")
        if row.get("operation") not in SUPPORTED_OPERATIONS:
            raise EnvelopeDrift("unsupported Growth edit directive")
        if row.get("binding") != binding:
            raise EnvelopeDrift("Growth directive binding drift")
        if row.get("upstream_proposed_edit_executable") is not False:
            raise EnvelopeDrift("free-form proposed edit cannot be executable")
        if (
            isinstance(row.get("start_ms"), bool)
            or isinstance(row.get("end_ms"), bool)
            or not isinstance(row.get("start_ms"), int)
            or not isinstance(row.get("end_ms"), int)
            or row["start_ms"] < 0
            or row["end_ms"] <= row["start_ms"]
        ):
            raise EnvelopeDrift("Growth directive interval invalid")
        if (
            not isinstance(row["confidence"], (int, float))
            or isinstance(row["confidence"], bool)
            or not 0 <= float(row["confidence"]) <= 1
        ):
            raise EnvelopeDrift("Growth directive confidence invalid")
        directive_id = row.get("directive_id")
        if not isinstance(directive_id, str) or directive_id in seen:
            raise ReviewConflict("duplicate/invalid Growth directive identity")
        body = copy.deepcopy(row)
        body.pop("directive_id")
        if directive_id != "gdr26d1:" + _sha(body):
            raise EnvelopeDrift("Growth directive digest identity drift")
        seen.add(directive_id)
    if handoff["evidence_boundary"] != {
        "model_review_only": True,
        "human_ground_truth": False,
        "human_label": False,
        "human_rating_evidence": False,
        "live_platform_evidence": False,
        "free_form_proposed_edit_executable": False,
    }:
        raise EnvelopeDrift("Growth handoff evidence boundary drift")
    if handoff["authority"] != {
        "advisory_only": True,
        "creator_mutation": False,
        "media_mutation": False,
        "provider_mutation": False,
        "publish_authorized": False,
        "release_authorized": False,
    }:
        raise EnvelopeDrift("Growth handoff authority drift")
    expected_handoff_id = "gdr26h1:" + _sha({
        "capture_digest": binding["capture_digest"],
        "package_digest": binding["package_digest"],
        "candidate_id": binding["candidate_id"],
        "critic_output_digest": binding["critic_output_digest"],
        "pairwise_output_digest": pairwise["output_digest"],
        "review_round": handoff["review_round"],
    })
    if handoff["handoff_id"] != expected_handoff_id:
        raise EnvelopeDrift("Growth dynamic handoff identity mismatch")
    material = copy.deepcopy(handoff)
    digest = material["handoff_digest"]
    material["handoff_digest"] = ""
    if _sha(material) != digest:
        raise EnvelopeDrift("Growth dynamic handoff digest mismatch")
    return _clone(handoff)


def validate_growth_r26_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "envelope_id", "envelope_digest",
        "creator_event", "growth_r26", "media_authority",
        "bridge_authority", "capture", "review", "candidate",
        "evidence_boundary",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EnvelopeDrift("Growth R26 Creator envelope fields mismatch")
    if value["contract_version"] != GROWTH_R26["creatorEnvelopeContract"]:
        raise EnvelopeDrift("Growth R26 Creator envelope contract mismatch")
    growth = value["growth_r26"]
    if not isinstance(growth, Mapping) or set(growth) != {
        "repository", "producer_sha", "ci_run_id", "starting_r25_sha",
        "ingest_contract",
    }:
        raise EnvelopeDrift("Growth R26 producer fields mismatch")
    if (
        growth["repository"] != GROWTH_R26["repository"]
        or growth["producer_sha"] != GROWTH_R26["producerSha"]
        or growth["ci_run_id"] != GROWTH_R26["ciRunId"]
        or growth["ingest_contract"] != GROWTH_R26["captureContract"]
        or growth["starting_r25_sha"] != "2c441ebaa017c7da72461316401aeaf445e3d6e5"
    ):
        raise AuthorityDrift("Growth R26 producer authority drift")

    media = _validate_media_authority(value["media_authority"])
    bridge = value["bridge_authority"]
    if bridge != _expected_bridge_authority():
        raise AuthorityDrift("Bridge R30 authority drift in Growth envelope")

    event = value["creator_event"]
    if not isinstance(event, Mapping) or set(event) != {
        "contractVersion", "producer", "captureMode", "reviewIdentity", "handoff"
    }:
        raise EnvelopeDrift("Growth Creator event fields mismatch")
    if (
        event["contractVersion"] != "creator.dynamic_external_review_event.r26.v1"
        or event["captureMode"] != "external_live_review"
        or event["producer"] != {
            "repository": GROWTH_R26["repository"],
            "sha": GROWTH_R26["producerSha"],
            "ciRunId": GROWTH_R26["ciRunId"],
            "contract": GROWTH_R26["dynamicHandoffContract"],
        }
    ):
        raise AuthorityDrift("Growth Creator event authority drift")
    handoff = _validate_dynamic_handoff(
        event["handoff"],
        media_authority=media,
        bridge_authority=bridge,
    )
    if event["reviewIdentity"] != handoff["handoff_id"]:
        raise EnvelopeDrift("review identity differs from handoff")

    capture = value["capture"]
    if not isinstance(capture, Mapping) or set(capture) != {
        "capture_id", "capture_digest", "assistant_response_digest",
        "conversation", "response_shape",
        "normalization_generated_summary",
        "normalization_generated_pairwise_confidence",
    }:
        raise EnvelopeDrift("Growth capture provenance fields mismatch")
    for key in ("capture_digest", "assistant_response_digest"):
        _hex(capture[key], 64, f"capture.{key}")
    if handoff["binding"]["capture_digest"] != capture["capture_digest"]:
        raise EnvelopeDrift("handoff/capture digest mismatch")

    review = value["review"]
    if not isinstance(review, Mapping) or set(review) != {
        "package_digest", "sealed_mapping_digest", "review_round",
        "model_facing_selection", "selected_candidate_id",
    }:
        raise EnvelopeDrift("Growth review provenance fields mismatch")
    if (
        review["package_digest"] != media["package_digest"]
        or review["sealed_mapping_digest"] != media["sealed_mapping_digest"]
        or review["review_round"] != media["review_round"]
        or review["package_digest"] != handoff["binding"]["package_digest"]
        or review["sealed_mapping_digest"] != handoff["binding"]["sealed_mapping_digest"]
    ):
        raise EnvelopeDrift("package/sealed-mapping/round provenance drift")
    selected = review["selected_candidate_id"]
    if selected is not None and not isinstance(selected, str):
        raise EnvelopeDrift("selected candidate identity invalid")
    pairwise = handoff["pairwise"]
    if (
        pairwise.get("model_facing_selection") != review["model_facing_selection"]
        or pairwise.get("selected_candidate_id") != selected
    ):
        raise EnvelopeDrift("pairwise selected candidate identity drift")

    candidate = value["candidate"]
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidate_id", "candidate_round", "source_id", "source_sha256",
        "render_sha256", "render_size", "attachment_sha256",
        "attachment_size", "attachment_mime_type", "handoff_digest", "state",
    }:
        raise EnvelopeDrift("Growth candidate summary fields mismatch")
    binding = handoff["binding"]
    expected = {
        "candidate_id": binding["candidate_id"],
        "candidate_round": binding["candidate_round"],
        "source_id": binding["source_id"],
        "source_sha256": binding["source_sha256"],
        "render_sha256": binding["render_sha256"],
        "render_size": binding["render_size"],
        "attachment_sha256": binding["attachment_sha256"],
        "attachment_size": binding["attachment_size"],
        "attachment_mime_type": binding["attachment_mime_type"],
        "handoff_digest": handoff["handoff_digest"],
        "state": handoff["state"],
    }
    if candidate != expected:
        raise EnvelopeDrift("Growth candidate/handoff summary drift")
    if candidate["state"] == "winner" and selected != candidate["candidate_id"]:
        raise EnvelopeDrift("winner is not selected candidate")
    if candidate["state"] == "targeted_reedit" and selected == candidate["candidate_id"]:
        raise EnvelopeDrift("selected winner cannot simultaneously target re-edit")
    if value["evidence_boundary"] != {
        "model_evidence": True,
        "human_ground_truth": False,
        "human_rating_evidence": False,
        "human_parity_inferred": False,
        "provider_mutation": False,
    }:
        raise EnvelopeDrift("Growth envelope evidence boundary drift")
    expected_id = "gdr26ce1:" + _sha({
        "growth_producer_sha": GROWTH_R26["producerSha"],
        "capture_digest": capture["capture_digest"],
        "package_digest": review["package_digest"],
        "candidate_id": candidate["candidate_id"],
        "handoff_digest": candidate["handoff_digest"],
        "review_round": review["review_round"],
    })
    if value["envelope_id"] != expected_id:
        raise EnvelopeDrift("Growth envelope identity mismatch")
    material = copy.deepcopy(value)
    digest = material["envelope_digest"]
    material["envelope_digest"] = ""
    if _sha(material) != digest:
        raise EnvelopeDrift("Growth envelope digest mismatch")
    return _clone(value)


def normalize_review(envelope: Mapping[str, Any]) -> dict[str, Any]:
    envelope = validate_growth_r26_envelope(envelope)
    h = envelope["creator_event"]["handoff"]
    b = h["binding"]
    return {
        "state": h["state"],
        "roundIndex": h["review_round"],
        "source": {
            "sourceId": b["source_id"],
            "sha256": b["source_sha256"],
            "size": b["source_size"],
        },
        "candidate": {
            "candidateId": b["candidate_id"],
            "renderSha256": b["render_sha256"],
            "renderSize": b["render_size"],
            "renderExportSha256": b["render_export_sha256"],
            "renderProducerSha": b["media_producer_sha"],
            "attachmentIdentity": (
                "r29:" + b["package_digest"][:16] + ":" + b["candidate_id"]
            ),
            "attachmentSha256": b["attachment_sha256"],
            "attachmentSize": b["attachment_size"],
        },
        "criticOutputDigest": b["critic_output_digest"],
        "handoff": _clone(h),
        "captureId": envelope["capture"]["capture_id"],
        "captureDigest": envelope["capture"]["capture_digest"],
        "assistantResponseDigest": envelope["capture"]["assistant_response_digest"],
        "packageDigest": envelope["review"]["package_digest"],
        "sealedMappingDigest": envelope["review"]["sealed_mapping_digest"],
        "selectedCandidateId": envelope["review"]["selected_candidate_id"],
        "envelopeDigest": envelope["envelope_digest"],
    }


def validate_review_context(
    review: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    candidate_root: Path,
) -> None:
    context = r28.validate_candidate_context(context)
    c = context["candidate"]
    if review["roundIndex"] != c["roundIndex"]:
        raise RoundError("review round differs from reviewed candidate round")
    if review["roundIndex"] > MAX_REEDIT_ROUNDS:
        raise RoundError("review exceeds max re-edit round")
    expected_source = {
        "sourceId": context["source"]["sourceId"],
        "sha256": context["source"]["sha256"],
        "size": context["source"]["size"],
    }
    if review["source"] != expected_source:
        raise EnvelopeDrift("review source differs from candidate context")
    for key, ctx_key in (
        ("candidateId", "candidateId"),
        ("renderSha256", "renderSha256"),
        ("renderSize", "renderSize"),
        ("renderExportSha256", "renderExportSha256"),
        ("renderProducerSha", "renderProducerSha"),
    ):
        if review["candidate"][key] != c[ctx_key]:
            raise EnvelopeDrift(f"review candidate drift: {key}")
    if (
        review["candidate"]["attachmentSha256"] != c["renderSha256"]
        or review["candidate"]["attachmentSize"] != c["renderSize"]
    ):
        raise EnvelopeDrift("review attachment bytes differ from render")
    root = Path(candidate_root).resolve()
    for rel, expected_sha, expected_size in (
        (c["finalPath"], c["renderSha256"], c["renderSize"]),
        (c["renderExportPath"], c["renderExportSha256"], None),
    ):
        p = (root / rel).resolve()
        try:
            p.relative_to(root)
        except ValueError as exc:
            raise EnvelopeDrift("candidate path escapes root") from exc
        if not p.is_file() or _file_sha(p) != expected_sha:
            raise EnvelopeDrift("reviewed candidate file hash mismatch")
        if expected_size is not None and _file_size(p) != expected_size:
            raise EnvelopeDrift("reviewed candidate file size mismatch")


def _require_targeted_round(review: Mapping[str, Any]) -> None:
    if review.get("state") != "targeted_reedit":
        raise RoundError("review is not targeted_reedit")
    round_index = review.get("roundIndex")
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or round_index < 0
        or round_index >= MAX_REEDIT_ROUNDS
    ):
        raise RoundError("targeted re-edit would exceed max two rounds")


def _legacy_media_handoff(dynamic: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility adapter for the exact R19 runtime embedded in Media R21.

    The executable directive set is copied exactly from Growth R26. The legacy
    authority literals below satisfy Media R19's frozen validator only; Creator
    never treats them as current review authority. Current authority remains
    the validated Growth R26 + Bridge R30 envelope and is persisted separately.
    """
    b = dynamic["binding"]
    legacy_binding = {
        "source_id": b["source_id"],
        "source_sha256": b["source_sha256"],
        "source_size": b["source_size"],
        "media_repository": b["media_repository"],
        "media_producer_sha": b["media_producer_sha"],
        "candidate_id": b["candidate_id"],
        "render_sha256": b["render_sha256"],
        "render_size": b["render_size"],
        "render_export_sha256": b["render_export_sha256"],
        "attachment_sha256": b["attachment_sha256"],
        "attachment_size": b["attachment_size"],
        "attachment_identity": "r29:" + b["package_digest"][:16] + ":" + b["candidate_id"],
        "review_bundle_digest": b["package_digest"],
        "critic_input_digest": b["critic_input_digest"],
        "critic_output_digest": b["critic_output_digest"],
    }
    directives = []
    for row in dynamic["directives"]:
        body = {
            "operation": row["operation"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "defect_category": row["defect_category"],
            "severity": row["severity"],
            "source_observation_id": row["source_observation_id"],
            "evidence": row["evidence"],
            "confidence": row["confidence"],
            "uncertainty": row["uncertainty"],
            "upstream_proposed_edit": row["upstream_proposed_edit"],
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(legacy_binding),
        }
        body["directive_id"] = "gcrd1:" + _sha(body)
        directives.append(body)
    coverage = dynamic["coverage"]
    legacy = {
        "contract_version": "growth.creator_reedit_handoff.v1",
        "adapter_version": "growth.web_video_critic_reedit_adapter.v1",
        "handoff_id": "",
        "handoff_digest": "",
        "state": "targeted_reedit",
        "reedit_round": dynamic["review_round"],
        "max_reedit_rounds": 2,
        "binding": legacy_binding,
        "pairwise": {
            "selection": dynamic["pairwise"]["model_facing_selection"],
            "mapped_candidate_id": dynamic["pairwise"]["selected_candidate_id"],
            "output_digest": dynamic["pairwise"]["output_digest"],
        },
        "coverage": {
            "method": coverage.get("method", "web_attached_video"),
            "inspected_ranges": coverage["inspected_ranges"],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": coverage.get("notes") or "Growth R26 dynamic review coverage",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": dynamic["summary_uncertainty"],
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
    legacy["handoff_id"] = "gcrh1:" + _sha({
        "critic_output_digest": legacy_binding["critic_output_digest"],
        "pairwise_output_digest": legacy["pairwise"]["output_digest"],
        "reedit_round": legacy["reedit_round"],
    })
    material = copy.deepcopy(legacy)
    material["handoff_digest"] = ""
    legacy["handoff_digest"] = _sha(material)
    r26.parse_growth_r23_handoff(legacy)
    return legacy


def _compat_review(review: Mapping[str, Any]) -> dict[str, Any]:
    result = _clone(review)
    result["handoff"] = _legacy_media_handoff(review["handoff"])
    return result


def _next_context(
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
    for p in (final_path, app_path, export_path):
        try:
            p.relative_to(root)
        except ValueError as exc:
            raise MediaEvidenceError("Media output escapes candidate root") from exc
    candidate = {
        "candidateId": (
            prior["candidate"]["candidateId"]
            + f":r29:{media_result['evidence']['nextRoundIndex']}:"
            + after["sha256"][:16]
        ),
        "roundIndex": media_result["evidence"]["nextRoundIndex"],
        "finalPath": final_path.relative_to(root).as_posix(),
        "renderSha256": after["sha256"],
        "renderSize": after["size"],
        "renderExportPath": export_path.relative_to(root).as_posix(),
        "renderExportSha256": after["renderExportSha256"],
        "renderExportDigest": after["renderExportDigest"],
        "renderProducerSha": MEDIA_R21["producerSha"],
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


def _descriptor(context: Mapping[str, Any]) -> dict[str, Any]:
    return r28._dynamic_descriptor(context)


def build_media_r21_round_bundle(
    *,
    media_checkout: Path,
    candidate_root: Path,
    baseline: Mapping[str, Any],
    challenger: Mapping[str, Any],
    envelope: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    verify_media_r21_checkout(media_checkout)
    baseline = r28.validate_candidate_context(baseline)
    challenger = r28.validate_candidate_context(challenger)
    review = envelope["review"]
    if challenger["candidate"]["roundIndex"] != baseline["candidate"]["roundIndex"] + 1:
        raise RoundError("R21 challenger is not baseline round N+1")
    if challenger["candidate"]["roundIndex"] > MAX_REEDIT_ROUNDS:
        raise RoundError("R21 challenger exceeds max round")
    request = {
        "contractVersion": MEDIA_R21["reviewRoundRequestContract"],
        "review": {
            "mode": "targeted_reedit",
            "baseline": {
                "candidate": _descriptor(baseline),
                "briefLineageDigest": baseline["briefDigest"],
            },
            "challenger": {
                "candidate": _descriptor(challenger),
                "briefLineageDigest": challenger["briefDigest"],
            },
            "priorReview": {
                "contractVersion": "media.prior_review_selection.r21.v1",
                "selectedCandidateId": baseline["candidate"]["candidateId"],
                "reviewRound": baseline["candidate"]["roundIndex"],
                "reviewPackageDigest": review["package_digest"],
                "sealedMappingDigest": review["sealed_mapping_digest"],
                "decisionEvidenceDigest": envelope["candidate"]["handoff_digest"],
                "evidenceType": "growth_reedit_handoff",
            },
        },
    }
    out_dir = Path(out_dir).resolve()
    root = Path(candidate_root).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        out_dir.relative_to(root)
    except ValueError as exc:
        raise MediaEvidenceError("R21 package output must stay in candidate root") from exc
    request_path = out_dir / "media.review_round_request.r21.v1.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    package_dir = out_dir / "package"
    env = dict(os.environ)
    env["GITHUB_SHA"] = MEDIA_R21["producerSha"]
    result = subprocess.run(
        [
            "node",
            str(Path(media_checkout).resolve() / "tools/build-r21-review-round.mjs"),
            "--request", str(request_path),
            "--sandbox-root", str(root),
            "--output-dir", str(package_dir),
        ],
        cwd=Path(media_checkout).resolve(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise MediaEvidenceError("Media R21 package failed: " + result.stderr[-5000:])
    lines = [x for x in result.stdout.splitlines() if x.startswith("R21_REVIEW_ROUND ")]
    if not lines:
        raise MediaEvidenceError("Media R21 package result line missing")
    log = json.loads(lines[-1].split(" ", 1)[1])
    bundle_path = package_dir / "media.review_round_bundle.r21.v1.json"
    evidence_path = package_dir / "media.review_round_bundle.r21.evidence.json"
    if not bundle_path.is_file() or not evidence_path.is_file():
        raise MediaEvidenceError("Media R21 package evidence incomplete")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        bundle.get("contractVersion") != MEDIA_R21["reviewRoundContract"]
        or bundle.get("producer") != {
            "repository": MEDIA_R21["repository"],
            "sha": MEDIA_R21["producerSha"],
        }
        or bundle.get("reviewRound") != challenger["candidate"]["roundIndex"]
        or bundle.get("humanQuality") is not False
    ):
        raise MediaEvidenceError("Media R21 bundle authority/round drift")
    if (
        log.get("packageDigest") != evidence.get("packageDigest")
        or log.get("sealedMappingDigest") != evidence.get("sealedMappingDigest")
        or _file_sha(bundle_path) != evidence.get("bundleFileSha256")
    ):
        raise MediaEvidenceError("Media R21 package digest drift")
    lineage = bundle.get("roundLineage") or {}
    compatibility_handoff = _legacy_media_handoff(
        envelope["creator_event"]["handoff"]
    )
    if (
        lineage.get("baselineReviewCandidateId") != baseline["candidate"]["candidateId"]
        or lineage.get("childReviewCandidateId") != challenger["candidate"]["candidateId"]
        or lineage.get("parentRenderSha256") != baseline["candidate"]["renderSha256"]
        or lineage.get("childRenderSha256") != challenger["candidate"]["renderSha256"]
        or lineage.get("growthHandoffDigest")
        != compatibility_handoff["handoff_digest"]
    ):
        raise MediaEvidenceError("Media R21 round lineage drift")
    out = {
        "contractVersion": "creator.media_r21_next_review_boundary.r29.v1",
        "producer": _clone(MEDIA_R21),
        "reviewRound": bundle["reviewRound"],
        "baselineCandidateId": baseline["candidate"]["candidateId"],
        "challengerCandidateId": challenger["candidate"]["candidateId"],
        "packageDigest": evidence["packageDigest"],
        "bundleFileSha256": evidence["bundleFileSha256"],
        "sealedMappingDigest": evidence["sealedMappingDigest"],
        "sealedMappingFileSha256": evidence["sealedMappingFileSha256"],
        "roundLineageDigest": evidence["roundLineageDigest"],
        "dynamicGrowthHandoffDigest": envelope["candidate"]["handoff_digest"],
        "mediaCompatibilityHandoffDigest": compatibility_handoff["handoff_digest"],
        "promptDigest": evidence["promptDigest"],
        "promptFileSha256": evidence["promptFileSha256"],
        "transportHandoffFileSha256": evidence["transportHandoffFileSha256"],
        "bundlePath": str(bundle_path),
        "evidencePath": str(evidence_path),
        "providerInvoked": False,
        "humanQualityClaimed": False,
    }
    out["boundaryDigest"] = _sha(out)
    return out


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                event = json.loads(line)
                material = dict(event)
                digest = material.pop("eventDigest", None)
                if (
                    event.get("ledgerVersion") != LEDGER_VERSION
                    or event.get("sequence") != len(self.events) + 1
                    or _sha(material) != digest
                    or event.get("eventKey") in self.by_key
                ):
                    raise ReviewConflict("R29 ledger corruption")
                self.events.append(event)
                self.by_key[event["eventKey"]] = event

    def append_once(self, key: str, event_type: str, payload: Mapping[str, Any]) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if prior["eventType"] != event_type or prior["payload"] != normalized:
                raise ReviewConflict(f"conflicting replay for {key}")
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
        return _sha([e for e in self.events if e["eventKey"] != "terminal"])


def _media_render_from_context(context: Mapping[str, Any]) -> dict[str, Any]:
    c = context["candidate"]
    return {
        "contract_version": "creator.media_r21_render.r29.v1",
        "repository": MEDIA_R21["repository"],
        "commit_sha": MEDIA_R21["producerSha"],
        "source_class": "provider",
        "source_id": context["source"]["sourceId"],
        "source_sha256": context["source"]["sha256"],
        "candidate_id": c["candidateId"],
        "round_index": c["roundIndex"],
        "plan_digest": _sha({
            "candidateId": c["candidateId"],
            "renderSha256": c["renderSha256"],
            "roundIndex": c["roundIndex"],
        }),
        "render_sha256": c["renderSha256"],
        "timeline_digest": _sha(context["timeline"]),
        "artifact_manifest_digest": c["renderExportSha256"],
        "technical_qa": {
            "passed": True,
            "qa_digest": _sha({"renderExportSha256": c["renderExportSha256"]}),
            "checks": [],
        },
        "render_provenance": {
            "renderExportDigest": c["renderExportDigest"],
            "editorialApplication": c["editorialApplication"],
            "mediaR21ProducerSha": MEDIA_R21["producerSha"],
        },
        "human_ground_truth": False,
    }


def _winner_bundle(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    ledger: Ledger,
) -> dict[str, Any]:
    c = context["candidate"]
    decision = {
        "contractVersion": r22.DECISION_VERSION,
        "roundIndex": c["roundIndex"],
        "state": "winner",
        "winnerCandidateId": c["candidateId"],
        "reason": "terminal exact Growth R26 dynamic live-review winner",
        "evaluations": [{
            "candidateId": c["candidateId"],
            "renderSha256": c["renderSha256"],
            "growthEnvelopeDigest": envelope["envelope_digest"],
            "handoffDigest": envelope["candidate"]["handoff_digest"],
            "assistantResponseDigest": envelope["capture"]["assistant_response_digest"],
        }],
        "humanLevelQualityClaimed": False,
        "aestheticSuperiorityClaimed": False,
    }
    decision["decisionDigest"] = _sha(decision)
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": c["candidateId"],
        "roundIndex": c["roundIndex"],
        "render": _media_render_from_context(context),
        "critic": _clone(envelope),
        "decision": decision,
        "lineage": {
            "loopId": context["loopId"],
            "sourceId": context["source"]["sourceId"],
            "sourceSha256": context["source"]["sha256"],
            "briefDigest": context["briefDigest"],
            "semanticAnalysisDigest": context["semanticAnalysisDigest"],
            "semanticDirectivesDigest": context["semanticDirectivesDigest"],
            "ledgerDigest": ledger.preterminal_digest,
            "growthCriticPin": {
                "producerSha": GROWTH_R26["producerSha"],
                "contract": GROWTH_R26["creatorEnvelopeContract"],
                "contractBlobSha1": GROWTH_R26["contractBlobSha1"],
                "schemaBlobSha1": GROWTH_R26["schemaBlobSha1"],
                "implementationBlobSha1": GROWTH_R26["implementationBlobSha1"],
                "envelopeDigest": envelope["envelope_digest"],
                "assistantResponseDigest": envelope["capture"]["assistant_response_digest"],
            },
            "mediaRenderExport": {
                "acceptedMediaR21ProducerSha": MEDIA_R21["producerSha"],
                "renderExportContract": MEDIA_R21["renderExportContract"],
                "reviewRoundContract": MEDIA_R21["reviewRoundContract"],
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def _validate_r29_media_render(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_source_sha256: str,
    expected_candidate_id: str,
    expected_plan_digest: str,
) -> dict[str, Any]:
    required = {
        "contract_version", "repository", "commit_sha", "source_class",
        "source_id", "source_sha256", "candidate_id", "round_index",
        "plan_digest", "render_sha256", "timeline_digest",
        "artifact_manifest_digest", "technical_qa", "render_provenance",
        "human_ground_truth",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise r23.EditorPublishHandoffError("R29 Media render fields mismatch")
    if value["contract_version"] != "creator.media_r21_render.r29.v1":
        raise r23.EditorPublishHandoffError("R29 Media render contract mismatch")
    if (
        value["repository"] != MEDIA_R21["repository"]
        or value["commit_sha"] != MEDIA_R21["producerSha"]
    ):
        raise r23.EditorPublishHandoffError("R29 Media R21 authority mismatch")
    if value["source_class"] != "provider":
        raise r23.EditorPublishHandoffError("R29 winner requires provider Media evidence")
    if value["source_id"] != expected_source_id:
        raise r23.EditorPublishHandoffError("R29 Media source ID mismatch")
    if value["source_sha256"] != expected_source_sha256:
        raise r23.EditorPublishHandoffError("R29 Media source SHA mismatch")
    if value["candidate_id"] != expected_candidate_id:
        raise r23.EditorPublishHandoffError("R29 Media candidate mismatch")
    if value["plan_digest"] != expected_plan_digest:
        raise r23.EditorPublishHandoffError("R29 Media plan digest mismatch")
    if (
        isinstance(value["round_index"], bool)
        or not isinstance(value["round_index"], int)
        or not 0 <= value["round_index"] <= MAX_REEDIT_ROUNDS
    ):
        raise r23.EditorPublishHandoffError("R29 Media round invalid")
    for key in (
        "source_sha256", "plan_digest", "render_sha256", "timeline_digest",
        "artifact_manifest_digest",
    ):
        _hex(value[key], 64, "R29 Media " + key)
    qa = value["technical_qa"]
    if (
        not isinstance(qa, Mapping)
        or qa.get("passed") is not True
        or not isinstance(qa.get("checks"), list)
    ):
        raise r23.EditorOutcomeIneligible("R29 Media technical QA failed")
    _hex(qa.get("qa_digest"), 64, "R29 Media technical QA digest")
    if value["human_ground_truth"] is not False:
        raise r23.EditorPublishHandoffError("R29 Media cannot claim human ground truth")
    return _clone(value)


def _validate_terminal_r29_review(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_render_sha256: str,
) -> dict[str, Any]:
    envelope = validate_growth_r26_envelope(value)
    if envelope["candidate"]["state"] != "winner":
        raise r23.EditorOutcomeIneligible(
            "only terminal Growth R26 winner may create publish handoff"
        )
    if envelope["candidate"]["source_id"] != expected_source_id:
        raise r23.EditorPublishHandoffError("R29 terminal review source mismatch")
    if envelope["candidate"]["render_sha256"] != expected_render_sha256:
        raise r23.EditorPublishHandoffError("R29 terminal review render mismatch")
    if envelope["review"]["selected_candidate_id"] != envelope["candidate"]["candidate_id"]:
        raise r23.EditorPublishHandoffError("R29 terminal selected candidate mismatch")
    return envelope


def materialize_publish_handoff(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    bundle: Mapping[str, Any],
    final_path: Path,
    release_authorization: Mapping[str, Any],
    publish_target: Mapping[str, str],
) -> dict[str, Any]:
    envelope = validate_growth_r26_envelope(envelope)
    if envelope["candidate"]["state"] != "winner":
        raise r23.EditorOutcomeIneligible("nonwinner cannot create publish handoff")
    required_target = {
        "platform", "accountId", "destination", "credentialRef",
        "authorizationRef", "caption", "cta",
    }
    if not isinstance(publish_target, Mapping) or set(publish_target) != required_target:
        raise R29Error("publish target fields mismatch")
    asset = publish_exec.probe_media(final_path)
    if (
        asset.sha256 != context["candidate"]["renderSha256"]
        or asset.size_bytes != context["candidate"]["renderSize"]
    ):
        raise EnvelopeDrift("publish final.mp4 differs from reviewed winner bytes")
    return r23.build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=asset,
        release_authorization=release_authorization,
        platform=publish_target["platform"],
        account_id=publish_target["accountId"],
        destination=publish_target["destination"],
        credential_ref=publish_target["credentialRef"],
        authorization_ref=publish_target["authorizationRef"],
        caption=publish_target["caption"],
        cta=publish_target["cta"],
        allow_synthetic_editor=False,
        media_render_validator=_validate_r29_media_render,
        growth_critic_validator=_validate_terminal_r29_review,
    )


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": REPORT_VERSION,
        "creatorBaseSha": CREATOR_R28_BASE_SHA,
        "state": "BLOCKED_WAITING_LIVE_GROWTH_OUTPUT",
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": False,
        "REAL_REEDIT_EXECUTED": False,
        "NEXT_REVIEW_PACKAGE_READY": False,
        "PUBLISH_HANDOFF_READY": False,
        "mediaR21": _clone(MEDIA_R21),
        "growthR26": _clone(GROWTH_R26),
        "bridgeR30": _clone(BRIDGE_R30),
        "missing": {
            "code": "MISSING_GENUINE_GROWTH_R26_DYNAMIC_CREATOR_ENVELOPE",
            "contract": GROWTH_R26["creatorEnvelopeContract"],
            "requiredProducerSha": GROWTH_R26["producerSha"],
            "requiredBridgeProducerSha": BRIDGE_R30["producerSha"],
            "note": "No genuine coordinator-run Growth output is attached or available in this Creator agent context.",
        },
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanQualityClaimed": False,
        "fabricatedLiveEvidence": False,
    }
    report["reportDigest"] = _sha(report)
    return report


def run_consumer(
    *,
    media_checkout: Path,
    growth_checkout: Path,
    bridge_checkout: Path,
    candidate_root: Path,
    candidate_context_path: Path,
    growth_output_path: Path,
    out_dir: Path,
    release_authorization_path: Path | None = None,
    publish_target: Mapping[str, str] | None = None,
    inject_lost_ack_after_media: bool = False,
) -> dict[str, Any]:
    media_pin = verify_media_r21_checkout(media_checkout)
    growth_pin = verify_growth_r26_checkout(growth_checkout)
    bridge_pin = verify_bridge_r30_checkout(bridge_checkout)
    context = r28.validate_candidate_context(
        json.loads(Path(candidate_context_path).read_text(encoding="utf-8"))
    )
    envelope = validate_growth_r26_envelope(
        json.loads(Path(growth_output_path).read_text(encoding="utf-8"))
    )
    review = normalize_review(envelope)
    validate_review_context(review, context, candidate_root=candidate_root)

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out_dir / "live-e2e-consumer-ledger.jsonl")
    ledger.append_once("start", "r29_started", {
        "contextDigest": context["contextDigest"],
        "mediaAuthorityDigest": media_pin["authorityDigest"],
        "growthAuthorityDigest": growth_pin["authorityDigest"],
        "bridgeAuthorityDigest": bridge_pin["authorityDigest"],
    })
    round_index = review["roundIndex"]
    review_status = ledger.append_once(
        f"review:{round_index}",
        "growth_r26_live_review",
        {
            "envelopeDigest": review["envelopeDigest"],
            "captureId": review["captureId"],
            "captureDigest": review["captureDigest"],
            "assistantResponseDigest": review["assistantResponseDigest"],
            "packageDigest": review["packageDigest"],
            "sealedMappingDigest": review["sealedMappingDigest"],
            "handoffDigest": envelope["candidate"]["handoff_digest"],
            "state": review["state"],
            "candidateId": review["candidate"]["candidateId"],
            "renderSha256": review["candidate"]["renderSha256"],
            "roundIndex": round_index,
        },
    )

    state = review["state"]
    if state == "targeted_reedit":
        _require_targeted_round(review)
        media_key = "media:" + review["envelopeDigest"]
        prior = ledger.by_key.get(media_key)
        compat = _compat_review(review)
        media_result = r28.execute_media_reedit(
            media_checkout=media_checkout,
            media_profile=MEDIA_R21_COMPAT,
            candidate_root=candidate_root,
            context=context,
            review=compat,
            out_dir=Path(candidate_root).resolve(),
        )
        if (
            inject_lost_ack_after_media
            and prior is None
            and media_result["evidence"]["logicalEffects"] == 1
        ):
            raise InjectedLostAck("injected lost ACK after exact Media R21 re-edit")
        ledger.append_once(media_key, "media_r21_reedit", {
            "envelopeDigest": review["envelopeDigest"],
            "dynamicHandoffDigest": envelope["candidate"]["handoff_digest"],
            "compatHandoffDigest": compat["handoff"]["handoff_digest"],
            "resultDigest": media_result["evidence"]["resultDigest"],
            "beforeSha256": media_result["evidence"]["before"]["sha256"],
            "afterSha256": media_result["evidence"]["after"]["sha256"],
            "applicationSidecarSha256": media_result["evidence"]["after"]["applicationSidecarSha256"],
            "renderExportSha256": media_result["evidence"]["after"]["renderExportSha256"],
        })
        next_context = _next_context(
            prior=context,
            media_result=media_result,
            candidate_root=candidate_root,
        )
        (out_dir / "next-candidate-context.json").write_text(
            json.dumps(next_context, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        package_root = (
            Path(candidate_root).resolve()
            / ".creator-r29-r21-packages"
            / review["envelopeDigest"][:24]
        )
        package = build_media_r21_round_bundle(
            media_checkout=media_checkout,
            candidate_root=candidate_root,
            baseline=context,
            challenger=next_context,
            envelope=envelope,
            out_dir=package_root,
        )
        ledger.append_once(
            f"package:{next_context['candidate']['roundIndex']}",
            "media_r21_next_review_package",
            {
                "boundaryDigest": package["boundaryDigest"],
                "packageDigest": package["packageDigest"],
                "sealedMappingDigest": package["sealedMappingDigest"],
                "roundLineageDigest": package["roundLineageDigest"],
                "baselineCandidateId": package["baselineCandidateId"],
                "challengerCandidateId": package["challengerCandidateId"],
            },
        )
        (out_dir / "next-review-boundary.json").write_text(
            json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        report = {
            "contractVersion": REPORT_VERSION,
            "state": "BLOCKED_WAITING_LIVE_GROWTH_OUTPUT",
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": True,
            "REAL_REEDIT_EXECUTED": True,
            "NEXT_REVIEW_PACKAGE_READY": True,
            "PUBLISH_HANDOFF_READY": False,
            "reviewReplay": review_status == "duplicate",
            "mediaReplay": media_result["evidence"]["replayed"],
            "roundIndex": round_index,
            "nextRoundIndex": next_context["candidate"]["roundIndex"],
            "beforeRenderSha256": media_result["evidence"]["before"]["sha256"],
            "afterRenderSha256": media_result["evidence"]["after"]["sha256"],
            "afterRenderSize": media_result["evidence"]["after"]["size"],
            "mediaResultDigest": media_result["evidence"]["resultDigest"],
            "nextContextDigest": next_context["contextDigest"],
            "nextReviewPackageDigest": package["packageDigest"],
            "nextReviewBoundaryDigest": package["boundaryDigest"],
            "growthEnvelopeDigest": review["envelopeDigest"],
            "assistantResponseDigest": review["assistantResponseDigest"],
            "maxReeditRounds": MAX_REEDIT_ROUNDS,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
    elif state == "winner":
        root = Path(candidate_root).resolve()
        source_path = (root / context["candidate"]["finalPath"]).resolve()
        final_path = out_dir / "final.mp4"
        shutil.copyfile(source_path, final_path)
        asset = publish_exec.probe_media(final_path)
        if (
            asset.sha256 != context["candidate"]["renderSha256"]
            or asset.size_bytes != context["candidate"]["renderSize"]
        ):
            raise EnvelopeDrift("winner final.mp4 differs from reviewed candidate")
        bundle = _winner_bundle(context=context, envelope=envelope, ledger=ledger)
        (out_dir / "editor-final-bundle.json").write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        publish_handoff = None
        if release_authorization_path is not None:
            if publish_target is None:
                raise R29Error("publish target required with release authorization")
            # R29 never executes the provider. It only materializes the existing R23 handoff.
            auth = json.loads(Path(release_authorization_path).read_text(encoding="utf-8"))
            publish_handoff = materialize_publish_handoff(
                context=context,
                envelope=envelope,
                bundle=bundle,
                final_path=final_path,
                release_authorization=auth,
                publish_target=publish_target,
            )
            (out_dir / "editor-publish-handoff.json").write_text(
                json.dumps(publish_handoff, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            ledger.append_once("publish-handoff", "publish_handoff_materialized", {
                "handoffDigest": publish_handoff["handoffDigest"],
                "providerInvoked": False,
            })
        ledger.append_once("terminal", "winner", {
            "envelopeDigest": envelope["envelope_digest"],
            "winnerCandidateId": context["candidate"]["candidateId"],
            "finalRenderSha256": asset.sha256,
            "bundleDigest": bundle["bundleDigest"],
            "publishHandoffDigest": None if publish_handoff is None else publish_handoff["handoffDigest"],
        })
        report = {
            "contractVersion": REPORT_VERSION,
            "state": "PUBLISH_HANDOFF_READY" if publish_handoff is not None else "WINNER_AWAITING_RELEASE_AUTHORIZATION",
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": True,
            "REAL_REEDIT_EXECUTED": context["candidate"]["roundIndex"] > 0,
            "NEXT_REVIEW_PACKAGE_READY": False,
            "PUBLISH_HANDOFF_READY": publish_handoff is not None,
            "winnerCandidateId": context["candidate"]["candidateId"],
            "finalRenderSha256": asset.sha256,
            "finalRenderSize": asset.size_bytes,
            "bundleDigest": bundle["bundleDigest"],
            "publishHandoffDigest": None if publish_handoff is None else publish_handoff["handoffDigest"],
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
    else:
        terminal = "human_review_required" if state in {"human_review", "reedit_limit_reached"} else state
        ledger.append_once("terminal", "nonpublishable", {
            "state": terminal,
            "envelopeDigest": envelope["envelope_digest"],
            "renderSha256": context["candidate"]["renderSha256"],
        })
        report = {
            "contractVersion": REPORT_VERSION,
            "state": terminal,
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": True,
            "REAL_REEDIT_EXECUTED": False,
            "NEXT_REVIEW_PACKAGE_READY": False,
            "PUBLISH_HANDOFF_READY": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanQualityClaimed": False,
            "ledgerDigest": ledger.digest,
        }
    report["reportDigest"] = _sha(report)
    (out_dir / "live_e2e_consumer.r29.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def build_test_envelope(
    *,
    context: Mapping[str, Any],
    state: str = "targeted_reedit",
) -> dict[str, Any]:
    """Deterministic CI fixture only. Never used by the operator CLI."""
    context = r28.validate_candidate_context(context)
    c = context["candidate"]
    package_digest = "4" * 64
    sealed = "5" * 64
    capture_digest = "6" * 64
    critic_input = "7" * 64
    critic_output = "8" * 64
    binding = {
        "source_id": context["source"]["sourceId"],
        "source_sha256": context["source"]["sha256"],
        "source_size": context["source"]["size"],
        "media_repository": MEDIA_R21["repository"],
        "media_producer_sha": MEDIA_R21["producerSha"],
        "package_digest": package_digest,
        "sealed_mapping_digest": sealed,
        "review_round": c["roundIndex"],
        "candidate_id": c["candidateId"],
        "candidate_round": c["roundIndex"],
        "render_sha256": c["renderSha256"],
        "render_size": c["renderSize"],
        "render_export_sha256": c["renderExportSha256"],
        "attachment_sha256": c["renderSha256"],
        "attachment_size": c["renderSize"],
        "attachment_mime_type": "video/mp4",
        "critic_input_digest": critic_input,
        "critic_output_digest": critic_output,
        "capture_digest": capture_digest,
    }
    directives = []
    if state == "targeted_reedit":
        d = {
            "operation": "trim",
            "start_ms": 100,
            "end_ms": 300,
            "defect_category": "awkward_dead_moment",
            "severity": "major",
            "source_observation_id": "r29-test-observation",
            "evidence": "CI fixture evidence only",
            "confidence": 0.9,
            "uncertainty": "CI fixture only; not live model evidence",
            "upstream_proposed_edit": "remove bounded pause",
            "upstream_proposed_edit_executable": False,
            "binding": copy.deepcopy(binding),
        }
        d["directive_id"] = "gdr26d1:" + _sha(d)
        directives = [d]
    selected = c["candidateId"] if state == "winner" else "other-candidate"
    model_selection = "A" if selected else "tie"
    if state == "tie":
        selected, model_selection = None, "tie"
    if state == "insufficient_evidence":
        selected, model_selection = None, "insufficient_evidence"
    if state in {"human_review", "reedit_limit_reached"}:
        selected, model_selection = None, "insufficient_evidence"
    handoff = {
        "contract_version": GROWTH_R26["dynamicHandoffContract"],
        "handoff_id": "",
        "handoff_digest": "",
        "state": state,
        "review_round": c["roundIndex"],
        "max_reedit_rounds": 2,
        "binding": binding,
        "pairwise": {
            "model_facing_selection": model_selection,
            "selected_candidate_id": selected,
            "output_digest": "9" * 64,
        },
        "coverage": {
            "method": "ci_fixture",
            "inspected_ranges": [{"start_ms": 0, "end_ms": 5000}],
            "uninspected_possible": True,
            "every_frame_inspected": False,
            "notes": "CI fixture coverage only",
            "coverage_uncertainty_preserved": True,
        },
        "summary_uncertainty": "CI fixture only",
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
    handoff["handoff_id"] = "gdr26h1:" + _sha({
        "capture_digest": capture_digest,
        "package_digest": package_digest,
        "candidate_id": c["candidateId"],
        "critic_output_digest": critic_output,
        "pairwise_output_digest": handoff["pairwise"]["output_digest"],
        "review_round": c["roundIndex"],
    })
    material = copy.deepcopy(handoff)
    material["handoff_digest"] = ""
    handoff["handoff_digest"] = _sha(material)
    media_authority = {
        "contract_version": "growth.media_dynamic_review_authority.r26.v1",
        "repository": MEDIA_R21["repository"],
        "producer_sha": MEDIA_R21["producerSha"],
        "ci_run_id": MEDIA_R21["ciRunId"],
        "package_contract": "media.dynamic_review_package.r21.v1",
        "contract_blob_sha1": MEDIA_R21["reviewRoundContractBlobSha1"],
        "schema_blob_sha1": MEDIA_R21["reviewRoundSchemaBlobSha1"],
        "implementation_blob_sha1": MEDIA_R21["reviewRoundImplementationBlobSha1"],
        "artifact_id": MEDIA_R21["artifactId"],
        "artifact_name": MEDIA_R21["artifactName"],
        "artifact_digest": MEDIA_R21["artifactDigest"],
        "package_digest": package_digest,
        "package_file_sha256": "a" * 64,
        "evidence_file_sha256": "b" * 64,
        "prompt_digest": "c" * 64,
        "prompt_file_sha256": "d" * 64,
        "sealed_mapping_digest": sealed,
        "sealed_mapping_file_sha256": "e" * 64,
        "review_round": c["roundIndex"],
        "source": {
            "source_id": context["source"]["sourceId"],
            "sha256": context["source"]["sha256"],
            "size": context["source"]["size"],
        },
        "attachments": [
            {"blind_label":"A","generic_file_name":"review-A.mp4","sha256":c["renderSha256"],"size":c["renderSize"],"mime_type":"video/mp4"},
            {"blind_label":"B","generic_file_name":"review-B.mp4","sha256":"f"*64,"size":c["renderSize"]+1,"mime_type":"video/mp4"},
        ],
    }
    capture = {
        "capture_id": "r29-ci-fixture-capture",
        "capture_digest": capture_digest,
        "assistant_response_digest": "1" * 64,
        "conversation": {"conversation_id": "ci-fixture"},
        "response_shape": "ci_fixture",
        "normalization_generated_summary": False,
        "normalization_generated_pairwise_confidence": False,
    }
    envelope = {
        "contract_version": GROWTH_R26["creatorEnvelopeContract"],
        "envelope_id": "",
        "envelope_digest": "",
        "creator_event": {
            "contractVersion": "creator.dynamic_external_review_event.r26.v1",
            "producer": {
                "repository": GROWTH_R26["repository"],
                "sha": GROWTH_R26["producerSha"],
                "ciRunId": GROWTH_R26["ciRunId"],
                "contract": GROWTH_R26["dynamicHandoffContract"],
            },
            "captureMode": "external_live_review",
            "reviewIdentity": handoff["handoff_id"],
            "handoff": handoff,
        },
        "growth_r26": {
            "repository": GROWTH_R26["repository"],
            "producer_sha": GROWTH_R26["producerSha"],
            "ci_run_id": GROWTH_R26["ciRunId"],
            "starting_r25_sha": "2c441ebaa017c7da72461316401aeaf445e3d6e5",
            "ingest_contract": GROWTH_R26["captureContract"],
        },
        "media_authority": media_authority,
        "bridge_authority": _expected_bridge_authority(),
        "capture": capture,
        "review": {
            "package_digest": package_digest,
            "sealed_mapping_digest": sealed,
            "review_round": c["roundIndex"],
            "model_facing_selection": model_selection,
            "selected_candidate_id": selected,
        },
        "candidate": {
            "candidate_id": c["candidateId"],
            "candidate_round": c["roundIndex"],
            "source_id": context["source"]["sourceId"],
            "source_sha256": context["source"]["sha256"],
            "render_sha256": c["renderSha256"],
            "render_size": c["renderSize"],
            "attachment_sha256": c["renderSha256"],
            "attachment_size": c["renderSize"],
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
    envelope["envelope_id"] = "gdr26ce1:" + _sha({
        "growth_producer_sha": GROWTH_R26["producerSha"],
        "capture_digest": capture_digest,
        "package_digest": package_digest,
        "candidate_id": c["candidateId"],
        "handoff_digest": handoff["handoff_digest"],
        "review_round": c["roundIndex"],
    })
    material = copy.deepcopy(envelope)
    material["envelope_digest"] = ""
    envelope["envelope_digest"] = _sha(material)
    return validate_growth_r26_envelope(envelope)


def _load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="creator-live-e2e-r29")
    sub = p.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("readiness")
    ready.add_argument("--out")
    run = sub.add_parser("consume")
    run.add_argument("--media-checkout", required=True)
    run.add_argument("--growth-checkout", required=True)
    run.add_argument("--bridge-checkout", required=True)
    run.add_argument("--candidate-root", required=True)
    run.add_argument("--candidate-context", required=True)
    run.add_argument("--growth-output", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--release-authorization")
    run.add_argument("--publish-target")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        report = readiness_report()
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, sort_keys=True))
        return 2
    try:
        report = run_consumer(
            media_checkout=Path(args.media_checkout),
            growth_checkout=Path(args.growth_checkout),
            bridge_checkout=Path(args.bridge_checkout),
            candidate_root=Path(args.candidate_root),
            candidate_context_path=Path(args.candidate_context),
            growth_output_path=Path(args.growth_output),
            out_dir=Path(args.out),
            release_authorization_path=(
                None if not args.release_authorization else Path(args.release_authorization)
            ),
            publish_target=(
                None if not args.publish_target else _load(args.publish_target)
            ),
        )
    except Exception as exc:
        blocked = {
            "contractVersion": REPORT_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": False,
            "REAL_REEDIT_EXECUTED": False,
            "NEXT_REVIEW_PACKAGE_READY": False,
            "PUBLISH_HANDOFF_READY": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanQualityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
