from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from creator_orchestrator import autonomous_reels as reels
from creator_orchestrator import mvp
from creator_orchestrator import semantic_export as export


def _ffmpeg(args):
    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=90,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr[-6000:])


def _talking(ffmpeg, path):
    _ffmpeg([
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", "color=c=0x335577:s=360x640:r=30:d=6",
        "-vf",
        "drawbox=x=105:y=90:w=150:h=180:color=white:t=fill,"
        "drawbox=x=70:y=285:w=220:h=260:color=0x88aacc:t=fill",
        "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ])


def _action(ffmpeg, path):
    colors = ["white", "yellow", "cyan", "magenta", "red", "lime"]
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
    for color in colors:
        args += ["-f", "lavfi", "-i", f"color=c={color}:s=360x640:r=30:d=1"]
    args += [
        "-filter_complex",
        "".join(f"[{i}:v]" for i in range(6)) + "concat=n=6:v=1:a=0[outv]",
        "-map", "[outv]", "-threads", "1", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
    ]
    _ffmpeg(args)


def _landscape(ffmpeg, path):
    _ffmpeg([
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6",
        "-vf",
        "drawgrid=w=160:h=90:t=2:color=white@0.35,"
        "drawbox=x=180:y=90:w=920:h=540:color=white@0.15:t=4",
        "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ])


def _valid_export():
    directives = {"mediaHints": {"beatMarkersMs": [1000]}}
    return {
        "contract_version": export.CONTRACT_VERSION,
        "repository": export.REPOSITORY,
        "commit_sha": "1" * 40,
        "source_id": "source-1",
        "source_sha256": "2" * 64,
        "brief_digest": "3" * 64,
        "analysis_contract": "creator.semantic_video_analysis.r18.v1",
        "director_report_contract": "creator.semantic_video_director.r18.v1",
        "semantic_timeline": {
            "semanticEvents": [{
                "evidenceType": "semantic_event",
                "startMs": 0,
                "endMs": 1000,
                "value": {"event": "hook"},
                "confidence": 0.5,
            }]
        },
        "unavailable_evidence": ["importantObjects"],
        "auto_style": "clean_podcast",
        "effective_style": "clean_podcast",
        "style_confidence": 0.5,
        "edit_directives": directives,
        "analysis_digest": "4" * 64,
        "directives_digest": reels.sha256_json(directives),
        "generation_mode": "deterministic_local_fallback",
    }


class SemanticExportR20ValidationTests(unittest.TestCase):
    def test_valid_contract_and_exact_keys(self):
        value = _valid_export()
        validated = export.validate_semantic_export(
            value,
            expected_commit_sha="1" * 40,
            expected_source_sha256="2" * 64,
            expected_brief_digest="3" * 64,
            expected_analysis_digest="4" * 64,
            expected_directives_digest=value["directives_digest"],
            source_duration_ms=6000,
        )
        self.assertEqual(set(validated), set(export.REQUIRED_KEYS))

    def test_source_sha_and_commit_binding_fail_closed(self):
        value = _valid_export()
        with self.assertRaises(export.SemanticExportError):
            export.validate_semantic_export(
                value,
                expected_commit_sha="9" * 40,
                source_duration_ms=6000,
            )
        with self.assertRaises(export.SemanticExportError):
            export.validate_semantic_export(
                value,
                expected_source_sha256="8" * 64,
                source_duration_ms=6000,
            )

    def test_out_of_bounds_timestamp_and_missing_field_fail_closed(self):
        value = _valid_export()
        value["semantic_timeline"]["semanticEvents"][0]["endMs"] = 7000
        with self.assertRaises(export.SemanticExportError):
            export.validate_semantic_export(
                value,
                source_duration_ms=6000,
            )
        missing = _valid_export()
        del missing["generation_mode"]
        with self.assertRaises(export.SemanticExportError):
            export.validate_semantic_export(
                missing,
                source_duration_ms=6000,
            )


@unittest.skipUnless(
    os.environ.get("CREATOR_MEDIA_R13_DIR"),
    "exact Media R13 checkout required for real R20 E2E",
)
class SemanticExportR20E2ETests(unittest.TestCase):
    def test_three_real_generated_sources_emit_canonical_export(self):
        ffmpeg = shutil.which("ffmpeg")
        self.assertIsNotNone(ffmpeg)
        media_repo = Path(os.environ["CREATOR_MEDIA_R13_DIR"]).resolve()
        creator_sha = export.current_creator_commit(
            Path(__file__).resolve().parents[1]
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generators = {
                "talking-head-r20": _talking,
                "action-r20": _action,
                "landscape-screen-r20": _landscape,
            }
            for source_id, generator in generators.items():
                source = root / f"{source_id}.mp4"
                generator(ffmpeg, source)
                out = root / f"out-{source_id}"
                with mock.patch.dict(
                    os.environ,
                    {
                        "GEMINI_API_KEY": "",
                        "CREATOR_GEMINI_VIDEO_ENABLE": "",
                    },
                    clear=False,
                ):
                    summary = mvp.run_pipeline(
                        input_path=source,
                        brief_arg="Create a source-bound benchmark short.",
                        out_dir=out,
                        source_id=source_id,
                        media_repo=str(media_repo),
                    )
                canonical = out / "creator.semantic_export.v1.json"
                self.assertTrue(canonical.is_file())
                value = json.loads(canonical.read_text(encoding="utf-8"))
                self.assertEqual(set(value), set(export.REQUIRED_KEYS))
                self.assertEqual(value["commit_sha"], creator_sha)
                self.assertEqual(value["source_id"], source_id)
                self.assertEqual(
                    value["source_sha256"],
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    value["brief_digest"],
                    reels.sha256_text(
                        "Create a source-bound benchmark short."
                    ),
                )
                self.assertEqual(
                    value["analysis_digest"],
                    summary["semanticDirector"]["analysisDigest"],
                )
                self.assertEqual(
                    value["directives_digest"],
                    summary["semanticDirector"]["editorialDirectivesDigest"],
                )
                self.assertEqual(
                    value["generation_mode"],
                    "deterministic_local_fallback",
                )
                validated = export.validate_semantic_export(
                    value,
                    expected_commit_sha=creator_sha,
                    expected_source_sha256=summary["input"]["sha256"],
                    expected_brief_digest=value["brief_digest"],
                    expected_analysis_digest=value["analysis_digest"],
                    expected_directives_digest=value["directives_digest"],
                    source_duration_ms=summary["input"]["durationMs"],
                )
                self.assertEqual(validated["repository"], "foto6/video1")
                self.assertIn(
                    "semanticExport",
                    summary["outputs"],
                )
                self.assertFalse(
                    "human_ground_truth" in json.dumps(value).lower()
                )


if __name__ == "__main__":
    unittest.main()
