from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from creator_orchestrator import media_r13_compat as m13
from creator_orchestrator import mvp


class CreatorMvpR17Tests(unittest.TestCase):
    def test_brief_normalization_and_local_fallback_are_explicit(self):
        brief, meta = mvp.normalize_brief("  Cut   this into a clean short.  ")
        self.assertEqual(brief, "Cut this into a clean short.")
        self.assertEqual(meta["mode"], "deterministic_local_fallback")
        self.assertFalse(meta["externalAiUsed"])
        script = mvp.build_local_script(brief, duration_ms=6000)
        self.assertEqual(
            script["generationMode"],
            "deterministic_local_fallback",
        )
        self.assertFalse(script["externalAiUsed"])
        self.assertTrue(script["scriptDigest"])
        self.assertEqual(script["beats"][-1]["endMs"], 6000)

    def test_brief_file_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "brief.txt"
            path.write_text("  vertical   proof edit  ", encoding="utf-8")
            brief, meta = mvp.normalize_brief(str(path))
        self.assertEqual(brief, "vertical proof edit")
        self.assertEqual(meta["source"], "file")

    def test_missing_dependency_has_actionable_exit_code(self):
        with mock.patch("creator_orchestrator.mvp.shutil.which", return_value=None):
            with self.assertRaises(mvp.MissingDependency) as caught:
                mvp._require_tool("ffmpeg")
        self.assertEqual(
            caught.exception.exit_code,
            mvp.EXIT_MISSING_DEPENDENCY,
        )
        self.assertIn("Install ffmpeg", str(caught.exception))

    def test_media_pin_rejects_old_failed_sha(self):
        self.assertNotEqual(
            m13.OLD_FAILED_MEDIA_R12_SHA,
            m13.MEDIA_R13_PRODUCER_SHA,
        )
        self.assertEqual(
            m13.MEDIA_R13_PRODUCER_SHA,
            "ad4e0ba487a3cabc84dd339d412e19a0db0f9add",
        )

    def test_managed_cleanup_never_deletes_user_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "user-source.mp4"
            source.write_bytes(b"user-owned-source")
            out = root / "out"
            work = out / ".creator-mvp-work" / "abc"
            work.mkdir(parents=True)
            (work / ".creator-mvp-managed.json").write_text(
                json.dumps({
                    "runId": "abc",
                    "version": mvp.MVP_VERSION,
                }),
                encoding="utf-8",
            )
            (work / "partial.tmp").write_bytes(b"partial")
            mvp._safe_clean_managed_work(
                work,
                out_root=out,
                run_id="abc",
            )
            self.assertFalse(work.exists())
            self.assertEqual(source.read_bytes(), b"user-owned-source")

    def test_refuses_to_clean_unmarked_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            work = out / ".creator-mvp-work" / "abc"
            work.mkdir(parents=True)
            with self.assertRaises(mvp.MvpError):
                mvp._safe_clean_managed_work(
                    work,
                    out_root=out,
                    run_id="abc",
                )
            self.assertTrue(work.exists())

    @unittest.skipUnless(
        os.environ.get("CREATOR_MEDIA_R13_DIR"),
        "exact Media R13 checkout required for real E2E",
    )
    def test_real_generated_video_one_command_flow(self):
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        media_repo = Path(
            os.environ["CREATOR_MEDIA_R13_DIR"]
        ).resolve()
        self.assertTrue((media_repo / "src" / "index.js").is_file())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source-fixture.mp4"
            out = root / "out"
            generated = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostdin",
                    "-y",
                    "-f", "lavfi",
                    "-i", "testsrc2=s=360x640:r=30:d=6",
                    "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=48000:duration=6",
                    "-shortest",
                    "-map_metadata", "-1",
                    "-threads", "1",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    str(source),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
            self.assertEqual(
                generated.returncode,
                0,
                generated.stderr[-4000:],
            )
            source_before = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()

            command = shutil.which("creator-mvp")
            self.assertIsNotNone(
                command,
                "creator-mvp console entrypoint must be installed for E2E",
            )
            executed = subprocess.run(
                [
                    command,
                    "--input", str(source),
                    "--brief",
                    (
                        "Show the result first, keep the edit concise, "
                        "and preserve the original source evidence."
                    ),
                    "--out", str(out),
                    "--style", "clean",
                    "--media-repo", str(media_repo),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=240,
            )
            self.assertEqual(
                executed.returncode,
                mvp.EXIT_SUCCESS,
                executed.stderr[-8000:],
            )
            summary = json.loads(executed.stdout)

            final_path = out / "final.mp4"
            preview_path = out / "preview.mp4"
            qa_path = out / "qa.json"
            summary_path = out / "run-summary.json"
            for path in (
                final_path,
                preview_path,
                qa_path,
                summary_path,
            ):
                self.assertTrue(path.is_file(), str(path))
                self.assertGreater(path.stat().st_size, 0)

            probed = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-show_entries",
                    "stream=codec_type,width,height,r_frame_rate:format=duration",
                    "-of", "json",
                    str(final_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            self.assertEqual(probed.returncode, 0, probed.stderr)
            media = json.loads(probed.stdout)
            video = next(
                item
                for item in media["streams"]
                if item["codec_type"] == "video"
            )
            self.assertEqual(video["width"], 1080)
            self.assertEqual(video["height"], 1920)
            self.assertEqual(video["r_frame_rate"], "30/1")
            self.assertGreaterEqual(
                float(media["format"]["duration"]),
                5.0,
            )

            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            self.assertTrue(qa["technicalQa"]["passed"])
            self.assertTrue(qa["creativeQa"]["passed"])
            self.assertEqual(
                qa["gates"],
                {
                    "input_ok": True,
                    "media_pin_ok": True,
                    "render_ok": True,
                    "technical_qa_ok": True,
                    "creative_qa_ok": True,
                    "artifact_export_ok": True,
                },
            )
            persisted = json.loads(
                summary_path.read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["state"], "MVP_GREEN")
            self.assertEqual(
                persisted["media"]["producerSha"],
                m13.MEDIA_R13_PRODUCER_SHA,
            )
            self.assertEqual(
                persisted["media"]["contractVersion"],
                m13.MEDIA_R13_COMPAT_VERSION,
            )
            self.assertEqual(
                persisted["fallback"]["mode"],
                "deterministic_local_fallback",
            )
            self.assertFalse(persisted["publishingEnabled"])
            self.assertFalse(persisted["growthEnabled"])
            self.assertFalse(persisted["analyticsEnabled"])
            self.assertFalse(persisted["credentialsPresent"])
            self.assertEqual(
                source_before,
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                summary["outputs"]["final"]["sha256"],
                hashlib.sha256(final_path.read_bytes()).hexdigest(),
            )
            self.assertFalse((out / ".creator-mvp-work").exists())


if __name__ == "__main__":
    unittest.main()
