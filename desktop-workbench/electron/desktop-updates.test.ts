import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { DesktopUpdateService } from "./desktop-updates";
import { FORK_RELEASES_URL, selectForkDesktopRelease } from "./fork-release";

const server = { serverUrl: "https://server.test", apiNamespace: "/api/v2", oauthWebOrigin: "https://server.test" };
const digest = createHash("sha256").update("installer").digest("hex");
function releases(version = "2.5.7") {
  return [{ tag_name: `v${version}-fork`, assets: ["exe", "pkg"].map(ext => {
    const name = ext === "exe" ? `Agents.Anywhere.Fork.Setup.${version}.exe` : `Agents.Anywhere.Fork-${version}-x64.pkg`;
    return {name, browser_download_url: `https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v${version}-fork/${name}`, digest: `sha256:${digest}`, size: 9};
  }) }];
}
function harness(t: TestContext, patch: Partial<ConstructorParameters<typeof DesktopUpdateService>[0]> = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "aa-update-"));
  const opened: string[] = [];
  const requests: {url: string; init?: RequestInit}[] = [];
  const options: ConstructorParameters<typeof DesktopUpdateService>[0] = {
    directory, currentVersion: "2.5.6", platform: "darwin",
    fetcher: async (url, init) => {
      requests.push({url:String(url),init});
      return String(url) === FORK_RELEASES_URL ? Response.json(releases()) : new Response("installer", {headers:{"content-type":"application/octet-stream","content-length":"9"}});
    },
    openInstaller: async file => {opened.push(file);}, onState: () => {}, ...patch,
  };
  const services: DesktopUpdateService[] = [];
  const make = () => {const service = new DesktopUpdateService(options);services.push(service);return service;};
  t.after(() => {services.forEach(s=>s.dispose());fs.rmSync(directory,{recursive:true,force:true});});
  return {service:make(),make,opened,requests,directory};
}

test("release selection only offers stable Fork installers with platform, size, checksum and exact repository URL", () => {
  for (const patch of [{draft:true},{prerelease:true},{tag_name:"v9.0.0-official"}]) {
    assert.equal(selectForkDesktopRelease([{...releases()[0],...patch}],"win32"),null);
  }
  for (const patch of [{digest:null},{size:0},{browser_download_url:"https://evil.example/setup.exe"},{name:"official.exe"}]) {
    const r = releases()[0];
    assert.equal(selectForkDesktopRelease([{...r,assets:[{...r.assets[0],...patch}]}],"win32"),null);
  }
  assert.equal(selectForkDesktopRelease([...releases("2.5.9"),...releases("2.5.7")],"darwin")?.version,"2.5.9");
  assert.equal(selectForkDesktopRelease(releases(),"linux"),null);
});

test("checks installed Desktop version against public releases without contacting or sending credentials to Server", async t => {
  const h=harness(t);const state=await h.service.check(server);
  assert.equal(state.available,true);assert.equal(state.dialogOpen,true);
  assert.equal(h.requests[0].url,FORK_RELEASES_URL);assert.equal(h.requests[0].init?.credentials,"omit");
  assert.equal(h.requests[0].init?.headers && "authorization" in h.requests[0].init.headers,false);
  const current=harness(t,{currentVersion:"2.5.7"});assert.equal((await current.service.check(server)).available,false);
});

test("ignore survives restart, newer releases prompt, and manual entry can reopen an ignored version",async t=>{
  const h=harness(t);await h.service.check(server);h.service.ignoreVersion();
  assert.equal((await h.make().check(server)).ignored,true);
  assert.equal(h.service.showPrompt().dialogOpen,true);
  assert.equal((await h.service.check({...server,serverUrl:"https://other.test"})).dialogOpen,true);
});

test("both platforms download verified complete installers once and publish accurate progress",async t=>{
  for (const platform of ["win32","darwin"]) {
    const h=harness(t,{platform});await h.service.check(server);
    const first=h.service.download();assert.equal(h.service.download(),first);
    const state=await first;assert.equal(state.phase,"downloaded");assert.equal(state.available,true);
    assert.equal(state.downloadedBytes,9);assert.equal(state.totalBytes,9);assert.equal(h.opened.length,1);
    assert.equal(path.extname(h.opened[0]),platform==="win32"?".exe":".pkg");
    assert.equal(fs.readFileSync(h.opened[0],"utf8"),"installer");
  }
});

test("corrupt, oversized, incomplete and HTML downloads are removed and never installed",async t=>{
  for (const response of [()=>new Response(Buffer.from("tampered!")),()=>new Response(Buffer.from("installer+extra")),()=>new Response(Buffer.from("short")),()=>new Response("<html>",{headers:{"content-type":"text/html"}})]) {
    const h=harness(t,{fetcher:async url=>String(url)===FORK_RELEASES_URL?Response.json(releases()):response()});
    await h.service.check(server);assert.equal((await h.service.download()).error,"downloadFailed");
    assert.equal(h.opened.length,0);assert.deepEqual(fs.existsSync(path.join(h.directory,"downloads")) ? fs.readdirSync(path.join(h.directory,"downloads")) : [],[]);
  }
});

test("failed installer opening retries the already verified download",async t=>{
  let attempts=0;const h=harness(t,{openInstaller:async()=>{if(++attempts===1)throw Error("blocked");}});
  await h.service.check(server);assert.equal((await h.service.download()).error,"openFailed");
  assert.equal((await h.service.download()).phase,"downloaded");assert.equal(h.requests.length,2);
});

test("logout and server changes discard late release responses",async t=>{
  let finish!: (r:Response)=>void;let signal:AbortSignal|null|undefined;
  const h=harness(t,{fetcher:async(_url,init)=>{signal=init?.signal;return new Promise(resolve=>{finish=resolve;});}});
  const pending=h.service.check(server);await h.service.check(null);assert.equal(signal?.aborted,true);
  finish(Response.json(releases()));await pending;assert.equal(h.service.getState().available,false);
});

test("release timeout cancels stalled bodies; invalid responses fail without prompting",async t=>{
  const h=harness(t,{healthTimeoutMs:10,fetcher:async()=>new Response(new ReadableStream())});
  assert.equal((await h.service.check(server)).error,"checkFailed");
  for (const payload of [{version:"99"},null,{}]) {
    const h=harness(t,{fetcher:async()=>Response.json(payload)});
    const state=await h.service.check(server);assert.equal(state.error,"checkFailed");assert.equal(state.dialogOpen,false);
  }
});

test("logout cancels downloads, removes partial files and never launches installation",async t=>{
  let started!:()=>void;const ready=new Promise<void>(resolve=>{started=resolve;});
  const h=harness(t,{fetcher:async url=>String(url)===FORK_RELEASES_URL?Response.json(releases()):new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1]));}})),onState:s=>{if(s.downloadedBytes)started();}});
  await h.service.check(server);const download=h.service.download();await ready;await h.service.check(null);await download;
  assert.equal(h.opened.length,0);assert.deepEqual(fs.existsSync(path.join(h.directory,"downloads")) ? fs.readdirSync(path.join(h.directory,"downloads")) : [],[]);
});
