from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import autonomous_reels as reels

MEDIA_R13_COMPAT_VERSION = "media.creator_consumer_compat.r13.v1"
MEDIA_R13_REPOSITORY = "foto6/video2"
MEDIA_R13_BRANCH = "agent/media-r13-creator-compat-20261001"
MEDIA_R13_PRODUCER_SHA = "ad4e0ba487a3cabc84dd339d412e19a0db0f9add"
MEDIA_R13_CI_RUN_ID = "36801556474"
MEDIA_R13_CI_CONCLUSION = "success"
MEDIA_R13_ARTIFACT_ID = "11136028209"
MEDIA_R13_BUNDLE_SHA256 = "e5f45429604519e2776fddeedb11032baae2728799aebfff2f6f1076686eeb7f"
MEDIA_R13_ENVELOPE_SHA256 = "e7ee654f3a3b098f32d7611ff721e506eb26caffe44d1a77aa25f077be94541c"

COMPAT_MANIFEST_PATH = "conformance/media.creator_consumer_compat.r13.v1/manifest.json"
COMPAT_CONTRACT_PATH = "conformance/media.creator_consumer_compat.r13.v1/contract.json"
RESULT_SCHEMA_PATH = "conformance/media.creator_consumer_compat.r13.v1/schemas/result-envelope.schema.json"
TECHNICAL_QA_SCHEMA_PATH = "conformance/media.creator_consumer_compat.r13.v1/schemas/technical-qa.schema.json"
CREATIVE_QUALITY_SCHEMA_PATH = "conformance/media.creator_consumer_compat.r13.v1/schemas/creative-quality-report.schema.json"
BUNDLE_FIXTURE_PATH = "fixtures/media_r13_cross_repo/compatibility-bundle.json"

EXPECTED_PINS = {
    "mediaJobConsumerManifest": {
        "path": "conformance/media.job.v1/consumer-manifest.json",
        "gitBlobSha": "96b252acae743f8fe059fd634ee320f92bd9c79c",
    },
    "mediaArtifactManifest": {
        "path": "conformance/media.artifact_manifest.v1/manifest.json",
        "gitBlobSha": "42aed1ca4720cddd4a5e48af076bc73b663322b0",
    },
    "creativePlanManifest": {
        "path": "conformance/media.creative_edit_plan.r12.v1/manifest.json",
        "gitBlobSha": "d031a07f1d392c690942bd5f8288a1713f1af791",
    },
    "creativePlanContract": {
        "path": "conformance/media.creative_edit_plan.r12.v1/contract.json",
        "gitBlobSha": "5298aeb2a9e4e13ed31b1610ce88778b7a911592",
    },
    "shortformEditorManifest": {
        "path": "conformance/media.shortform_editor.r11.v1/manifest.json",
        "gitBlobSha": "07c38a048d23490b8e55924697650e9969bf089f",
    },
    "shortformProfile": {
        "path": "conformance/media.shortform_editor.r11.v1/profile.json",
        "gitBlobSha": "d8f19d9a9d117c5736238159bd5e6d2491370986",
    },
    "compatContract": {
        "path": COMPAT_CONTRACT_PATH,
        "gitBlobSha": "ecfeaed347b53ed549124b9d1701ebf70b37eea3",
    },
    "resultEnvelopeSchema": {
        "path": RESULT_SCHEMA_PATH,
        "gitBlobSha": "119b26b494df77c4ce8d83ffd63791afc112d264",
    },
    "technicalQaSchema": {
        "path": TECHNICAL_QA_SCHEMA_PATH,
        "gitBlobSha": "1b2f71e443b0038736e8be99f544493965693658",
    },
    "creativeQualitySchema": {
        "path": CREATIVE_QUALITY_SCHEMA_PATH,
        "gitBlobSha": "c63f95b45f5440aabd8c14dc5fcb8eeae1fc8535",
    },
}
COMPAT_MANIFEST_BLOB_SHA = "b750b347f6c6a7a2398e47e53e166f5fb1c72781"

OLD_FAILED_MEDIA_R12_SHA = "98f298b88faaef106fb412712d6c9824e2b926d9"
OLD_FAILED_MEDIA_R12_CI_RUN_ID = "36799818187"


class MediaR13CompatibilityError(ValueError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_blob_sha_bytes(value: bytes) -> str:
    prefix = f"blob {len(value)}\0".encode("ascii")
    return hashlib.sha1(prefix + value).hexdigest()


def _path_bytes(root: Path, relative_path: str) -> bytes:
    path = root / relative_path
    if not path.is_file():
        raise MediaR13CompatibilityError(
            f"required pinned Media contract file missing: {relative_path}"
        )
    return path.read_bytes()


def validate_local_pinned_contracts(
    *,
    repo_root: Path | None = None,
) -> dict[str, str]:
    root = repo_root or _repo_root()
    actual: dict[str, str] = {}
    for name, pin in EXPECTED_PINS.items():
        blob_sha = git_blob_sha_bytes(_path_bytes(root, pin["path"]))
        if blob_sha != pin["gitBlobSha"]:
            raise MediaR13CompatibilityError(
                f"pinned Media blob mismatch for {name}: "
                f"expected {pin['gitBlobSha']}, got {blob_sha}"
            )
        actual[name] = blob_sha
    manifest_sha = git_blob_sha_bytes(
        _path_bytes(root, COMPAT_MANIFEST_PATH)
    )
    if manifest_sha != COMPAT_MANIFEST_BLOB_SHA:
        raise MediaR13CompatibilityError(
            "Media R13 compatibility manifest Git blob mismatch"
        )
    actual["creatorCompatManifest"] = manifest_sha
    return actual


def _load_json(root: Path, relative_path: str) -> Any:
    try:
        return json.loads(_path_bytes(root, relative_path))
    except json.JSONDecodeError as exc:
        raise MediaR13CompatibilityError(
            f"invalid JSON in pinned Media file {relative_path}"
        ) from exc


def _resolve_ref(
    schema: Mapping[str, Any],
    *,
    repo_root: Path,
) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    mapping = {
        "./technical-qa.schema.json": TECHNICAL_QA_SCHEMA_PATH,
        "./creative-quality-report.schema.json": CREATIVE_QUALITY_SCHEMA_PATH,
    }
    try:
        path = mapping[ref]
    except KeyError as exc:
        raise MediaR13CompatibilityError(
            f"unsupported pinned schema ref {ref!r}"
        ) from exc
    value = _load_json(repo_root, path)
    if not isinstance(value, Mapping):
        raise MediaR13CompatibilityError("referenced schema must be an object")
    return value


def _schema_validate(
    value: Any,
    schema: Mapping[str, Any],
    *,
    repo_root: Path,
    label: str,
) -> None:
    schema = _resolve_ref(schema, repo_root=repo_root)
    if "anyOf" in schema:
        errors = []
        for branch in schema["anyOf"]:
            try:
                _schema_validate(
                    value,
                    branch,
                    repo_root=repo_root,
                    label=label,
                )
                return
            except MediaR13CompatibilityError as exc:
                errors.append(str(exc))
        raise MediaR13CompatibilityError(
            f"{label} failed every anyOf branch: {'; '.join(errors)}"
        )
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            raise MediaR13CompatibilityError(f"{label} must be an object")
        required = set(schema.get("required", []))
        missing = required - set(value)
        if missing:
            raise MediaR13CompatibilityError(
                f"{label} missing required fields: {sorted(missing)}"
            )
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise MediaR13CompatibilityError(
                    f"{label} has unknown fields: {sorted(unknown)}"
                )
        for name, child_schema in properties.items():
            if name in value:
                _schema_validate(
                    value[name],
                    child_schema,
                    repo_root=repo_root,
                    label=f"{label}.{name}",
                )
        additional = schema.get("additionalProperties")
        if isinstance(additional, Mapping):
            for name, child in value.items():
                if name not in properties:
                    _schema_validate(
                        child,
                        additional,
                        repo_root=repo_root,
                        label=f"{label}.{name}",
                    )
    elif expected_type == "array":
        if not isinstance(value, list):
            raise MediaR13CompatibilityError(f"{label} must be an array")
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            raise MediaR13CompatibilityError(
                f"{label} must contain at least {minimum} items"
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, child in enumerate(value):
                _schema_validate(
                    child,
                    item_schema,
                    repo_root=repo_root,
                    label=f"{label}[{index}]",
                )
    elif expected_type == "string":
        if not isinstance(value, str):
            raise MediaR13CompatibilityError(f"{label} must be a string")
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            raise MediaR13CompatibilityError(
                f"{label} must have length >= {minimum}"
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise MediaR13CompatibilityError(
                f"{label} does not match pinned schema pattern"
            )
    elif expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise MediaR13CompatibilityError(f"{label} must be an integer")
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise MediaR13CompatibilityError(
                f"{label} must be >= {minimum}"
            )
    elif expected_type == "null":
        if value is not None:
            raise MediaR13CompatibilityError(f"{label} must be null")
    if "const" in schema and value != schema["const"]:
        raise MediaR13CompatibilityError(
            f"{label} must equal pinned const {schema['const']!r}"
        )


def _expected_contract_digests() -> dict[str, Any]:
    result = {name: dict(pin) for name, pin in EXPECTED_PINS.items()}
    result["creatorCompatManifest"] = {
        "path": COMPAT_MANIFEST_PATH,
        "gitBlobSha": COMPAT_MANIFEST_BLOB_SHA,
    }
    return result


@dataclass(frozen=True)
class MediaR13ProductionPin:
    producer_sha: str = MEDIA_R13_PRODUCER_SHA
    ci_run_id: str = MEDIA_R13_CI_RUN_ID
    ci_conclusion: str = MEDIA_R13_CI_CONCLUSION
    compatibility_contract_blob_sha: str = EXPECTED_PINS["compatContract"]["gitBlobSha"]
    result_envelope_schema_blob_sha: str = EXPECTED_PINS["resultEnvelopeSchema"]["gitBlobSha"]
    technical_qa_schema_blob_sha: str = EXPECTED_PINS["technicalQaSchema"]["gitBlobSha"]
    creative_quality_schema_blob_sha: str = EXPECTED_PINS["creativeQualitySchema"]["gitBlobSha"]

    def validate(self) -> "MediaR13ProductionPin":
        if self.producer_sha != MEDIA_R13_PRODUCER_SHA:
            raise MediaR13CompatibilityError(
                "Media R13 producer SHA does not match exact production pin"
            )
        if self.ci_run_id != MEDIA_R13_CI_RUN_ID:
            raise MediaR13CompatibilityError(
                "Media R13 CI run ID does not match production pin"
            )
        if self.ci_conclusion != "success":
            raise MediaR13CompatibilityError(
                "Media R13 exact-head CI is not successful"
            )
        expected = {
            "compatibility_contract_blob_sha":
                EXPECTED_PINS["compatContract"]["gitBlobSha"],
            "result_envelope_schema_blob_sha":
                EXPECTED_PINS["resultEnvelopeSchema"]["gitBlobSha"],
            "technical_qa_schema_blob_sha":
                EXPECTED_PINS["technicalQaSchema"]["gitBlobSha"],
            "creative_quality_schema_blob_sha":
                EXPECTED_PINS["creativeQualitySchema"]["gitBlobSha"],
        }
        for field, required in expected.items():
            actual = getattr(self, field)
            if actual != required:
                raise MediaR13CompatibilityError(
                    f"Media R13 {field} changed from exact production pin"
                )
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "repository": MEDIA_R13_REPOSITORY,
            "branch": MEDIA_R13_BRANCH,
            "producerSha": self.producer_sha,
            "ciRunId": self.ci_run_id,
            "ciConclusion": self.ci_conclusion,
            "contractVersion": MEDIA_R13_COMPAT_VERSION,
            "compatibilityManifestBlobSha": COMPAT_MANIFEST_BLOB_SHA,
            "pins": _expected_contract_digests(),
        }


def _validate_manifest_contract(
    *,
    repo_root: Path,
) -> None:
    manifest = _load_json(repo_root, COMPAT_MANIFEST_PATH)
    contract = _load_json(repo_root, COMPAT_CONTRACT_PATH)
    if manifest.get("contractVersion") != MEDIA_R13_COMPAT_VERSION:
        raise MediaR13CompatibilityError(
            "compatibility manifest contract version mismatch"
        )
    if contract.get("contractVersion") != MEDIA_R13_COMPAT_VERSION:
        raise MediaR13CompatibilityError(
            "compatibility contract version mismatch"
        )
    if manifest.get("producerRepository") != MEDIA_R13_REPOSITORY:
        raise MediaR13CompatibilityError(
            "compatibility manifest repository mismatch"
        )
    if manifest.get("producerBranch") != MEDIA_R13_BRANCH:
        raise MediaR13CompatibilityError(
            "compatibility manifest branch mismatch"
        )
    if manifest.get("pins") != {
        name: dict(pin) for name, pin in EXPECTED_PINS.items()
    }:
        raise MediaR13CompatibilityError(
            "compatibility manifest pinned bundle changed"
        )
    if contract.get("producerRepository") != MEDIA_R13_REPOSITORY:
        raise MediaR13CompatibilityError(
            "compatibility contract repository mismatch"
        )
    if contract.get("resultEnvelopeSchema") != "schemas/result-envelope.schema.json":
        raise MediaR13CompatibilityError(
            "compatibility result envelope schema path changed"
        )
    guarantees = contract.get("compatibilityGuarantees")
    if not isinstance(guarantees, Mapping) or not all(
        guarantees.get(name) is True
        for name in (
            "r11TechnicalQaMustPass",
            "r12CreativeGuardrailsMustPass",
            "sourceProvenanceMustAlreadyPass",
            "contractPinsMustMatchExactly",
            "producerShaMustMatchPinnedExactHead",
        )
    ):
        raise MediaR13CompatibilityError(
            "compatibility guarantees do not preserve required fail-closed gates"
        )


def validate_envelope(
    envelope: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    pin: MediaR13ProductionPin | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    pin = (pin or MediaR13ProductionPin()).validate()
    validate_local_pinned_contracts(repo_root=root)
    _validate_manifest_contract(repo_root=root)
    schema = _load_json(root, RESULT_SCHEMA_PATH)
    if not isinstance(schema, Mapping):
        raise MediaR13CompatibilityError("result envelope schema must be an object")
    _schema_validate(
        envelope,
        schema,
        repo_root=root,
        label="Media R13 result envelope",
    )
    if envelope["producer"] != {
        "repository": MEDIA_R13_REPOSITORY,
        "sha": pin.producer_sha,
    }:
        raise MediaR13CompatibilityError(
            "Media R13 envelope producer SHA/repository mismatch"
        )
    if envelope["contractDigests"] != _expected_contract_digests():
        raise MediaR13CompatibilityError(
            "Media R13 envelope contract blob bundle mismatch"
        )
    technical = envelope["technicalQa"]
    if technical["passed"] is not True or technical["value"].get("passed") is not True:
        raise MediaR13CompatibilityError("Media R13 technical QA did not pass")
    if reels.sha256_json(technical["value"]) != technical["sha256"]:
        raise MediaR13CompatibilityError(
            "Media R13 technical QA digest mismatch"
        )
    for check in technical["value"].get("checks", []):
        if check.get("pass") is not True:
            raise MediaR13CompatibilityError(
                "Media R13 technical QA contains failed check"
            )
    creative = envelope["creativeQuality"]
    if creative["passed"] is not True:
        raise MediaR13CompatibilityError(
            "Media R13 creative quality did not pass"
        )
    if creative["creativePlanDigest"] != envelope["creativePlanDigest"]:
        raise MediaR13CompatibilityError(
            "Media R13 creative plan digest mismatch"
        )
    for guardrail in creative.get("guardrails", []):
        if guardrail.get("pass") is not True:
            raise MediaR13CompatibilityError(
                "Media R13 creative hard guardrail failed"
            )
    visual = creative.get("visualQa")
    if not isinstance(visual, Mapping) or visual.get("passed") is not True:
        raise MediaR13CompatibilityError(
            "Media R13 visual creative QA did not pass"
        )
    for check in visual.get("checks", []):
        if check.get("pass") is not True:
            raise MediaR13CompatibilityError(
                "Media R13 visual creative QA contains failed check"
            )
    probe = envelope["probeEvidence"]
    if reels.sha256_json(probe["value"]) != probe["sha256"]:
        raise MediaR13CompatibilityError(
            "Media R13 probe evidence digest mismatch"
        )
    final_content = envelope["finalContent"]
    if (
        probe["value"].get("outputSha256") != final_content["sha256"]
        or probe["value"].get("outputSize") != final_content["size"]
    ):
        raise MediaR13CompatibilityError(
            "Media R13 final content does not bind probe output"
        )
    source_evidence = probe["value"].get("sourceEvidence")
    if not isinstance(source_evidence, list) or not source_evidence:
        raise MediaR13CompatibilityError(
            "Media R13 source provenance evidence is missing"
        )
    for item in source_evidence:
        if not isinstance(item, Mapping):
            raise MediaR13CompatibilityError(
                "Media R13 source evidence item must be an object"
            )
        if (
            item.get("exists") is not True
            or item.get("local") is not True
            or item.get("probeOk") is not True
            or item.get("error") is not None
        ):
            raise MediaR13CompatibilityError(
                "Media R13 source evidence is not fully validated"
            )
        if (
            item.get("expectedSha256") != item.get("sha256")
            or item.get("expectedSize") != item.get("size")
        ):
            raise MediaR13CompatibilityError(
                "Media R13 source evidence digest/size mismatch"
            )
    reels._reject_secrets(envelope)
    return _clone(envelope)


def validate_bundle_value(
    bundle: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    pin: MediaR13ProductionPin | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    pin = (pin or MediaR13ProductionPin()).validate()
    if not isinstance(bundle, Mapping):
        raise MediaR13CompatibilityError(
            "Media R13 compatibility bundle must be an object"
        )
    if set(bundle) != {
        "bundleDigest",
        "compatibilityManifest",
        "contractDigests",
        "contractVersion",
        "demoConsumerEnvelope",
        "producer",
    }:
        raise MediaR13CompatibilityError(
            "Media R13 compatibility bundle fields changed"
        )
    if bundle["contractVersion"] != MEDIA_R13_COMPAT_VERSION:
        raise MediaR13CompatibilityError(
            "Media R13 compatibility bundle version mismatch"
        )
    if bundle["producer"] != {
        "repository": MEDIA_R13_REPOSITORY,
        "sha": pin.producer_sha,
    }:
        raise MediaR13CompatibilityError(
            "Media R13 compatibility bundle producer mismatch"
        )
    if bundle["compatibilityManifest"] != {
        "path": COMPAT_MANIFEST_PATH,
        "gitBlobSha": COMPAT_MANIFEST_BLOB_SHA,
    }:
        raise MediaR13CompatibilityError(
            "Media R13 compatibility manifest bundle binding mismatch"
        )
    if bundle["contractDigests"] != _expected_contract_digests():
        raise MediaR13CompatibilityError(
            "Media R13 compatibility bundle contract digests mismatch"
        )
    core = dict(bundle)
    bundle_digest = core.pop("bundleDigest")
    if reels.sha256_json(core) != bundle_digest:
        raise MediaR13CompatibilityError(
            "Media R13 compatibility bundle digest mismatch"
        )
    envelope = validate_envelope(
        bundle["demoConsumerEnvelope"],
        repo_root=root,
        pin=pin,
    )
    if envelope["contractDigests"] != bundle["contractDigests"]:
        raise MediaR13CompatibilityError(
            "Media R13 envelope does not bind bundle contract digests"
        )
    return _clone(bundle)


def load_and_validate_bundle(
    *,
    repo_root: Path | None = None,
    pin: MediaR13ProductionPin | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    raw = _path_bytes(root, BUNDLE_FIXTURE_PATH)
    if _sha256_bytes(raw) != MEDIA_R13_BUNDLE_SHA256:
        raise MediaR13CompatibilityError(
            "checked-in Media R13 workflow artifact bundle SHA-256 mismatch"
        )
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MediaR13CompatibilityError(
            "checked-in Media R13 workflow artifact bundle is invalid JSON"
        ) from exc
    return validate_bundle_value(
        bundle,
        repo_root=root,
        pin=pin,
    )

def readiness(
    *,
    repo_root: Path | None = None,
    pin: MediaR13ProductionPin | None = None,
) -> dict[str, Any]:
    pin = pin or MediaR13ProductionPin()
    try:
        bundle = load_and_validate_bundle(
            repo_root=repo_root,
            pin=pin,
        )
    except (MediaR13CompatibilityError, reels.AutonomousReelsError) as exc:
        report = {
            "state": "BLOCKED_MEDIA_R13",
            "productionMediaReady": False,
            "reason": str(exc),
            "expectedPin": MediaR13ProductionPin().as_dict(),
            "oldFailedMediaR12Rejected": True,
            "oldFailedMediaR12Sha": OLD_FAILED_MEDIA_R12_SHA,
        }
    else:
        envelope = bundle["demoConsumerEnvelope"]
        report = {
            "state": "READY_MEDIA_R13",
            "productionMediaReady": True,
            "reason": "exact Media R13 producer, compatibility contract, pinned blobs, and emitted CI artifact validated",
            "acceptedPin": pin.as_dict(),
            "ciRunId": MEDIA_R13_CI_RUN_ID,
            "ciConclusion": MEDIA_R13_CI_CONCLUSION,
            "workflowArtifactId": MEDIA_R13_ARTIFACT_ID,
            "workflowArtifactBundleSha256": MEDIA_R13_BUNDLE_SHA256,
            "workflowArtifactEnvelopeSha256": MEDIA_R13_ENVELOPE_SHA256,
            "bundleDigest": bundle["bundleDigest"],
            "logicalJobId": envelope["logicalJobId"],
            "artifactManifestDigest": envelope["artifactManifestDigest"],
            "timelineDigest": envelope["timelineDigest"],
            "technicalQaPassed": True,
            "creativeQualityPassed": True,
            "oldFailedMediaR12Rejected": True,
            "oldFailedMediaR12Sha": OLD_FAILED_MEDIA_R12_SHA,
            "livePublishingEnabled": False,
        }
    report["readinessDigest"] = reels.sha256_json(report)
    return report


def emit_exact_workflow_artifact(
    output_dir: str | Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    bundle = load_and_validate_bundle(repo_root=root)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    bundle_bytes = (reels.canonical_json(bundle) + "\n").encode("utf-8")
    envelope_bytes = (
        reels.canonical_json(bundle["demoConsumerEnvelope"]) + "\n"
    ).encode("utf-8")
    if _sha256_bytes(bundle_bytes) != MEDIA_R13_BUNDLE_SHA256:
        raise MediaR13CompatibilityError(
            "Creator reproduction cannot reproduce exact Media R13 bundle bytes"
        )
    if _sha256_bytes(envelope_bytes) != MEDIA_R13_ENVELOPE_SHA256:
        raise MediaR13CompatibilityError(
            "Creator reproduction cannot reproduce exact Media R13 envelope bytes"
        )
    bundle_path = target / "compatibility-bundle.json"
    envelope_path = target / "demo-consumer-envelope.json"
    bundle_path.write_bytes(bundle_bytes)
    envelope_path.write_bytes(envelope_bytes)
    return {
        "contractVersion": MEDIA_R13_COMPAT_VERSION,
        "producerSha": MEDIA_R13_PRODUCER_SHA,
        "ciRunId": MEDIA_R13_CI_RUN_ID,
        "workflowArtifactId": MEDIA_R13_ARTIFACT_ID,
        "bundlePath": str(bundle_path),
        "bundleSha256": _sha256_bytes(bundle_bytes),
        "envelopePath": str(envelope_path),
        "envelopeSha256": _sha256_bytes(envelope_bytes),
        "bundleDigest": bundle["bundleDigest"],
    }
