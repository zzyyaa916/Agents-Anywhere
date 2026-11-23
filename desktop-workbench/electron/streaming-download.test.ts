import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { safeDownloadName, StreamingDownloads, type DownloadProgress } from "./streaming-download";

const SERVER = "https://server.example:9443";

/** A response body whose chunks the test releases one at a time. */
function controlledBody() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  return {
    stream,
    push: (text: string) => controller.enqueue(new TextEncoder().encode(text)),
    end: () => controller.close(),
    fail: (error: Error) => controller.error(error),
  };
}

function setup(t: test.TestContext, respond: (url: string, init: RequestInit) => Promise<Response>) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "aa-stream-download-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const progress: DownloadProgress[] = [];
  const requests: { url: string; init: RequestInit }[] = [];
  const downloads = new StreamingDownloads({
    fetcher: async (url, init) => { requests.push({ url, init }); return respond(url, init); },
    serverOrigin: () => SERVER,
    onProgress: (value) => progress.push(value),
    progressIntervalMs: 0,
  });
  const target = path.join(directory, "zulijian_A.mp4");
  return { directory, downloads, progress, requests, target };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function waitFor(check: () => boolean) {
  for (let i = 0; i < 200 && !check(); i++) await tick();
  assert.ok(check(), "condition not reached");
}

test("chunks stream to the chosen file with progress against the transfer size", async (t) => {
  const body = controlledBody();
  const { directory, downloads, progress, requests, target } = setup(t, async () => new Response(body.stream));
  const id = downloads.register(target);
  const running = downloads.start(id, { url: "/api/v2/connectors/c/fs/transfers/fsdl_1?token=secret", authToken: "user", size: 10 });

  await waitFor(() => progress.length >= 1);
  body.push("abcd");
  await waitFor(() => progress.some((p) => p.received === 4));
  body.push("efghij");
  await waitFor(() => progress.some((p) => p.received === 10));
  body.end();
  const result = await running;

  assert.deepEqual(result, { ok: true, fileName: "zulijian_A.mp4", bytes: 10 });
  assert.equal(fs.readFileSync(target, "utf8"), "abcdefghij");
  assert.deepEqual(progress.map((p) => p.received), [0, 4, 10, 10]);
  assert.ok(progress.every((p) => p.id === id && p.total === 10));
  assert.deepEqual(fs.readdirSync(directory), ["zulijian_A.mp4"]);
  assert.equal(requests[0].url, `${SERVER}/api/v2/connectors/c/fs/transfers/fsdl_1?token=secret`);
  assert.deepEqual(requests[0].init.headers, { authorization: "Bearer user" });
  assert.equal(downloads.completedPath(id), target);
});

test("cancelling mid-stream deletes the partial file and leaves no destination", async (t) => {
  const body = controlledBody();
  const { directory, downloads, progress, target } = setup(t, async (_url, init) => {
    init.signal?.addEventListener("abort", () => body.fail(new Error("aborted")));
    return new Response(body.stream);
  });
  const id = downloads.register(target);
  const running = downloads.start(id, { url: "/api/v2/x", size: 100 });
  await waitFor(() => progress.length >= 1);
  body.push("partial");
  await waitFor(() => progress.some((p) => p.received === 7));
  await waitFor(() => fs.readdirSync(directory).length === 1);

  assert.equal(downloads.cancel(id), true);
  const result = await running;

  assert.equal(result.ok, false);
  assert.equal(!result.ok && result.code, "canceled");
  assert.deepEqual(fs.readdirSync(directory), []);
});

test("a stream error deletes the partial file", async (t) => {
  const body = controlledBody();
  const { directory, downloads, progress, target } = setup(t, async () => new Response(body.stream));
  const id = downloads.register(target);
  const running = downloads.start(id, { url: "/api/v2/x", size: 100 });
  await waitFor(() => progress.length >= 1);
  body.push("half");
  await waitFor(() => progress.some((p) => p.received === 4));
  body.fail(new Error("connection reset"));
  const result = await running;

  assert.equal(result.ok, false);
  assert.equal(!result.ok && result.code, "failed");
  assert.deepEqual(fs.readdirSync(directory), []);
});

test("a short stream is reported incomplete and removed; an existing file is kept", async (t) => {
  const { directory, downloads, target } = setup(t, async () => new Response("only-part"));
  fs.writeFileSync(target, "previous");
  const id = downloads.register(target);
  const result = await downloads.start(id, { url: "/api/v2/x", size: 100 });

  assert.equal(!result.ok && result.code, "incomplete");
  assert.equal(fs.readFileSync(target, "utf8"), "previous");
  assert.deepEqual(fs.readdirSync(directory), ["zulijian_A.mp4"]);
});

test("an expired transfer can be retried with a new URL; other failures forget the target", async (t) => {
  let status = 404;
  const { downloads, target } = setup(t, async () => status === 200 ? new Response("ok") : new Response("gone", { status }));
  const id = downloads.register(target);

  const expired = await downloads.start(id, { url: "/api/v2/old" });
  assert.equal(!expired.ok && expired.code, "expired");
  assert.equal(fs.existsSync(target), false);

  status = 200;
  const retried = await downloads.start(id, { url: "/api/v2/new", size: 2 });
  assert.equal(retried.ok, true);
  assert.equal(fs.readFileSync(target, "utf8"), "ok");

  status = 500;
  const other = downloads.register(path.join(path.dirname(target), "other.bin"));
  const failed = await downloads.start(other, { url: "/api/v2/x" });
  assert.equal(!failed.ok && failed.code, "http");
  const again = await downloads.start(other, { url: "/api/v2/x" });
  assert.equal(!again.ok && again.code, "invalid");
});

test("only the connected Server is fetched and unregistered ids are refused", async (t) => {
  const { downloads, requests, target } = setup(t, async () => new Response("x"));
  const id = downloads.register(target);
  const foreign = await downloads.start(id, { url: "https://evil.example/steal" });
  assert.equal(!foreign.ok && foreign.code, "invalid");
  const unknown = await downloads.start("missing", { url: "/api/v2/x" });
  assert.equal(!unknown.ok && unknown.code, "invalid");
  assert.equal(requests.length, 0);
  assert.equal(downloads.cancel("missing"), false);
});

test("suggested names cannot carry directories or reserved characters", () => {
  assert.equal(safeDownloadName("../../etc/passwd"), "passwd");
  assert.equal(safeDownloadName("C:\\Users\\a\\clip.mp4"), "clip.mp4");
  assert.equal(safeDownloadName('bad<>:"|?*name.txt'), "bad_______name.txt");
  assert.equal(safeDownloadName(""), "download");
  assert.equal(safeDownloadName("trailing. "), "trailing");
});
