import { compareUpdateVersions } from "./update-version";

export const FORK_RELEASES_URL = "https://api.github.com/repos/zzyyaa916/Agents-Anywhere/releases?per_page=20";
const downloadPrefix = "https://github.com/zzyyaa916/Agents-Anywhere/releases/download/";
export type ForkDesktopRelease = { version: string; url: string; sha256: string; size: number };

export function selectForkDesktopRelease(payload: unknown, platform: string): ForkDesktopRelease | null {
  if (!Array.isArray(payload)) throw new Error("Invalid release list.");
  let latest: ForkDesktopRelease | null = null;
  for (const release of payload) {
    if (!release || release.draft || release.prerelease || typeof release.tag_name !== "string") continue;
    const match = /^v(\d+\.\d+\.\d+)-fork$/.exec(release.tag_name);
    if (!match || !Array.isArray(release.assets)) continue;
    const version = match[1];
    const name = platform === "win32" ? `Agents.Anywhere.Fork.Setup.${version}.exe`
      : platform === "darwin" ? `Agents.Anywhere.Fork-${version}-x64.pkg` : null;
    const asset = release.assets.find((a: Record<string, unknown> | null) => a?.name === name);
    if (!name || !asset || asset.browser_download_url !== `${downloadPrefix}${release.tag_name}/${name}`
      || !/^sha256:[a-f0-9]{64}$/.test(asset.digest ?? "") || !Number.isSafeInteger(asset.size) || asset.size <= 0) continue;
    if (!latest || (compareUpdateVersions(version, latest.version) ?? 0) > 0) {
      latest = { version, url: asset.browser_download_url, sha256: asset.digest.slice(7), size: asset.size };
    }
  }
  return latest;
}
