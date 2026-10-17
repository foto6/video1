import { existsSync } from "node:fs";
import path from "node:path";

// Some Windows FFmpeg builds crash in fontconfig without an explicit font.
export function withWindowsFont(command, platform = process.platform, fontPath = null) {
  if (platform !== "win32" || !/ffmpeg(?:\.exe)?$/i.test(command.binary)) return command;
  const font = fontPath ?? path.join(process.env.WINDIR ?? "C:\\Windows", "Fonts", "arial.ttf");
  if (!existsSync(font)) throw new Error(`Windows rendering font is missing: ${font}`);
  const escaped = font.replaceAll("\\", "/").replaceAll(":", "\\:").replaceAll("'", "'\\''");
  const args = [...command.args];
  for (let i = 1; i < args.length; i++) {
    if (["-vf", "-filter:v", "-filter_complex"].includes(args[i - 1])) {
      args[i] = args[i].replace(/drawtext=(?!fontfile=)/g, `drawtext=fontfile='${escaped}':`);
    }
  }
  return { ...command, args };
}

export function configureWindowsFonts(executor) {
  const run = executor.run.bind(executor);
  executor.run = (command, options) => run(withWindowsFont(command), options);
  return executor;
}
