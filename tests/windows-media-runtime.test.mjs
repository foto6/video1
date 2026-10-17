import assert from "node:assert/strict";
import test from "node:test";
import { withWindowsFont } from "../tools/windows-media-runtime.mjs";
import { execFileSync } from "node:child_process";

test("Windows FFmpeg renders Cyrillic captions with the selected host font", { skip: process.platform !== "win32" }, () => {
  const command = withWindowsFont({binary: "ffmpeg", args: ["-hide_banner", "-v", "error", "-f", "lavfi", "-i",
    "color=s=160x280:d=0.1", "-vf", "drawtext=text='Привет':fontsize=24", "-frames:v", "1", "-f", "null", "-"]});
  execFileSync(command.binary, command.args, { windowsHide: true, stdio: "pipe" });
});

test("font override leaves other commands and caller arguments intact", () => {
  const command = {binary: "ffprobe", args: ["-v", "error", "sample.mp4"]};
  assert.equal(withWindowsFont(command, "win32"), command);
  const video = {binary: "ffmpeg", args: ["-vf", "drawtext=text=Hello"]};
  assert.equal(withWindowsFont(video, "linux"), video);
});
