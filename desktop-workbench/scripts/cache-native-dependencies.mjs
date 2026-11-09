// Use GitHub's asset API when its browser release-download route times out.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { UV_VERSION, run } from "./prepare-uv.mjs";
import { PYTHON_VERSION, PBS_RELEASE } from "./prepare-python.mjs";

const targets = {
  win: [{ uv: "x86_64-pc-windows-msvc.zip", python: "x86_64-pc-windows-msvc", electron: "win32-x64" }],
  mac: [
    { uv: "aarch64-apple-darwin.tar.gz", python: "aarch64-apple-darwin", electron: "darwin-arm64" },
    { uv: "x86_64-apple-darwin.tar.gz", python: "x86_64-apple-darwin", electron: "darwin-x64" },
  ],
}[process.argv[2]];
assert(targets, "Expected win or mac packaging target");
const electronVersion = createRequire(import.meta.url)("electron/package.json").version;
const uvCache = join(".cache", "uv", UV_VERSION);
const pythonCache = join(".cache", "python", `${PYTHON_VERSION}+${PBS_RELEASE}`);
const electronCache = join(".cache", "electron");

async function asset(repo, tag, name, directory) {
  await mkdir(directory, { recursive: true });
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await run("gh", ["release", "download", tag, "--repo", repo, "--pattern", name, "--dir", directory, "--skip-existing"]);
      return;
    } catch (error) {
      if (attempt === 3) throw error;
      await new Promise(resolve => setTimeout(resolve, attempt * 1000));
    }
  }
}

await asset("astral-sh/python-build-standalone", PBS_RELEASE, "SHA256SUMS", pythonCache);
await asset("electron/electron", `v${electronVersion}`, "SHASUMS256.txt", electronCache);
const electronSums = await readFile(join(electronCache, "SHASUMS256.txt"), "utf8");
for (const target of targets) {
  await asset("astral-sh/uv", UV_VERSION, `uv-${target.uv}`, uvCache);
  await asset("astral-sh/uv", UV_VERSION, `uv-${target.uv}.sha256`, uvCache);
  await asset("astral-sh/python-build-standalone", PBS_RELEASE, `cpython-${PYTHON_VERSION}+${PBS_RELEASE}-${target.python}-install_only_stripped.tar.gz`, pythonCache);
  const electronFile = `electron-v${electronVersion}-${target.electron}.zip`;
  await asset("electron/electron", `v${electronVersion}`, electronFile, electronCache);
  const sum = electronSums.split(/\r?\n/).map(line => line.trim().split(/\s+/)).find(([, name]) => name?.replace(/^\*/, "") === electronFile);
  assert(sum && /^[a-f0-9]{64}$/i.test(sum[0]), `Missing Electron checksum: ${electronFile}`);
  const actual = createHash("sha256").update(await readFile(join(electronCache, electronFile))).digest("hex");
  assert.equal(actual, sum[0].toLowerCase(), `Electron checksum mismatch: ${electronFile}`);
}
// uv and Python retain their original checksum validation in the packaging scripts.
const licenseDirectory = join("build", "uv", "THIRD_PARTY_LICENSES", "uv");
await mkdir(licenseDirectory, { recursive: true });
for (const name of ["LICENSE-MIT", "LICENSE-APACHE"]) {
  const response = spawnSync("gh", ["api", `repos/astral-sh/uv/contents/${name}?ref=${UV_VERSION}`], { encoding: "utf8" });
  assert.equal(response.status, 0, "Cannot download uv license from GitHub API");
  const record = JSON.parse(response.stdout);
  assert.equal(record.encoding, "base64");
  await writeFile(join(licenseDirectory, name), Buffer.from(record.content, "base64"));
}
console.log("Official native assets cached; Electron hashes verified.");

// Seed the stock builder's documented archive cache; it verifies its pinned hashes.
const { getCacheDirectory } = createRequire(import.meta.url)("app-builder-lib/out/util/electronGet");
const builderCache = getCacheDirectory({ allowEnvVarOverride: true });
const toolsets = process.argv[2] === "win" ? [
  ["7zip@1.0.0", "7zip-win-x64.tar.gz"],
  ["winCodeSign-2.6.0", "winCodeSign-2.6.0.7z"],
  ["nsis-3.0.4.1", "nsis-3.0.4.1.7z"],
  ["nsis-resources-3.4.1", "nsis-resources-3.4.1.7z"],
] : [
  ["7zip@1.0.0", `7zip-darwin-${process.arch === "arm64" ? "arm64" : "x86_64"}.tar.gz`],
  ["dmg-builder@1.2.5", `dmgbuild-bundle-${process.arch === "arm64" ? "arm64" : "x86_64"}-75c8a6c.tar.gz`],
];
for (const [tag, name] of toolsets) {
  await asset("electron-userland/electron-builder-binaries", tag, name, join(builderCache, tag));
}
console.log("Official packaging toolsets cached for local integrity validation.");
