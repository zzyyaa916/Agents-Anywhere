import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { nativeLoginLaunchers } from "./native-login-launchers";

test("native login launchers quote paths and run without capturing account output", t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "aa-login-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const directory = path.join(root, "账户 space'百分%path");
  const windows = nativeLoginLaunchers(directory, "win32");
  const cmd = fs.readFileSync(windows.codex, "utf8");
  assert.ok(cmd.includes("百分%%path"));
  assert.ok(cmd.includes('python.exe" -m connector.cli fork-login codex'));
  assert.ok(!cmd.includes(">"));
  if (process.platform === "win32") return;
  const python = path.join(directory, ".venv/bin/python");
  fs.mkdirSync(path.dirname(python), { recursive: true });
  fs.writeFileSync(python, '#!/bin/sh\nprintf "%s\\n" "$@"\n', { mode: 0o700 });
  const mac = nativeLoginLaunchers(directory, "darwin");
  const result = spawnSync(mac.claude, [], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "-m\nconnector.cli\nfork-login\nclaude\n");
  assert.equal(fs.statSync(mac.claude).mode & 0o777, 0o700);
});
