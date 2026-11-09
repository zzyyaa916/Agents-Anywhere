import fs from "node:fs";
import path from "node:path";

export function nativeLoginLaunchers(directory: string, platform = process.platform): Record<"codex" | "claude", string> {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const windows = platform === "win32";
  const python = path.join(directory, ".venv", windows ? "Scripts" : "bin", windows ? "python.exe" : "python");
  const result = {} as Record<"codex" | "claude", string>;
  for (const runtime of ["codex", "claude"] as const) {
    const file = path.join(directory, `Login ${runtime === "codex" ? "Codex" : "Claude Code"}.${windows ? "cmd" : "command"}`);
    const quoted = windows ? `"${python.replaceAll("%", "%%")}"` : `'${python.replaceAll("'", "'\\''")}'`;
    const command = `${quoted} -m connector.cli fork-login ${runtime}`;
    fs.writeFileSync(file, windows ? `@echo off\r\n${command}\r\npause\r\n` : `#!/bin/sh\nexec ${command}\n`, { mode: 0o700 });
    result[runtime] = file;
  }
  return result;
}
