import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Readable, Transform, type TransformCallback } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ReadableStream as WebReadableStream } from "node:stream/web";

/**
 * Save-as downloads streamed straight to disk by Main.
 *
 * The renderer only names the file and supplies the prepared transfer URL; the
 * destination comes from the save dialog and is remembered here, so a renderer
 * can never choose an arbitrary write path. Bytes go through a `.part` file next
 * to the destination and replace it only after the whole transfer arrived, so a
 * cancelled or failed download leaves nothing behind. Transfer tokens stay in
 * memory and are never logged.
 */

export type DownloadProgress = { id: string; received: number; total: number | null };

export type DownloadFailureCode = "expired" | "http" | "canceled" | "incomplete" | "failed" | "invalid";

export type DownloadResult =
  | { ok: true; fileName: string; bytes: number }
  | { ok: false; code: DownloadFailureCode; message: string; status?: number };

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;

export type StreamingDownloadsOptions = {
  fetcher: Fetcher;
  /** Origin of the configured Server; only its URLs are fetched. */
  serverOrigin: () => string;
  onProgress: (progress: DownloadProgress) => void;
  progressIntervalMs?: number;
  now?: () => number;
};

export class StreamingDownloads {
  private readonly targets = new Map<string, string>();
  private readonly active = new Map<string, AbortController>();
  private readonly completed = new Map<string, string>();

  constructor(private readonly options: StreamingDownloadsOptions) {}

  /** Remember a destination chosen in the save dialog; returns its download id. */
  register(filePath: string): string {
    const id = randomUUID();
    this.targets.set(id, path.resolve(filePath));
    return id;
  }

  /** Abort an active transfer, or forget a destination that has not started. */
  cancel(id: string): boolean {
    const controller = this.active.get(id);
    if (controller) {
      controller.abort();
      return true;
    }
    return this.targets.delete(id);
  }

  completedPath(id: string): string | null {
    return this.completed.get(id) ?? null;
  }

  async start(
    id: string,
    input: { url: string; authToken?: string | null; size?: number | null },
  ): Promise<DownloadResult> {
    const filePath = this.targets.get(id);
    if (!filePath) return failure("invalid", "This download is no longer available.");
    if (this.active.has(id)) return failure("invalid", "This download is already running.");
    let url: string;
    try {
      url = this.serverUrl(input.url);
    } catch (error) {
      this.targets.delete(id);
      return failure("invalid", errorMessage(error));
    }

    const controller = new AbortController();
    this.active.set(id, controller);
    const partPath = `${filePath}.${id.slice(0, 8)}.part`;
    let received = 0;
    let createdPart = false;
    try {
      const headers: Record<string, string> = {};
      if (input.authToken) headers.authorization = `Bearer ${input.authToken}`;
      const response = await this.options.fetcher(url, { headers, signal: controller.signal });
      if (!response.ok) {
        await response.body?.cancel().catch(() => undefined);
        // A prepared transfer is single-use and short-lived; 404/410 means it is gone.
        const expired = response.status === 404 || response.status === 410;
        if (!expired) this.targets.delete(id);
        return failure(expired ? "expired" : "http", `HTTP ${response.status}`, response.status);
      }
      if (!response.body) {
        this.targets.delete(id);
        return failure("failed", "The download returned no data.");
      }
      const declared = Number(response.headers.get("content-length"));
      const total = validSize(input.size) ?? (Number.isSafeInteger(declared) && declared >= 0 ? declared : null);
      const interval = this.options.progressIntervalMs ?? 200;
      const now = this.options.now ?? Date.now;
      let lastEmit = -Infinity;
      const emit = (force: boolean) => {
        const time = now();
        if (!force && time - lastEmit < interval) return;
        lastEmit = time;
        this.options.onProgress({ id, received, total });
      };
      const counter = new Transform({
        transform(chunk: Buffer, _encoding: BufferEncoding, callback: TransformCallback) {
          received += chunk.length;
          emit(false);
          callback(null, chunk);
        },
      });
      emit(true);
      createdPart = true;
      // pipeline() applies backpressure end to end and destroys every stage on abort or error.
      await pipeline(
        Readable.fromWeb(response.body as unknown as WebReadableStream<Uint8Array>),
        counter,
        fs.createWriteStream(partPath, { flags: "wx", mode: 0o644 }),
        { signal: controller.signal },
      );
      if (total !== null && received !== total) {
        await removeQuietly(partPath);
        this.targets.delete(id);
        return failure("incomplete", `Received ${received} of ${total} bytes.`);
      }
      await fs.promises.rename(partPath, filePath);
      emit(true);
      this.targets.delete(id);
      this.completed.set(id, filePath);
      return { ok: true, fileName: path.basename(filePath), bytes: received };
    } catch (error) {
      if (createdPart) await removeQuietly(partPath);
      this.targets.delete(id);
      if (controller.signal.aborted) return failure("canceled", "The download was canceled.");
      return failure("failed", errorMessage(error));
    } finally {
      this.active.delete(id);
    }
  }

  private serverUrl(raw: string): string {
    const origin = new URL(this.options.serverOrigin()).origin;
    const url = new URL(String(raw ?? ""), origin);
    if (url.origin !== origin || (url.protocol !== "https:" && url.protocol !== "http:")) {
      throw new Error("Downloads are only allowed from the connected Server.");
    }
    return url.toString();
  }
}

/** Keep only a file name: drop directories and characters Windows rejects. */
export function safeDownloadName(value: unknown): string {
  const base = path.basename(String(value ?? "").replace(/\\/g, "/"))
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/, "")
    .slice(0, 200);
  return base && base !== "." && base !== ".." ? base : "download";
}

function validSize(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function failure(code: DownloadFailureCode, message: string, status?: number): DownloadResult {
  return { ok: false, code, message, ...(status === undefined ? {} : { status }) };
}

async function removeQuietly(filePath: string): Promise<void> {
  await fs.promises.rm(filePath, { force: true }).catch(() => undefined);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
