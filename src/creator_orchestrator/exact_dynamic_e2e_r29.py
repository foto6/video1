from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import dynamic_live_review_loop as r28
from . import editor_publish_handoff as r23
from . import publish_execution as r21

CONTRACT_VERSION = "creator.exact_dynamic_e2e.r29.v1"
LEDGER_VERSION = "creator.exact_dynamic_e2e_ledger.r29.v1"
REPORT_VERSION = "creator.exact_dynamic_e2e.r29.readiness.v1"
ADAPTER_VERSION = "creator.growth_r26_media_r19_adapter.r29.v1"
PACKAGE_RESULT_VERSION = "creator.media_r21_round_package_result.r29.v1"
CREATOR_BASE_SHA = "0d670abd4b5f04391fd1e6e1af4836a9fc92c8f3"
MAX_REEDIT_ROUNDS = 2

MEDIA_R21_AUTHORITY = {
    "repository": "foto6/video2",
    "producerSha": "d753e9e4c1f4448386608a1425232dbc1dba87ea",
    "ciRunId": 36994000619,
    "artifactId": 11221240371,
    "artifactName": "media-r21-round-pair-review",
    "artifactDigest": "sha256:1036800923196882590ace62edbaa123ab4250b9d242e14adba909ba256ab022",
    "reviewBundleContract": "media.review_round_bundle.r21.v1",
    "reviewBundleContractBlobSha1": "65358261775f0fcd2ab9e21f3f621aee977f29da",
    "reviewBundleSchemaBlobSha1": "f04925e317d849434852e6b706533f909da47b22",
    "reviewBundleManifestBlobSha1": "f76033375e7ee03b56491722e2e99e7334bd2cad",
    "reviewBundleImplementationBlobSha1": "c6f556b8a177b6182d787356625094cdcad5a58e",
    "reviewBundleRunnerBlobSha1": "c93e9a69de31b66189031932ccfa7f2c83cf043c",
    "applicationContract": "media.editorial_reedit_application.v1",
    "applicationContractBlobSha1": "6b3350c5f1524fe49a49d5637514e2fb1a808bcf",
    "applicationSchemaBlobSha1": "7cabf91f08ae11b68cc4a7eec88d358a46730289",
    "applicationManifestBlobSha1": "502c32253d370e9b4e3d53f4a70de317f89dd21b",
    "r19ImplementationBlobSha1": "8110a086b5b319bd2601860845c6afbf97681921",
    "r19RunnerBlobSha1": "7dbec612621aa42baaf2946cdac61d070e3ff41f",
    "renderExportManifestBlobSha1": "945acb01ff0269d89b91463aa8d862f500e055b2",
    "renderExportSchemaBlobSha1": "6353d32d785a2a1f1441bac4cfd0271b46b41d4a",
    "r20ContractBlobSha1": "bf650ad1552686d830965edad3fd62451ec0ec22",
    "r20SchemaBlobSha1": "680aa69dfb595f31e93fb2bdfe0fdae2ac5ca25b",
    "r20ManifestBlobSha1": "da4af21cae8dffacb9cc303576fb08cb671e02ce",
    "r20ImplementationBlobSha1": "cebaa1083d121844b5f7d5a78196d201f860d8a8",
    "r20RunnerBlobSha1": "33c742f1e0314e462fb3e97337bf82883ec80f00",
}

GROWTH_R26_AUTHORITY = {
    "repository": "foto6/video3",
    "producerSha": "e844ed2daaaca9e9694fe1e0fb6b8b7bfac69cbc",
    "ciRunId": 36996617627,
    "captureContract": "growth.dynamic_live_review_capture.r26.v1",
    "creatorEnvelopeContract": "growth.dynamic_creator_external_review_envelope.r26.v1",
    "dynamicHandoffContract": "growth.dynamic_creator_reedit_handoff.r26.v1",
    "contractBlobSha1": "700c942c4e9375eab5748f873d15f29f4b3f3826",
    "schemaBlobSha1": "de5f2d600cfece9829cf2b26ce1827516c7038c3",
    "implementationBlobSha1": "71fc2e372401ebf65d603681101eb1d7d0c520d7",
    "legacyHandoffContractBlobSha1": "ced853aad722aad4c7a88e9a41756baa1b2892a6",
    "legacyHandoffSchemaBlobSha1": "ba9ada04488760147136dcaaf012206405c04653",
    "directiveAdapterBlobSha1": "c358d31866cdea842202fef6add992d102a58f90",
    "startingR25Sha": "2c441ebaa017c7da72461316401aeaf445e3d6e5",
}

BRIDGE_R30_AUTHORITY = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "ceaee873231a8552c5b7324083baa800eec566a8",
    "ciRunId": 36993885456,
    "captureContract": "bridge.dynamic_existing_chat_video_review_capture.v1",
    "captureSchemaId": "bridge://bridge.dynamic_existing_chat_video_review_capture.v1",
    "handoffContract": "media.dynamic_review_handoff.v1",
    "handoffSchemaBlobSha1": "93968dc1fb65a334493acdb587b20753f0a8494a",
    "captureSchemaBlobSha1": "2cbe22ad6c7fe877764bad8dcfc1496aef3f3737",
    "resultSchemaBlobSha1": "4a6620a28609c7b5c4a4a538a875b206ce6a9dce",
    "implementationBlobSha1": "c5bd2f95a6d58a86cddd9a6fdc127e68e3346c20",
    "verifierBlobSha1": "343ee5cb41a443932a0a944eac2957dd36836dec",
}

# Exact Media R19 compatibility constants are required by the exact R21 checkout's
# frozen R19 validator. They are execution-schema compatibility only and are
# never accepted as live-review provenance.
_MEDIA_R19_COMPAT_BRIDGE_R26 = {
    "repository": "foto6/WebAIBridge",
    "branch": "agent/bridge-r26-file-attachment-rehearsal-20261002",
    "source_sha": "73c13f9eed2a2cbcea881dd8c5452d054bfef940",
    "attachment_contract": "bridge.chat_file_attachment.v1",
    "rehearsal_request_contract": "bridge.chat_file_attachment_rehearsal_request.v1",
    "rehearsal_result_contract": "bridge.chat_file_attachment_rehearsal_result.v1",
    "dom_probe_contract": "bridge.chat_file_attachment_dom_probe.v1",
    "operator_evidence_contract": "bridge.chat_file_attachment_operator_evidence.v1",
    "max_file_bytes": 500000000,
    "disposition": "READY_FOR_EXPLICIT_LIVE_REHEARSAL",
    "live_pass": False,
    "real_upload_proven": False,
    "real_prompt_send_proven": False,
    "no_live_deploy": True,
    "no_cutover": True,
}
_MEDIA_R19_COMPAT_MEDIA_R18 = {
    "repository": "foto6/video2",
    "branch": "agent/media-r18-direct-model-review-package-20261002",
    "source_sha": "2c41f084e000eca5efd9a51d2d3752bec1bd1311",
    "ci_run_id": 36967381891,
    "contract": "media.direct_model_review_package.v1",
    "max_file_bytes": 500000000,
    "live_upload_performed": False,
    "model_judgment_performed": False,
}

ALLOWED_STATES = {
    "targeted_reedit",
    "winner",
    "tie",
    "insufficient_evidence",
    "human_review",
    "reedit_limit_reached",
}
ALLOWED_OPERATIONS = {
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


class R29Error(ValueError):
    pass


class AuthorityDrift(R29Error):
    pass


class LineageDrift(R29Error):
    pass


class ReplayConflict(R29Error):
    pass


class RoundLimit(R29Error):
    pass


class PackageDrift(R29Error):
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


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R29Error(f"{field} must be non-empty")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R29Error(f"{field} must be positive integer")
    return value


def _profile_digest(value: Mapping[str, Any]) -> str:
    return _sha(value)


def _verify_exact_profile(
    supplied: Mapping[str, Any],
    expected: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if not isinstance(supplied, Mapping) or supplied != expected:
        raise AuthorityDrift(f"{label} authority profile drift")
    return _clone(supplied)


def validate_media_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    return _verify_exact_profile(value, MEDIA_R21_AUTHORITY, "Media R21")


def validate_growth_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    return _verify_exact_profile(value, GROWTH_R26_AUTHORITY, "Growth R26")


def validate_bridge_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    return _verify_exact_profile(value, BRIDGE_R30_AUTHORITY, "Bridge R30")


def _verify_checkout(
    root: Path,
    *,
    expected_sha: str,
    checks: Mapping[str, str],
    expected: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    root = Path(root).resolve()
    if r28._git_head(root) != expected_sha:
        raise AuthorityDrift(f"{label} checkout producer SHA drift")
    observed: dict[str, str] = {}
    for field, rel in checks.items():
        path = root / rel
        if not path.is_file():
            raise AuthorityDrift(f"{label} authority file missing: {rel}")
        observed[field] = r28._git_blob_sha(path)
        if observed[field] != expected[field]:
            raise AuthorityDrift(f"{label} authority blob drift: {field}")
    return {
        "checkoutSha": expected_sha,
        "observedBlobs": observed,
    }


def verify_media_checkout(root: Path) -> dict[str, Any]:
    validate_media_authority(MEDIA_R21_AUTHORITY)
    checks = {
        "reviewBundleContractBlobSha1": "conformance/media.review_round_bundle.r21.v1/contract.json",
        "reviewBundleSchemaBlobSha1": "conformance/media.review_round_bundle.r21.v1/schema.json",
        "reviewBundleManifestBlobSha1": "conformance/media.review_round_bundle.r21.v1/manifest.json",
        "reviewBundleImplementationBlobSha1": "src/review-round-r21.js",
        "reviewBundleRunnerBlobSha1": "tools/build-r21-review-round.mjs",
        "applicationContractBlobSha1": "conformance/media.editorial_reedit_application.v1/contract.json",
        "applicationSchemaBlobSha1": "conformance/media.editorial_reedit_application.v1/schema.json",
        "applicationManifestBlobSha1": "conformance/media.editorial_reedit_application.v1/manifest.json",
        "r19ImplementationBlobSha1": "src/editorial-reedit-r19.js",
        "r19RunnerBlobSha1": "tools/run-r19-editorial-reedit.mjs",
        "renderExportManifestBlobSha1": "conformance/media.render_export.v1/manifest.json",
        "renderExportSchemaBlobSha1": "conformance/media.render_export.v1/schema.json",
        "r20ContractBlobSha1": "conformance/media.dynamic_review_package.r20.v1/contract.json",
        "r20SchemaBlobSha1": "conformance/media.dynamic_review_package.r20.v1/schema.json",
        "r20ManifestBlobSha1": "conformance/media.dynamic_review_package.r20.v1/manifest.json",
        "r20ImplementationBlobSha1": "src/dynamic-review-r20.js",
        "r20RunnerBlobSha1": "tools/build-r20-dynamic-review.mjs",
    }
    result = _verify_checkout(
        root,
        expected_sha=MEDIA_R21_AUTHORITY["producerSha"],
        checks=checks,
        expected=MEDIA_R21_AUTHORITY,
        label="Media R21",
    )
    result["profileDigest"] = _profile_digest(MEDIA_R21_AUTHORITY)
    return result


def verify_growth_checkout(root: Path) -> dict[str, Any]:
    checks = {
        "contractBlobSha1": "conformance/growth.dynamic_live_review_capture.r26.v1/contract.json",
        "schemaBlobSha1": "conformance/growth.dynamic_live_review_capture.r26.v1/schema.json",
        "implementationBlobSha1": "growth_analytics/dynamic_review_capture_r26.py",
        "legacyHandoffContractBlobSha1": "conformance/growth.creator_reedit_handoff.v1/contract.json",
        "legacyHandoffSchemaBlobSha1": "conformance/growth.creator_reedit_handoff.v1/schema.json",
        "directiveAdapterBlobSha1": "growth_analytics/critic_reedit_adapter.py",
    }
    result = _verify_checkout(
        root,
        expected_sha=GROWTH_R26_AUTHORITY["producerSha"],
        checks=checks,
        expected=GROWTH_R26_AUTHORITY,
        label="Growth R26",
    )
    result["profileDigest"] = _profile_digest(GROWTH_R26_AUTHORITY)
    return result


def verify_bridge_checkout(root: Path) -> dict[str, Any]:
    checks = {
        "handoffSchemaBlobSha1": "app/contracts/r30/media.dynamic_review_handoff.v1.schema.json",
        "captureSchemaBlobSha1": "app/contracts/r30/bridge.dynamic_existing_chat_video_review_capture.v1.schema.json",
        "resultSchemaBlobSha1": "app/contracts/r30/bridge.r30_dynamic_review_transport_result.v1.schema.json",
        "implementationBlobSha1": "app/r30-dynamic-review.js",
        "verifierBlobSha1": "app/r30-verify-dynamic-handoff.js",
    }
    result = _verify_checkout(
        root,
        expected_sha=BRIDGE_R30_AUTHORITY["producerSha"],
        checks=checks,
        expected=BRIDGE_R30_AUTHORITY,
        label="Bridge R30",
    )
    result["profileDigest"] = _profile_digest(BRIDGE_R30_AUTHORITY)
    return result


def _validate_media_envelope_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "repository", "producer_sha", "ci_run_id",
        "package_contract", "contract_blob_sha1", "schema_blob_sha1",
        "implementation_blob_sha1", "artifact_id", "artifact_name",
        "artifact_digest", "package_digest", "package_file_sha256",
        "evidence_file_sha256", "prompt_digest", "prompt_file_sha256",
        "sealed_mapping_digest", "sealed_mapping_file_sha256", "review_round",
        "source", "attachments",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LineageDrift("Media R21 envelope authority fields mismatch")
    exact = {
        "contract_version": "growth.media_dynamic_review_authority.r26.v1",
        "repository": MEDIA_R21_AUTHORITY["repository"],
        "producer_sha": MEDIA_R21_AUTHORITY["producerSha"],
        "ci_run_id": MEDIA_R21_AUTHORITY["ciRunId"],
        "package_contract": "media.dynamic_review_package.r21.v1",
        "contract_blob_sha1": MEDIA_R21_AUTHORITY["reviewBundleContractBlobSha1"],
        "schema_blob_sha1": MEDIA_R21_AUTHORITY["reviewBundleSchemaBlobSha1"],
        "implementation_blob_sha1": MEDIA_R21_AUTHORITY["reviewBundleImplementationBlobSha1"],
        "artifact_id": MEDIA_R21_AUTHORITY["artifactId"],
        "artifact_name": MEDIA_R21_AUTHORITY["artifactName"],
        "artifact_digest": MEDIA_R21_AUTHORITY["artifactDigest"],
    }
    for key, expected in exact.items():
        if value[key] != expected:
            raise AuthorityDrift(f"Media R21 envelope authority drift: {key}")
    for key in (
        "package_digest", "package_file_sha256", "evidence_file_sha256",
        "prompt_digest", "prompt_file_sha256", "sealed_mapping_digest",
        "sealed_mapping_file_sha256",
    ):
        _hex(value[key], 64, f"media_authority.{key}")
    round_index = value["review_round"]
    if isinstance(round_index, bool) or not isinstance(round_index, int) or not 0 <= round_index <= 2:
        raise LineageDrift("Media authority review_round invalid")
    source = value["source"]
    if not isinstance(source, Mapping) or set(source) != {"source_id", "sha256", "size"}:
        raise LineageDrift("Media authority source fields mismatch")
    _nonempty(source["source_id"], "media.source_id")
    _hex(source["sha256"], 64, "media.source_sha256")
    _positive(source["size"], "media.source_size")
    attachments = value["attachments"]
    if not isinstance(attachments, list) or len(attachments) != 2:
        raise LineageDrift("Media authority requires exact A/B attachments")
    seen = set()
    for row in attachments:
        if not isinstance(row, Mapping) or set(row) != {
            "blind_label", "generic_file_name", "sha256", "size", "mime_type"
        }:
            raise LineageDrift("Media attachment authority fields mismatch")
        if row["blind_label"] not in {"A", "B"} or row["blind_label"] in seen:
            raise LineageDrift("Media attachment blind labels invalid")
        seen.add(row["blind_label"])
        _hex(row["sha256"], 64, "media.attachment.sha256")
        _positive(row["size"], "media.attachment.size")
        if row["mime_type"] != "video/mp4":
            raise LineageDrift("Media attachment MIME mismatch")
    return _clone(value)


def _validate_bridge_envelope_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "contract_version": "growth.bridge_dynamic_capture_authority.r26.v1",
        "repository": BRIDGE_R30_AUTHORITY["repository"],
        "producer_sha": BRIDGE_R30_AUTHORITY["producerSha"],
        "ci_run_id": BRIDGE_R30_AUTHORITY["ciRunId"],
        "capture_contract": BRIDGE_R30_AUTHORITY["captureContract"],
        "capture_schema_id": BRIDGE_R30_AUTHORITY["captureSchemaId"],
        "contract_blob_sha1": BRIDGE_R30_AUTHORITY["handoffSchemaBlobSha1"],
        "schema_blob_sha1": BRIDGE_R30_AUTHORITY["captureSchemaBlobSha1"],
        "implementation_blob_sha1": BRIDGE_R30_AUTHORITY["implementationBlobSha1"],
    }
    if value != expected:
        raise AuthorityDrift("Bridge R30 envelope authority drift")
    return _clone(value)


def _validate_dynamic_handoff(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "handoff_id", "handoff_digest", "state",
        "review_round", "max_reedit_rounds", "binding", "pairwise",
        "coverage", "summary_uncertainty", "directives",
        "evidence_boundary", "authority",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LineageDrift("Growth R26 dynamic handoff fields mismatch")
    if value["contract_version"] != GROWTH_R26_AUTHORITY["dynamicHandoffContract"]:
        raise AuthorityDrift("Growth R26 dynamic handoff contract drift")
    state = value["state"]
    if state not in ALLOWED_STATES:
        raise LineageDrift("Growth R26 handoff state unsupported")
    review_round = value["review_round"]
    if isinstance(review_round, bool) or not isinstance(review_round, int) or not 0 <= review_round <= 2:
        raise LineageDrift("Growth R26 handoff review_round invalid")
    if value["max_reedit_rounds"] != MAX_REEDIT_ROUNDS:
        raise LineageDrift("Growth R26 max re-edit rounds drift")
    binding = value["binding"]
    required_binding = {
        "source_id", "source_sha256", "source_size", "media_repository",
        "media_producer_sha", "package_digest", "sealed_mapping_digest",
        "review_round", "candidate_id", "candidate_round", "render_sha256",
        "render_size", "render_export_sha256", "attachment_sha256",
        "attachment_size", "attachment_mime_type", "critic_input_digest",
        "critic_output_digest", "capture_digest",
    }
    if not isinstance(binding, Mapping) or set(binding) != required_binding:
        raise LineageDrift("Growth R26 binding fields mismatch")
    if binding["media_repository"] != MEDIA_R21_AUTHORITY["repository"]:
        raise AuthorityDrift("Growth R26 Media repository drift")
    if binding["media_producer_sha"] != MEDIA_R21_AUTHORITY["producerSha"]:
        raise AuthorityDrift("Growth R26 Media producer drift")
    for key in (
        "source_sha256", "package_digest", "sealed_mapping_digest",
        "render_sha256", "render_export_sha256", "attachment_sha256",
        "critic_input_digest", "critic_output_digest", "capture_digest",
    ):
        _hex(binding[key], 64, f"handoff.binding.{key}")
    for key in ("source_size", "render_size", "attachment_size"):
        _positive(binding[key], f"handoff.binding.{key}")
    if binding["attachment_mime_type"] != "video/mp4":
        raise LineageDrift("review attachment MIME is not video/mp4")
    if binding["review_round"] != review_round or binding["candidate_round"] != review_round:
        raise LineageDrift("Growth R26 round binding drift")
    if (
        binding["render_sha256"] != binding["attachment_sha256"]
        or binding["render_size"] != binding["attachment_size"]
    ):
        raise LineageDrift("Growth R26 reviewed render/attachment identity mismatch")

    pairwise = value["pairwise"]
    if not isinstance(pairwise, Mapping) or set(pairwise) != {
        "model_facing_selection", "selected_candidate_id", "output_digest"
    }:
        raise LineageDrift("Growth R26 pairwise fields mismatch")
    if pairwise["model_facing_selection"] not in {"A", "B", "tie", "insufficient_evidence"}:
        raise LineageDrift("Growth R26 pairwise selection invalid")
    _hex(pairwise["output_digest"], 64, "handoff.pairwise.output_digest")
    if pairwise["selected_candidate_id"] is not None:
        _nonempty(pairwise["selected_candidate_id"], "handoff.pairwise.selected_candidate_id")

    directives = value["directives"]
    if not isinstance(directives, list):
        raise LineageDrift("Growth R26 directives must be list")
    if state == "targeted_reedit" and not directives:
        raise LineageDrift("targeted_reedit requires directives")
    if state != "targeted_reedit" and directives:
        raise LineageDrift("non-targeted handoff must not execute directives")
    seen = set()
    for directive in directives:
        required_directive = {
            "operation", "start_ms", "end_ms", "defect_category", "severity",
            "source_observation_id", "evidence", "confidence", "uncertainty",
            "upstream_proposed_edit", "upstream_proposed_edit_executable",
            "binding", "directive_id",
        }
        if not isinstance(directive, Mapping) or set(directive) != required_directive:
            raise LineageDrift("Growth R26 directive fields mismatch")
        if directive["operation"] not in ALLOWED_OPERATIONS:
            raise LineageDrift("unsupported Growth R26 directive")
        if directive["binding"] != binding:
            raise LineageDrift("directive binding differs from handoff")
        if directive["upstream_proposed_edit_executable"] is not False:
            raise LineageDrift("free-form model edit cannot be executable")
        if (
            isinstance(directive["start_ms"], bool)
            or isinstance(directive["end_ms"], bool)
            or not isinstance(directive["start_ms"], int)
            or not isinstance(directive["end_ms"], int)
            or directive["start_ms"] < 0
            or directive["end_ms"] <= directive["start_ms"]
        ):
            raise LineageDrift("directive interval invalid")
        body = dict(directive)
        directive_id = body.pop("directive_id")
        expected_id = "gdr26d1:" + _sha(body)
        if directive_id != expected_id or directive_id in seen:
            raise LineageDrift("directive identity/digest mismatch")
        seen.add(directive_id)

    if value["evidence_boundary"] != {
        "model_review_only": True,
        "human_ground_truth": False,
        "human_label": False,
        "human_rating_evidence": False,
        "live_platform_evidence": False,
        "free_form_proposed_edit_executable": False,
    }:
        raise LineageDrift("Growth R26 evidence boundary drift")
    if value["authority"] != {
        "advisory_only": True,
        "creator_mutation": False,
        "media_mutation": False,
        "provider_mutation": False,
        "publish_authorized": False,
        "release_authorized": False,
    }:
        raise LineageDrift("Growth R26 authority boundary drift")

    expected_id = "gdr26h1:" + _sha({
        "capture_digest": binding["capture_digest"],
        "package_digest": binding["package_digest"],
        "candidate_id": binding["candidate_id"],
        "critic_output_digest": binding["critic_output_digest"],
        "pairwise_output_digest": pairwise["output_digest"],
        "review_round": review_round,
    })
    if value["handoff_id"] != expected_id:
        raise LineageDrift("Growth R26 handoff ID mismatch")
    material = dict(value)
    material["handoff_digest"] = ""
    if value["handoff_digest"] != _sha(material):
        raise LineageDrift("Growth R26 handoff digest mismatch")
    return _clone(value)


def validate_growth_r26_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "envelope_id", "envelope_digest", "creator_event",
        "growth_r26", "media_authority", "bridge_authority", "capture",
        "review", "candidate", "evidence_boundary",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LineageDrift("Growth R26 Creator envelope fields mismatch")
    if value["contract_version"] != GROWTH_R26_AUTHORITY["creatorEnvelopeContract"]:
        raise AuthorityDrift("Growth R26 Creator envelope contract drift")
    growth = value["growth_r26"]
    expected_growth = {
        "repository": GROWTH_R26_AUTHORITY["repository"],
        "producer_sha": GROWTH_R26_AUTHORITY["producerSha"],
        "ci_run_id": GROWTH_R26_AUTHORITY["ciRunId"],
        "starting_r25_sha": GROWTH_R26_AUTHORITY["startingR25Sha"],
        "ingest_contract": GROWTH_R26_AUTHORITY["captureContract"],
    }
    if growth != expected_growth:
        raise AuthorityDrift("Growth R26 producer authority drift")
    media = _validate_media_envelope_authority(value["media_authority"])
    bridge = _validate_bridge_envelope_authority(value["bridge_authority"])

    event = value["creator_event"]
    if not isinstance(event, Mapping) or set(event) != {
        "contractVersion", "producer", "captureMode", "reviewIdentity", "handoff"
    }:
        raise LineageDrift("Creator dynamic review event fields mismatch")
    expected_event_producer = {
        "repository": GROWTH_R26_AUTHORITY["repository"],
        "sha": GROWTH_R26_AUTHORITY["producerSha"],
        "ciRunId": GROWTH_R26_AUTHORITY["ciRunId"],
        "contract": GROWTH_R26_AUTHORITY["dynamicHandoffContract"],
    }
    if (
        event["contractVersion"] != "creator.dynamic_external_review_event.r26.v1"
        or event["producer"] != expected_event_producer
        or event["captureMode"] != "external_live_review"
    ):
        raise AuthorityDrift("Creator dynamic event authority drift")
    handoff = _validate_dynamic_handoff(event["handoff"])
    if event["reviewIdentity"] != handoff["handoff_id"]:
        raise LineageDrift("review identity/handoff mismatch")

    capture = value["capture"]
    if not isinstance(capture, Mapping) or set(capture) != {
        "capture_id", "capture_digest", "assistant_response_digest",
        "conversation", "response_shape", "normalization_generated_summary",
        "normalization_generated_pairwise_confidence",
    }:
        raise LineageDrift("Growth R26 capture fields mismatch")
    _nonempty(capture["capture_id"], "capture.capture_id")
    _hex(capture["capture_digest"], 64, "capture.capture_digest")
    _hex(capture["assistant_response_digest"], 64, "capture.assistant_response_digest")
    if not isinstance(capture["conversation"], Mapping):
        raise LineageDrift("capture.conversation missing")
    if handoff["binding"]["capture_digest"] != capture["capture_digest"]:
        raise LineageDrift("handoff capture digest mismatch")

    review = value["review"]
    if not isinstance(review, Mapping) or set(review) != {
        "package_digest", "sealed_mapping_digest", "review_round",
        "model_facing_selection", "selected_candidate_id",
    }:
        raise LineageDrift("Growth R26 review fields mismatch")
    for key in ("package_digest", "sealed_mapping_digest"):
        _hex(review[key], 64, f"review.{key}")
    if review["package_digest"] != media["package_digest"]:
        raise PackageDrift("review/package digest mismatch")
    if review["sealed_mapping_digest"] != media["sealed_mapping_digest"]:
        raise PackageDrift("review/sealed mapping digest mismatch")
    if review["review_round"] != media["review_round"]:
        raise LineageDrift("review round/media authority mismatch")
    if review["model_facing_selection"] != handoff["pairwise"]["model_facing_selection"]:
        raise LineageDrift("pairwise selection drift")
    if review["selected_candidate_id"] != handoff["pairwise"]["selected_candidate_id"]:
        raise LineageDrift("selected candidate identity drift")

    binding = handoff["binding"]
    for key, expected in (
        ("package_digest", review["package_digest"]),
        ("sealed_mapping_digest", review["sealed_mapping_digest"]),
        ("review_round", review["review_round"]),
    ):
        if binding[key] != expected:
            raise LineageDrift(f"handoff binding drift: {key}")

    candidate = value["candidate"]
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidate_id", "candidate_round", "source_id", "source_sha256",
        "render_sha256", "render_size", "attachment_sha256", "attachment_size",
        "attachment_mime_type", "handoff_digest", "state",
    }:
        raise LineageDrift("Growth R26 candidate summary fields mismatch")
    expected_candidate = {
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
    if candidate != expected_candidate:
        raise LineageDrift("Growth R26 candidate/handoff summary drift")
    if candidate["candidate_round"] != review["review_round"]:
        raise LineageDrift("candidate round/review round mismatch")
    if (
        candidate["source_id"] != media["source"]["source_id"]
        or candidate["source_sha256"] != media["source"]["sha256"]
    ):
        raise LineageDrift("candidate source/media package mismatch")
    matches = [
        row for row in media["attachments"]
        if row["sha256"] == candidate["attachment_sha256"]
        and row["size"] == candidate["attachment_size"]
    ]
    if len(matches) != 1:
        raise LineageDrift("reviewed attachment is not uniquely bound to Media package")
    if candidate["state"] == "winner":
        if review["selected_candidate_id"] != candidate["candidate_id"]:
            raise LineageDrift("winner is not selected candidate")
    elif candidate["state"] in {"tie", "insufficient_evidence"}:
        if review["selected_candidate_id"] is not None:
            raise LineageDrift("nonselection state must not have selected candidate")
    elif candidate["state"] == "targeted_reedit":
        if review["review_round"] >= MAX_REEDIT_ROUNDS:
            raise RoundLimit("targeted re-edit would exceed max two rounds")
        if review["selected_candidate_id"] == candidate["candidate_id"]:
            raise LineageDrift("selected winner cannot also be targeted_reedit")

    if value["evidence_boundary"] != {
        "model_evidence": True,
        "human_ground_truth": False,
        "human_rating_evidence": False,
        "human_parity_inferred": False,
        "provider_mutation": False,
    }:
        raise LineageDrift("Growth R26 envelope evidence boundary drift")
    expected_id = "gdr26ce1:" + _sha({
        "growth_producer_sha": GROWTH_R26_AUTHORITY["producerSha"],
        "capture_digest": capture["capture_digest"],
        "package_digest": review["package_digest"],
        "candidate_id": candidate["candidate_id"],
        "handoff_digest": candidate["handoff_digest"],
        "review_round": review["review_round"],
    })
    if value["envelope_id"] != expected_id:
        raise LineageDrift("Growth R26 envelope ID mismatch")
    material = dict(value)
    material["envelope_digest"] = ""
    if value["envelope_digest"] != _sha(material):
        raise LineageDrift("Growth R26 envelope digest mismatch")
    return _clone(value)


def validate_review_against_context(
    envelope: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    candidate_root: Path,
) -> dict[str, Any]:
    envelope = validate_growth_r26_envelope(envelope)
    context = r28.validate_candidate_context(context)
    candidate = context["candidate"]
    summary = envelope["candidate"]
    binding = envelope["creator_event"]["handoff"]["binding"]
    if (
        context["source"]["sourceId"] != summary["source_id"]
        or context["source"]["sha256"] != summary["source_sha256"]
        or context["source"]["size"] != binding["source_size"]
    ):
        raise LineageDrift("Growth R26 review source differs from Creator context")
    for left, right, field in (
        (candidate["candidateId"], summary["candidate_id"], "candidateId"),
        (candidate["roundIndex"], summary["candidate_round"], "roundIndex"),
        (candidate["renderSha256"], summary["render_sha256"], "renderSha256"),
        (candidate["renderSize"], summary["render_size"], "renderSize"),
        (candidate["renderExportSha256"], binding["render_export_sha256"], "renderExportSha256"),
    ):
        if left != right:
            raise LineageDrift(f"Creator candidate drift: {field}")
    root = Path(candidate_root).resolve()
    final_path = (root / candidate["finalPath"]).resolve()
    export_path = (root / candidate["renderExportPath"]).resolve()
    for path in (final_path, export_path):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise LineageDrift("Creator candidate path escapes root") from exc
    if not final_path.is_file() or not export_path.is_file():
        raise LineageDrift("Creator candidate bytes/sidecar missing")
    if r28._file_sha(final_path) != candidate["renderSha256"]:
        raise LineageDrift("Creator candidate render hash mismatch")
    if r28._file_size(final_path) != candidate["renderSize"]:
        raise LineageDrift("Creator candidate render size mismatch")
    if r28._file_sha(export_path) != candidate["renderExportSha256"]:
        raise LineageDrift("Creator render-export file hash mismatch")
    return envelope


def _r19_runtime_profile() -> dict[str, Any]:
    return {
        "authorityVersion": r28.AUTHORITY_VERSION,
        "family": "media_r19_r20_editorial_dynamic_review",
        "repository": MEDIA_R21_AUTHORITY["repository"],
        "producerSha": MEDIA_R21_AUTHORITY["producerSha"],
        "ciRunId": MEDIA_R21_AUTHORITY["ciRunId"],
        "applicationContract": MEDIA_R21_AUTHORITY["applicationContract"],
        "applicationContractBlobSha1": MEDIA_R21_AUTHORITY["applicationContractBlobSha1"],
        "applicationManifestBlobSha1": MEDIA_R21_AUTHORITY["applicationManifestBlobSha1"],
        "applicationSchemaBlobSha1": MEDIA_R21_AUTHORITY["applicationSchemaBlobSha1"],
        "r19ImplementationBlobSha1": MEDIA_R21_AUTHORITY["r19ImplementationBlobSha1"],
        "r19RunnerBlobSha1": MEDIA_R21_AUTHORITY["r19RunnerBlobSha1"],
        "renderExportContract": "media.render_export.v1",
        "renderExportManifestBlobSha1": MEDIA_R21_AUTHORITY["renderExportManifestBlobSha1"],
        "renderExportSchemaBlobSha1": MEDIA_R21_AUTHORITY["renderExportSchemaBlobSha1"],
        "dynamicPackageContract": "media.dynamic_review_package.r20.v1",
        "dynamicRequestContract": "media.dynamic_review_request.r20.v1",
        "dynamicBridgeHandoffContract": "media.bridge_live_review_handoff.r20.v1",
        "dynamicContractBlobSha1": MEDIA_R21_AUTHORITY["r20ContractBlobSha1"],
        "dynamicManifestBlobSha1": MEDIA_R21_AUTHORITY["r20ManifestBlobSha1"],
        "dynamicSchemaBlobSha1": MEDIA_R21_AUTHORITY["r20SchemaBlobSha1"],
        "dynamicImplementationBlobSha1": MEDIA_R21_AUTHORITY["r20ImplementationBlobSha1"],
        "dynamicRunnerBlobSha1": MEDIA_R21_AUTHORITY["r20RunnerBlobSha1"],
        "testFixture": False,
    }


def adapt_growth_r26_for_media_r19(
    envelope: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = validate_growth_r26_envelope(envelope)
    context = r28.validate_candidate_context(context)
    handoff = envelope["creator_event"]["handoff"]
    if handoff["state"] != "targeted_reedit":
        raise R29Error("Media adaptation requires targeted_reedit")
    binding = handoff["binding"]
    candidate = context["candidate"]
    compat_binding = {
        "source_id": binding["source_id"],
        "source_sha256": binding["source_sha256"],
        "source_size": binding["source_size"],
        "media_repository": MEDIA_R21_AUTHORITY["repository"],
        "media_producer_sha": candidate["renderProducerSha"],
        "candidate_id": binding["candidate_id"],
        "render_sha256": binding["render_sha256"],
        "render_size": binding["render_size"],
        "render_export_sha256": binding["render_export_sha256"],
        "attachment_sha256": binding["attachment_sha256"],
        "attachment_size": binding["attachment_size"],
        "attachment_identity": (
            "r29:" + envelope["review"]["package_digest"][:16] + ":"
            + binding["attachment_sha256"][:16]
        ),
        "review_bundle_digest": envelope["review"]["package_digest"],
        "critic_input_digest": binding["critic_input_digest"],
        "critic_output_digest": binding["critic_output_digest"],
    }
    directives = []
    for source in handoff["directives"]:
        body = {
            "operation": source["operation"],
            "start_ms": source["start_ms"],
            "end_ms": source["end_ms"],
            "defect_category": source["defect_category"],
            "severity": source["severity"],
            "source_observation_id": source["source_observation_id"],
            "evidence": source["evidence"],
            "confidence": source["confidence"],
            "uncertainty": source["uncertainty"],
            "upstream_proposed_edit": source["upstream_proposed_edit"],
            "upstream_proposed_edit_executable": False,
            "binding": _clone(compat_binding),
        }
        body["directive_id"] = "gcrd1:" + _sha(body)
        directives.append(body)
    compat = {
        "contract_version": "growth.creator_reedit_handoff.v1",
        "adapter_version": "growth.web_video_critic_reedit_adapter.v1",
        "handoff_id": "",
        "handoff_digest": "",
        "state": "targeted_reedit",
        "reedit_round": handoff["review_round"],
        "max_reedit_rounds": MAX_REEDIT_ROUNDS,
        "binding": compat_binding,
        "pairwise": {
            "selection": handoff["pairwise"]["model_facing_selection"],
            "mapped_candidate_id": handoff["pairwise"]["selected_candidate_id"],
            "output_digest": handoff["pairwise"]["output_digest"],
        },
        "coverage": _clone(handoff["coverage"]),
        "summary_uncertainty": handoff["summary_uncertainty"],
        "directives": directives,
        "bridge_r26_authority": _clone(_MEDIA_R19_COMPAT_BRIDGE_R26),
        "media_r18_authority": _clone(_MEDIA_R19_COMPAT_MEDIA_R18),
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
    compat["handoff_id"] = "gcrh1:" + _sha({
        "critic_output_digest": compat_binding["critic_output_digest"],
        "pairwise_output_digest": compat["pairwise"]["output_digest"],
        "reedit_round": compat["reedit_round"],
    })
    material = copy.deepcopy(compat)
    material["handoff_digest"] = ""
    compat["handoff_digest"] = _sha(material)
    adapter = {
        "contractVersion": ADAPTER_VERSION,
        "sourceGrowthAuthorityDigest": _profile_digest(GROWTH_R26_AUTHORITY),
        "sourceEnvelopeDigest": envelope["envelope_digest"],
        "sourceHandoffDigest": handoff["handoff_digest"],
        "sourcePackageDigest": envelope["review"]["package_digest"],
        "sourceSealedMappingDigest": envelope["review"]["sealed_mapping_digest"],
        "sourceCaptureDigest": envelope["capture"]["capture_digest"],
        "sourceAssistantResponseDigest": envelope["capture"]["assistant_response_digest"],
        "candidateId": binding["candidate_id"],
        "roundIndex": binding["review_round"],
        "mediaR19CompatibilityHandoffDigest": compat["handoff_digest"],
        "legacyAuthorityFieldsAreExecutionSchemaCompatibilityOnly": True,
        "legacyAuthorityFieldsAcceptedAsLiveProvenance": False,
        "modelJudgmentSynthesized": False,
    }
    adapter["adapterDigest"] = _sha(adapter)
    return compat, adapter


def _normalized_review(
    envelope: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    compat, adapter = adapt_growth_r26_for_media_r19(envelope, context)
    binding = envelope["creator_event"]["handoff"]["binding"]
    candidate = context["candidate"]
    review = {
        "state": envelope["candidate"]["state"],
        "roundIndex": envelope["review"]["review_round"],
        "source": {
            "sourceId": binding["source_id"],
            "sha256": binding["source_sha256"],
            "size": binding["source_size"],
        },
        "candidate": {
            "candidateId": binding["candidate_id"],
            "renderSha256": binding["render_sha256"],
            "renderSize": binding["render_size"],
            "renderExportSha256": binding["render_export_sha256"],
            "renderProducerSha": candidate["renderProducerSha"],
            "attachmentIdentity": compat["binding"]["attachment_identity"],
            "attachmentSha256": binding["attachment_sha256"],
            "attachmentSize": binding["attachment_size"],
        },
        "criticOutputDigest": binding["critic_output_digest"],
        "handoff": compat,
        "captureId": envelope["capture"]["capture_id"],
        "captureDigest": envelope["capture"]["capture_digest"],
        "envelopeDigest": envelope["envelope_digest"],
    }
    return review, adapter


def execute_media_reedit(
    *,
    media_checkout: Path,
    candidate_root: Path,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    verify_media_checkout(media_checkout)
    envelope = validate_review_against_context(
        envelope, context, candidate_root=candidate_root
    )
    if envelope["candidate"]["state"] != "targeted_reedit":
        raise R29Error("re-edit requires targeted_reedit")
    if envelope["review"]["review_round"] >= MAX_REEDIT_ROUNDS:
        raise RoundLimit("third re-edit attempt rejected")
    review, adapter = _normalized_review(envelope, context)
    result = r28.execute_media_reedit(
        media_checkout=media_checkout,
        media_profile=_r19_runtime_profile(),
        candidate_root=candidate_root,
        context=context,
        review=review,
        out_dir=out_dir,
    )
    application = result["application"]
    if (
        application.get("contractVersion") != MEDIA_R21_AUTHORITY["applicationContract"]
        or application.get("producer") != {
            "repository": MEDIA_R21_AUTHORITY["repository"],
            "sha": MEDIA_R21_AUTHORITY["producerSha"],
        }
        or application.get("handoff", {}).get("digest")
        != adapter["mediaR19CompatibilityHandoffDigest"]
    ):
        raise LineageDrift("Media R21 application/adapter lineage mismatch")
    adapter_path = Path(out_dir).resolve() / "creator.growth_r26_media_r19_adapter.r29.v1.json"
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(
        json.dumps(adapter, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result["adapter"] = adapter
    result["adapterPath"] = str(adapter_path)
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
    candidate = {
        "candidateId": after["candidateId"].replace(":r28:", ":r29:"),
        "roundIndex": media_result["evidence"]["nextRoundIndex"],
        "finalPath": final_path.relative_to(root).as_posix(),
        "renderSha256": after["sha256"],
        "renderSize": after["size"],
        "renderExportPath": export_path.relative_to(root).as_posix(),
        "renderExportSha256": after["renderExportSha256"],
        "renderExportDigest": after["renderExportDigest"],
        "renderProducerSha": MEDIA_R21_AUTHORITY["producerSha"],
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
    context = r28.validate_candidate_context(context)
    candidate = context["candidate"]
    return {
        "candidateId": candidate["candidateId"],
        "roundNumber": candidate["roundIndex"],
        "source": _clone(context["source"]),
        "render": {
            "path": candidate["finalPath"],
            "sha256": candidate["renderSha256"],
            "size": candidate["renderSize"],
        },
        "renderExport": {
            "path": candidate["renderExportPath"],
            "fileSha256": candidate["renderExportSha256"],
            "digest": candidate["renderExportDigest"],
        },
        "renderProducerSha": candidate["renderProducerSha"],
        "editorialApplication": _clone(candidate["editorialApplication"]),
        "reviewDerivative": None,
    }


def build_r21_next_package(
    *,
    media_checkout: Path,
    candidate_root: Path,
    before_context: Mapping[str, Any],
    after_context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    verify_media_checkout(media_checkout)
    before = r28.validate_candidate_context(before_context)
    after = r28.validate_candidate_context(after_context)
    envelope = validate_growth_r26_envelope(envelope)
    if after["candidate"]["roundIndex"] != before["candidate"]["roundIndex"] + 1:
        raise RoundLimit("R21 package round is not N+1")
    if after["candidate"]["roundIndex"] > MAX_REEDIT_ROUNDS:
        raise RoundLimit("R21 package exceeds max two rounds")
    request = {
        "contractVersion": "media.review_round_request.r21.v1",
        "review": {
            "mode": "targeted_reedit",
            "baseline": {
                "candidate": _descriptor(before),
                "briefLineageDigest": before["briefDigest"],
            },
            "challenger": {
                "candidate": _descriptor(after),
                "briefLineageDigest": after["briefDigest"],
            },
            "priorReview": {
                "contractVersion": "media.prior_review_selection.r21.v1",
                "selectedCandidateId": before["candidate"]["candidateId"],
                "reviewRound": before["candidate"]["roundIndex"],
                "reviewPackageDigest": envelope["review"]["package_digest"],
                "sealedMappingDigest": envelope["review"]["sealed_mapping_digest"],
                "decisionEvidenceDigest": envelope["candidate"]["handoff_digest"],
                "evidenceType": "growth_reedit_handoff",
            },
        },
    }
    root = Path(candidate_root).resolve()
    work = Path(out_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    request_path = work / "media.review_round_request.r21.v1.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    package_dir = work / "package"
    env = dict(os.environ)
    env["GITHUB_SHA"] = MEDIA_R21_AUTHORITY["producerSha"]
    proc = subprocess.run(
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
    if proc.returncode != 0:
        raise PackageDrift("Media R21 package build failed: " + proc.stderr[-5000:])
    lines = [
        line for line in proc.stdout.splitlines()
        if line.startswith("R21_REVIEW_ROUND ")
    ]
    if not lines:
        raise PackageDrift("Media R21 package result line missing")
    log = json.loads(lines[-1].split(" ", 1)[1])
    bundle_path = package_dir / "media.review_round_bundle.r21.v1.json"
    evidence_path = package_dir / "media.review_round_bundle.r21.evidence.json"
    mapping_path = package_dir / "media.review_round_sealed_mapping.r21.v1.json"
    handoff_path = package_dir / "media.review_round_transport_handoff.r21.v1.json"
    prompt_path = package_dir / "model-review-prompt.txt.json"
    for path in (bundle_path, evidence_path, mapping_path, handoff_path, prompt_path):
        if not path.is_file():
            raise PackageDrift("Media R21 package output incomplete")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if (
        bundle.get("contractVersion") != MEDIA_R21_AUTHORITY["reviewBundleContract"]
        or bundle.get("producer") != {
            "repository": MEDIA_R21_AUTHORITY["repository"],
            "sha": MEDIA_R21_AUTHORITY["producerSha"],
        }
        or bundle.get("mode") != "targeted_reedit"
        or bundle.get("reviewRound") != after["candidate"]["roundIndex"]
    ):
        raise PackageDrift("Media R21 bundle authority/round drift")
    if (
        evidence.get("packageDigest") != log.get("packageDigest")
        or evidence.get("sealedMappingDigest") != log.get("sealedMappingDigest")
        or evidence.get("roundLineageDigest") != log.get("roundLineageDigest")
        or evidence.get("promptDigest") != log.get("promptDigest")
    ):
        raise PackageDrift("Media R21 log/evidence digest drift")
    if bundle.get("transportHandoff", {}).get("packageDigest") != log["packageDigest"]:
        raise PackageDrift("Media R21 transport package digest drift")
    if mapping.get("digest") != log["sealedMappingDigest"]:
        raise PackageDrift("Media R21 sealed mapping digest drift")
    if bundle.get("roundLineage", {}).get("priorReview", {}).get(
        "decisionEvidenceDigest"
    ) != envelope["candidate"]["handoff_digest"]:
        raise PackageDrift("Media R21 prior review handoff digest drift")
    if bundle.get("roundLineage", {}).get("parentRenderSha256") != before["candidate"]["renderSha256"]:
        raise PackageDrift("Media R21 baseline render lineage drift")
    if bundle.get("roundLineage", {}).get("childRenderSha256") != after["candidate"]["renderSha256"]:
        raise PackageDrift("Media R21 challenger render lineage drift")
    for attachment in bundle["attachments"]:
        path = package_dir / attachment["path"]
        if (
            not path.is_file()
            or r28._file_sha(path) != attachment["sha256"]
            or r28._file_size(path) != attachment["size"]
        ):
            raise PackageDrift("Media R21 attachment byte drift")
    result = {
        "contractVersion": PACKAGE_RESULT_VERSION,
        "producerSha": MEDIA_R21_AUTHORITY["producerSha"],
        "reviewRound": bundle["reviewRound"],
        "baselineCandidateId": before["candidate"]["candidateId"],
        "challengerCandidateId": after["candidate"]["candidateId"],
        "baselineRenderSha256": before["candidate"]["renderSha256"],
        "challengerRenderSha256": after["candidate"]["renderSha256"],
        "sourceGrowthR26EnvelopeDigest": envelope["envelope_digest"],
        "sourceGrowthR26HandoffDigest": envelope["candidate"]["handoff_digest"],
        "packageDigest": log["packageDigest"],
        "sealedMappingDigest": log["sealedMappingDigest"],
        "roundLineageDigest": log["roundLineageDigest"],
        "promptDigest": log["promptDigest"],
        "bundleFileSha256": r28._file_sha(bundle_path),
        "evidenceFileSha256": r28._file_sha(evidence_path),
        "sealedMappingFileSha256": r28._file_sha(mapping_path),
        "transportHandoffFileSha256": r28._file_sha(handoff_path),
        "modelReviewPerformed": False,
        "liveProviderMutation": False,
        "humanLevelQualityClaimed": False,
    }
    result["resultDigest"] = _sha(result)
    result_path = work / "creator.media_r21_round_package_result.r29.v1.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "evidence": result,
        "bundle": bundle,
        "packageDir": str(package_dir),
        "bundlePath": str(bundle_path),
        "transportHandoffPath": str(handoff_path),
        "resultPath": str(result_path),
    }


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
                digest = material.pop("eventDigest")
                if (
                    event.get("ledgerVersion") != LEDGER_VERSION
                    or event.get("sequence") != len(self.events) + 1
                    or _sha(material) != digest
                ):
                    raise ReplayConflict("R29 ledger corruption")
                if event["eventKey"] in self.by_key:
                    raise ReplayConflict("R29 duplicate durable key")
                self.events.append(event)
                self.by_key[event["eventKey"]] = event

    def append_once(self, key: str, event_type: str, payload: Mapping[str, Any]) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if prior["eventType"] != event_type or prior["payload"] != normalized:
                raise ReplayConflict(f"conflicting durable replay for {key}")
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
        return _sha([row for row in self.events if row["eventKey"] != "terminal"])


def readiness_report() -> dict[str, Any]:
    report = {
        "contractVersion": REPORT_VERSION,
        "creatorBaseSha": CREATOR_BASE_SHA,
        "state": "BLOCKED_WAITING_GENUINE_DYNAMIC_CAPTURE",
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": False,
        "REAL_REEDIT_EXECUTED": False,
        "NEXT_REVIEW_PACKAGE_READY": False,
        "PUBLISH_HANDOFF_READY": False,
        "mediaR21Authority": _clone(MEDIA_R21_AUTHORITY),
        "growthR26Authority": _clone(GROWTH_R26_AUTHORITY),
        "bridgeR30Authority": _clone(BRIDGE_R30_AUTHORITY),
        "growthR26ExactHeadArtifact": {
            "ciRunId": 36996617627,
            "artifactId": 11221662698,
            "artifactName": "growth-r26-dynamic-review-capture",
            "artifactDigest": "sha256:d06e589d294dc942109834801fe676300f87dfce1ddbfde1877b65f7cf70cb31",
            "state": "SOURCE_READY",
            "liveCapture": None,
            "creatorEnvelopes": None,
        },
        "maxReeditRounds": MAX_REEDIT_ROUNDS,
        "r19CompatibilityBoundary": {
            "exactMediaR21R19RuntimeUsed": True,
            "legacyAuthorityFieldsAreExecutionSchemaCompatibilityOnly": True,
            "legacyAuthorityFieldsAcceptedAsLiveProvenance": False,
            "sourceLiveAuthority": "Growth R26 + Bridge R30 + Media R21 only",
        },
        "providerInvoked": False,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "captchaOr2faBypass": False,
        "humanLevelQualityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    return report


def _terminal_growth_validator(value: Mapping[str, Any], *, expected_source_id: str, expected_render_sha256: str) -> dict[str, Any]:
    envelope = validate_growth_r26_envelope(value)
    if envelope["candidate"]["state"] != "winner":
        raise r23.EditorOutcomeIneligible("only Growth R26 winner may publish")
    if envelope["candidate"]["source_id"] != expected_source_id:
        raise r23.EditorPublishHandoffError("R29 terminal source mismatch")
    if envelope["candidate"]["render_sha256"] != expected_render_sha256:
        raise r23.EditorPublishHandoffError("R29 terminal render mismatch")
    return envelope


def _build_final_bundle(
    *,
    context: Mapping[str, Any],
    envelope: Mapping[str, Any],
    ledger: Ledger,
) -> dict[str, Any]:
    # R28's Media render shape remains the accepted R23 editor-bundle bridge.
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
            "ledgerDigest": ledger.preterminal_digest,
            "growthCriticPin": {
                "authorityProfileDigest": _profile_digest(GROWTH_R26_AUTHORITY),
                "producerSha": GROWTH_R26_AUTHORITY["producerSha"],
                "envelopeDigest": envelope["envelope_digest"],
                "captureDigest": envelope["capture"]["capture_digest"],
            },
            "mediaRenderExport": {
                "authorityProfileDigest": _profile_digest(MEDIA_R21_AUTHORITY),
                "producerSha": context["candidate"]["renderProducerSha"],
                "renderExportDigest": context["candidate"]["renderExportDigest"],
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return bundle


def run_continuation(
    *,
    media_checkout: Path,
    growth_checkout: Path,
    bridge_checkout: Path,
    candidate_root: Path,
    candidate_context_path: Path,
    review_envelope_path: Path,
    out_dir: Path,
    release_authorization_path: Path | None = None,
    publish_target: Mapping[str, str] | None = None,
    inject_lost_ack_after_media: bool = False,
) -> dict[str, Any]:
    media_pin = verify_media_checkout(media_checkout)
    growth_pin = verify_growth_checkout(growth_checkout)
    bridge_pin = verify_bridge_checkout(bridge_checkout)
    context = r28.validate_candidate_context(
        json.loads(Path(candidate_context_path).read_text(encoding="utf-8"))
    )
    envelope = validate_review_against_context(
        json.loads(Path(review_envelope_path).read_text(encoding="utf-8")),
        context,
        candidate_root=candidate_root,
    )
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out / "exact-dynamic-e2e-ledger.r29.jsonl")
    ledger.append_once(
        "start",
        "r29_started",
        {
            "contextDigest": context["contextDigest"],
            "mediaAuthorityDigest": media_pin["profileDigest"],
            "growthAuthorityDigest": growth_pin["profileDigest"],
            "bridgeAuthorityDigest": bridge_pin["profileDigest"],
        },
    )
    round_index = envelope["review"]["review_round"]
    review_key = f"review:{round_index}"
    review_status = ledger.append_once(
        review_key,
        "growth_r26_live_review",
        {
            "envelopeDigest": envelope["envelope_digest"],
            "captureDigest": envelope["capture"]["capture_digest"],
            "assistantResponseDigest": envelope["capture"]["assistant_response_digest"],
            "packageDigest": envelope["review"]["package_digest"],
            "sealedMappingDigest": envelope["review"]["sealed_mapping_digest"],
            "handoffDigest": envelope["candidate"]["handoff_digest"],
            "candidateId": envelope["candidate"]["candidate_id"],
            "renderSha256": envelope["candidate"]["render_sha256"],
            "state": envelope["candidate"]["state"],
        },
    )
    state = envelope["candidate"]["state"]
    if state == "targeted_reedit":
        if round_index >= MAX_REEDIT_ROUNDS:
            raise RoundLimit("third re-edit attempt rejected")
        media_key = "media:" + envelope["envelope_digest"]
        media_prior = ledger.by_key.get(media_key)
        media_result = execute_media_reedit(
            media_checkout=media_checkout,
            candidate_root=candidate_root,
            context=context,
            envelope=envelope,
            out_dir=Path(candidate_root).resolve(),
        )
        if (
            inject_lost_ack_after_media
            and media_prior is None
            and media_result["evidence"]["logicalEffects"] == 1
        ):
            raise InjectedLostAck("injected lost ACK after exact Media effect")
        ledger.append_once(
            media_key,
            "media_r21_r19_reedit",
            {
                "sourceEnvelopeDigest": envelope["envelope_digest"],
                "sourceHandoffDigest": envelope["candidate"]["handoff_digest"],
                "adapterDigest": media_result["adapter"]["adapterDigest"],
                "resultDigest": media_result["evidence"]["resultDigest"],
                "beforeSha256": media_result["evidence"]["before"]["sha256"],
                "afterSha256": media_result["evidence"]["after"]["sha256"],
                "afterSize": media_result["evidence"]["after"]["size"],
            },
        )
        next_context = build_next_context(
            prior=context,
            media_result=media_result,
            candidate_root=candidate_root,
        )
        next_context_path = out / "next-candidate-context.json"
        next_context_path.write_text(
            json.dumps(next_context, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        package_key = "package:" + str(next_context["candidate"]["roundIndex"])
        package_prior = ledger.by_key.get(package_key)
        package_result = build_r21_next_package(
            media_checkout=media_checkout,
            candidate_root=candidate_root,
            before_context=context,
            after_context=next_context,
            envelope=envelope,
            out_dir=Path(candidate_root).resolve()
            / ".creator-r29-packages"
            / envelope["envelope_digest"][:24],
        )
        ledger.append_once(
            package_key,
            "media_r21_review_round_package",
            {
                "resultDigest": package_result["evidence"]["resultDigest"],
                "packageDigest": package_result["evidence"]["packageDigest"],
                "sealedMappingDigest": package_result["evidence"]["sealedMappingDigest"],
                "roundLineageDigest": package_result["evidence"]["roundLineageDigest"],
                "baselineRenderSha256": package_result["evidence"]["baselineRenderSha256"],
                "challengerRenderSha256": package_result["evidence"]["challengerRenderSha256"],
            },
        )
        report = {
            "contractVersion": REPORT_VERSION,
            "state": "BLOCKED_WAITING_GENUINE_DYNAMIC_CAPTURE",
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": True,
            "REAL_REEDIT_EXECUTED": True,
            "NEXT_REVIEW_PACKAGE_READY": True,
            "PUBLISH_HANDOFF_READY": False,
            "roundIndex": round_index,
            "nextRoundIndex": next_context["candidate"]["roundIndex"],
            "reviewReplay": review_status == "duplicate",
            "mediaReplay": media_result["evidence"]["replayed"],
            "packageReplay": package_prior is not None,
            "beforeRenderSha256": media_result["evidence"]["before"]["sha256"],
            "afterRenderSha256": media_result["evidence"]["after"]["sha256"],
            "afterRenderSize": media_result["evidence"]["after"]["size"],
            "sourceEnvelopeDigest": envelope["envelope_digest"],
            "sourceHandoffDigest": envelope["candidate"]["handoff_digest"],
            "sourceCaptureDigest": envelope["capture"]["capture_digest"],
            "sourceAssistantResponseDigest": envelope["capture"]["assistant_response_digest"],
            "nextPackageDigest": package_result["evidence"]["packageDigest"],
            "nextSealedMappingDigest": package_result["evidence"]["sealedMappingDigest"],
            "nextRoundLineageDigest": package_result["evidence"]["roundLineageDigest"],
            "nextTransportHandoffPath": package_result["transportHandoffPath"],
            "ledgerDigest": ledger.digest,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "credentialsUsed": False,
            "captchaOr2faBypass": False,
            "humanLevelQualityClaimed": False,
        }
        report["reportDigest"] = _sha(report)
        (out / "exact_dynamic_e2e.r29.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    if state != "winner":
        terminal = "human_review_required" if state in {"human_review", "reedit_limit_reached"} else state
        ledger.append_once(
            "terminal",
            "nonpublishable_review_outcome",
            {
                "state": terminal,
                "envelopeDigest": envelope["envelope_digest"],
                "renderSha256": context["candidate"]["renderSha256"],
            },
        )
        report = {
            "contractVersion": REPORT_VERSION,
            "state": terminal,
            "SOURCE_READY": True,
            "REAL_REVIEW_INGESTED": True,
            "REAL_REEDIT_EXECUTED": False,
            "NEXT_REVIEW_PACKAGE_READY": False,
            "PUBLISH_HANDOFF_READY": False,
            "roundIndex": round_index,
            "ledgerDigest": ledger.digest,
            "providerInvoked": False,
            "liveProviderMutation": False,
            "humanLevelQualityClaimed": False,
        }
        report["reportDigest"] = _sha(report)
        (out / "exact_dynamic_e2e.r29.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    root = Path(candidate_root).resolve()
    final_source = (root / context["candidate"]["finalPath"]).resolve()
    final_path = out / "final.mp4"
    shutil.copyfile(final_source, final_path)
    asset = r21.probe_media(final_path)
    if (
        asset.sha256 != context["candidate"]["renderSha256"]
        or asset.size_bytes != context["candidate"]["renderSize"]
    ):
        raise LineageDrift("winner final.mp4 lineage mismatch")
    bundle = _build_final_bundle(context=context, envelope=envelope, ledger=ledger)
    (out / "editor-final-bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    publish_handoff = None
    if release_authorization_path is not None:
        if publish_target is None:
            raise R29Error("publish target required with release authorization")
        auth = json.loads(Path(release_authorization_path).read_text(encoding="utf-8"))
        publish_handoff = r23.build_editor_publish_handoff(
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
            json.dumps(publish_handoff, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    ledger.append_once(
        "terminal",
        "winner_terminal",
        {
            "envelopeDigest": envelope["envelope_digest"],
            "winnerCandidateId": context["candidate"]["candidateId"],
            "finalRenderSha256": asset.sha256,
            "bundleDigest": bundle["bundleDigest"],
            "publishHandoffDigest": (
                None if publish_handoff is None else publish_handoff["handoffDigest"]
            ),
        },
    )
    report = {
        "contractVersion": REPORT_VERSION,
        "state": (
            "PUBLISH_HANDOFF_READY"
            if publish_handoff is not None
            else "WINNER_AWAITING_RELEASE_AUTHORIZATION"
        ),
        "SOURCE_READY": True,
        "REAL_REVIEW_INGESTED": True,
        "REAL_REEDIT_EXECUTED": context["candidate"]["roundIndex"] > 0,
        "NEXT_REVIEW_PACKAGE_READY": False,
        "PUBLISH_HANDOFF_READY": publish_handoff is not None,
        "winnerCandidateId": context["candidate"]["candidateId"],
        "finalRenderSha256": asset.sha256,
        "finalRenderSize": asset.size_bytes,
        "bundleDigest": bundle["bundleDigest"],
        "publishHandoffDigest": (
            None if publish_handoff is None else publish_handoff["handoffDigest"]
        ),
        "ledgerDigest": ledger.digest,
        "providerInvoked": False,
        "liveProviderMutation": False,
        "humanLevelQualityClaimed": False,
    }
    report["reportDigest"] = _sha(report)
    (out / "exact_dynamic_e2e.r29.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-exact-dynamic-r29")
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("readiness")
    ready.add_argument("--out")
    run = sub.add_parser("continue")
    run.add_argument("--media-checkout", required=True)
    run.add_argument("--growth-checkout", required=True)
    run.add_argument("--bridge-checkout", required=True)
    run.add_argument("--candidate-root", required=True)
    run.add_argument("--candidate-context", required=True)
    run.add_argument("--growth-envelope", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--release-authorization")
    run.add_argument("--publish-target")
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
        report = run_continuation(
            media_checkout=Path(args.media_checkout),
            growth_checkout=Path(args.growth_checkout),
            bridge_checkout=Path(args.bridge_checkout),
            candidate_root=Path(args.candidate_root),
            candidate_context_path=Path(args.candidate_context),
            review_envelope_path=Path(args.growth_envelope),
            out_dir=Path(args.out),
            release_authorization_path=(
                None if not args.release_authorization
                else Path(args.release_authorization)
            ),
            publish_target=(
                None if not args.publish_target
                else _load(args.publish_target)
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
            "providerInvoked": False,
            "liveProviderMutation": False,
            "humanLevelQualityClaimed": False,
        }
        print(json.dumps(blocked, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
