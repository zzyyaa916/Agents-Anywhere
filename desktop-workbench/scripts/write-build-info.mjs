/** Record Server compatibility metadata; Fork client updates use published client versions. */
import { readFileSync, writeFileSync } from "node:fs";

const pyproject = readFileSync(new URL("../../server/pyproject.toml", import.meta.url), "utf8");
const project = /^\[project\]\s*$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(pyproject)?.[1] ?? "";
const serverVersion = /^version\s*=\s*"([^"]+)"\s*$/m.exec(project)?.[1];
if (!serverVersion) throw new Error("server/pyproject.toml has no [project] version.");

writeFileSync(new URL("../build-info.json", import.meta.url), `${JSON.stringify({ serverVersion }, null, 2)}\n`);
