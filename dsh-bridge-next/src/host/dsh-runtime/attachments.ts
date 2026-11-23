import { constants } from 'node:fs'
import { createHash } from 'node:crypto'
import { lstat, mkdir, open, realpath } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import type { AttachmentStore, ImageMediaType } from '@deepseek-ai/dsh-attachment'
import type { PromptContentPart } from '@deepseek-ai/dsh-api-session-controller'
import type { FileUploads } from '@deepseek-ai/dsh-client-file-upload'
import type { SessionId } from '@deepseek-ai/dsh-session'
import type { SessionEvent } from '@deepseek-ai/dsh-session'
import type { SessionLogSnapshot } from '@deepseek-ai/dsh-session-query'
import { readJson, writeJson } from '../storage/files.js'
import { canonicalJson, digest } from './identity.js'
import { BridgeError } from './errors.js'
import { record } from './types.js'

export const IMAGE_MIME_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'] as const

/**
 * Small UTF-8 text files are inlined into the prompt instead of going through DSH's file upload,
 * whose admission can stall after the stream is fully read (observed on Harness 0.2.1-rc.5).
 */
export const INLINE_TEXT_MAX_BYTES = 256 * 1024
const INLINE_TEXT_EXTENSIONS = new Set(['md', 'markdown', 'mdx', 'txt', 'text', 'log', 'csv', 'tsv', 'json', 'jsonl',
  'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'xml', 'html', 'htm', 'css', 'rst', 'adoc', 'tex'])
const INLINE_TEXT_MEDIA_TYPES = new Set(['application/json', 'application/x-ndjson', 'application/xml', 'application/yaml',
  'application/x-yaml', 'application/toml'])
/** Invisible marker that lets history keep inlined file text out of the user's message bubble. */
export const INLINE_ATTACHMENT_MARKER = '\u2063aa-attachment\u2063'
/** DSH upload is bounded so one stalled upload cannot block the session's write queue forever. */
export const FILE_UPLOAD_TIMEOUT_MS = 120_000

export function isInlineTextAttachment(item: Pick<AttachmentReference, 'name' | 'mediaType' | 'size'>): boolean {
  if (item.size > INLINE_TEXT_MAX_BYTES) return false
  const mediaType = item.mediaType.toLowerCase()
  if (mediaType.startsWith('text/') || INLINE_TEXT_MEDIA_TYPES.has(mediaType)) return true
  const dot = item.name.lastIndexOf('.')
  return dot > 0 && INLINE_TEXT_EXTENSIONS.has(item.name.slice(dot + 1).toLowerCase())
}

export function isInlinedAttachmentText(text: string): boolean { return text.startsWith(INLINE_ATTACHMENT_MARKER) }

function inlineAttachmentText(name: string, text: string): string {
  const safeName = name.replace(/[\r\n"<>]/g, '_')
  return `${INLINE_ATTACHMENT_MARKER}<attachment name="${safeName}">\n${text}\n</attachment>`
}

/** Await `operation`, failing after `ms` and aborting the operation's signal. */
async function withTimeout<T>(signal: AbortSignal, ms: number, message: string, operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController()
  const onAbort = () => controller.abort(signal.reason)
  signal.addEventListener('abort', onAbort, { once: true })
  let timer: NodeJS.Timeout | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new BridgeError('DSH_SERVICE_UNAVAILABLE', message, true)
      controller.abort(error)
      reject(error)
    }, ms)
  })
  try { return await Promise.race([operation(controller.signal), timeout]) }
  finally { clearTimeout(timer); signal.removeEventListener('abort', onAbort) }
}

/** lstat, so a symbolic link counts as present and is then refused by the staging checks. */
async function exists(path: string): Promise<boolean> {
  try { await lstat(path); return true }
  catch (error) { if (record(error).code === 'ENOENT') return false; throw error }
}
export interface AttachmentReference {
  fileId: string
  name: string
  mediaType: string
  size: number
  sha256: string
}
export interface StagedAttachment extends AttachmentReference { uploadId: string }
export interface AttachmentReceipt {
  platformId: string
  fingerprint: string
  attachments: AttachmentReference[]
}
export interface AttachmentSnapshot extends SessionLogSnapshot { bridgeRevision?: string, attachmentReceipts?: Record<string, AttachmentReceipt> }

/** The Bridge accepts opaque staging IDs, never caller-selected filesystem paths. */
export function parseAttachments(value: unknown): StagedAttachment[] {
  if (value == null) return []
  if (!Array.isArray(value)) throw new BridgeError('INVALID_PARAMS', 'Attachments must be an array.')
  const files = new Set<string>(), uploads = new Set<string>()
  return value.map(raw => {
    const item = record(raw)
    if (typeof item.mediaType !== 'string' || !/^[-\w.+]+\/[-\w.+]+$/.test(item.mediaType)) {
      throw new BridgeError('INVALID_PARAMS', 'Invalid attachment media type.')
    }
    if (typeof item.fileId !== 'string' || !/^file_[\w-]{1,128}$/.test(item.fileId) ||
        typeof item.uploadId !== 'string' || !/^[a-f0-9]{32}$/.test(item.uploadId) ||
        typeof item.name !== 'string' || !item.name || item.name.length > 1024 ||
        typeof item.size !== 'number' || !Number.isSafeInteger(item.size) || item.size < 0 ||
        typeof item.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.sha256) ||
        files.has(item.fileId) || uploads.has(item.uploadId)) {
      throw new BridgeError('INVALID_PARAMS', 'Invalid or duplicate attachment.')
    }
    files.add(item.fileId); uploads.add(item.uploadId)
    return { fileId: item.fileId, uploadId: item.uploadId, name: item.name,
      mediaType: item.mediaType as ImageMediaType, size: item.size, sha256: item.sha256 }
  })
}

export function attachmentReferences(images: readonly StagedAttachment[]): AttachmentReference[] {
  return images.map(({ uploadId: _, ...reference }) => reference)
}

export function attachmentFingerprint(text: string, images: readonly StagedAttachment[]): string {
  return digest(canonicalJson({ text, attachments: attachmentReferences(images).map(image => ({ ...image })) }))
}

export function receiptKey(event: SessionEvent): string | undefined {
  if (event.type !== 'user/message') return
  const source = record(event.data.source)
  return typeof source.rpcId === 'string' ? source.rpcId : event.data.id
}

/** AA file references survive Host restarts; DSH owns the actual attachment objects. */
export class RuntimeAttachments {
  readonly staging: string
  /**
   * `legacyStaging` is where Connectors before 2.0.3 stage uploads: next to the legacy endpoint
   * under DSH_HOME. It is only searched for upload IDs that are not in `staging`.
   */
  constructor(private readonly root: string, private readonly legacyStaging?: string) { this.staging = join(root, 'staging') }

  async initialize(): Promise<void> { await mkdir(this.staging, { recursive: true, mode: 0o700 }) }

  /** The resolved staging directory holding `uploadId`; the primary one unless only the legacy one has it. */
  private async stagingRoot(primary: string, uploadId: string): Promise<string> {
    if (!this.legacyStaging || await exists(join(primary, uploadId))) return primary
    let legacy: string
    try { legacy = await realpath(this.legacyStaging) }
    catch (error) { if (record(error).code === 'ENOENT') return primary; throw error }
    return await exists(join(legacy, uploadId)) ? legacy : primary
  }

  async readReceipts(id: string): Promise<Record<string, AttachmentReceipt>> {
    return await readJson<Record<string, AttachmentReceipt>>(join(this.root, 'receipts', `${digest(id)}.json`)) ?? {}
  }

  /** Called under NativeRuntime's per-session write queue, before official prompt admission. */
  async remember(id: string, requestId: string, receipt: AttachmentReceipt): Promise<void> {
    const receipts = await this.readReceipts(id)
    receipts[requestId] = receipt
    await writeJson(join(this.root, 'receipts', `${digest(id)}.json`), receipts)
  }

  async prepare(images: readonly StagedAttachment[], store: AttachmentStore, signal: AbortSignal,
    upload?: { service: FileUploads, sessionId: SessionId, timeoutMs?: number }): Promise<PromptContentPart[]> {
    const imageFiles = images.filter(image => IMAGE_MIME_TYPES.includes(image.mediaType as ImageMediaType))
    const uploadCount = images.filter(image => !IMAGE_MIME_TYPES.includes(image.mediaType as ImageMediaType) && !isInlineTextAttachment(image)).length
    if (uploadCount && !upload) throw new BridgeError(
      'UNSUPPORTED_OPERATION', 'File attachments require DSH 0.1.5-rc.1 or later. Update DSH and restart the plugin.')
    const limits = store.imageLimits
    if (imageFiles.length > limits.maxImagesPerMessage || imageFiles.some(image => image.size > limits.maxImageBytes) ||
        imageFiles.reduce((total, image) => total + image.size, 0) > limits.maxMessageImageBytes) {
      throw new BridgeError('INVALID_PARAMS', 'Images exceed the DSH attachment size or count limits.')
    }
    const primary = await realpath(this.staging)
    const parts: PromptContentPart[] = []
    for (const image of images) {
      signal.throwIfAborted()
      const root = await this.stagingRoot(primary, image.uploadId)
      const path = join(root, image.uploadId)
      if ((await lstat(path)).isSymbolicLink()) throw new BridgeError('INVALID_PARAMS', 'Attachment staging cannot use symbolic links.')
      // Resolve the parent as well as refusing a symlink at the file itself.
      if (dirname(await realpath(path)) !== root) throw new BridgeError('INVALID_PARAMS', 'Invalid attachment staging location.')
      const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW)
      try {
        const stat = await file.stat()
        if (!stat.isFile() || stat.size !== image.size) throw new BridgeError('INVALID_PARAMS', 'Staged attachment size does not match its upload.')
        if (IMAGE_MIME_TYPES.includes(image.mediaType as ImageMediaType)) {
          const data = await file.readFile()
          if (data.length !== image.size || createHash('sha256').update(data).digest('hex') !== image.sha256) {
            throw new BridgeError('INVALID_PARAMS', 'Staged attachment content does not match its upload.')
          }
          parts.push({ type: 'image', name: image.name, mediaType: image.mediaType as ImageMediaType, data: data.toString('base64') })
        } else if (isInlineTextAttachment(image)) {
          const data = await file.readFile()
          if (data.length !== image.size || createHash('sha256').update(data).digest('hex') !== image.sha256) {
            throw new BridgeError('INVALID_PARAMS', 'Staged attachment content does not match its upload.')
          }
          let text: string
          try { text = new TextDecoder('utf-8', { fatal: true }).decode(data) }
          catch { throw new BridgeError('INVALID_PARAMS', `Attachment ${image.name} is not valid UTF-8 text.`) }
          parts.push({ type: 'text', text: inlineAttachmentText(image.name, text) })
        } else {
          // Validate while streaming. Throw before EOF so DSH cannot commit a corrupt upload.
          const data = async function* () {
            const hash = createHash('sha256')
            let bytes = 0
            for await (const chunk of file.createReadStream({ autoClose: false, highWaterMark: 64 * 1024 })) {
              signal.throwIfAborted()
              bytes += chunk.length
              if (bytes > image.size) throw new BridgeError('INVALID_PARAMS', 'Staged attachment size does not match its upload.')
              hash.update(chunk)
              yield chunk as Buffer
            }
            signal.throwIfAborted()
            if (bytes !== image.size || hash.digest('hex') !== image.sha256) {
              throw new BridgeError('INVALID_PARAMS', 'Staged attachment content does not match its upload.')
            }
          }
          const result = await withTimeout(signal, upload!.timeoutMs ?? FILE_UPLOAD_TIMEOUT_MS,
            `DSH did not finish receiving attachment ${image.name}. Retry, or restart DSH if it keeps stalling.`,
            uploadSignal => upload!.service.uploadStream({ sessionId: upload!.sessionId, name: image.name, data: data(), signal: uploadSignal }))
          parts.push({ type: 'file', receiptId: result.receiptId })
        }
      } finally { await file.close() }
    }
    signal.throwIfAborted()
    // SessionController.prompt performs official batch admission and saveImages before enqueueing.
    return parts
  }
}
