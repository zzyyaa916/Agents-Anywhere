/** Native JSONL hard deletion. Never dispose another consumer's live Agent. */
import { lstat, readdir, realpath, rm } from 'node:fs/promises'
import { isAbsolute, join, resolve } from 'node:path'
import { BridgeError } from './errors.js'

type Persistence = {
  root: string
  stat(id: string): Promise<{ header: { id: string } } | undefined>
  open(id: string, access: 'write'): Promise<{ close(): Promise<void> }>
}
const missing = (error: unknown) => (error as Error)?.constructor?.name === 'SessionPersistenceNotFoundError'

export async function deleteNativeHistory(storage: unknown, id: string, attached: boolean, commit: boolean): Promise<void> {
  if (!/^[A-Za-z0-9_-]+$/.test(id)) throw new BridgeError('INVALID_PARAMS', 'Invalid native session identity.')
  if (attached) throw new BridgeError('UNSUPPORTED_OPERATION', 'Close the native DSH session before deleting its history.')
  const persistence = storage as Persistence | undefined
  if (!persistence || persistence.constructor.name !== 'JsonlSessionPersistence' || typeof persistence.root !== 'string' || !isAbsolute(persistence.root)
    || typeof persistence.stat !== 'function' || typeof persistence.open !== 'function') {
    throw new BridgeError('UNSUPPORTED_OPERATION', 'This persistence backend cannot safely erase native files.')
  }
  const root = resolve(persistence.root)
  if (await realpath(root) !== root) throw new BridgeError('INVALID_PARAMS', 'Native history symlinks cannot be deleted.')
  let exists = true
  try { const metadata = await persistence.stat(id); exists = metadata !== undefined; if (metadata && metadata.header.id !== id) throw new Error('Native identity mismatch') }
  catch (error) { if (!missing(error)) throw error; exists = false }
  const targets: string[] = []
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) throw new BridgeError('INVALID_PARAMS', 'Native history symlinks cannot be deleted.')
    if (!entry.isDirectory()) continue
    const target = join(root, entry.name, id)
    try {
      const meta = await lstat(target)
      if (!meta.isDirectory() || meta.isSymbolicLink() || await realpath(target) !== target) {
        throw new BridgeError('INVALID_PARAMS', 'Invalid native session directory.')
      }
      targets.push(target)
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
  }
  if (exists && targets.length !== 1) throw new BridgeError('INVALID_PARAMS', 'Native session storage is ambiguous.')
  if (!commit) return
  // The backend's writer lease prevents a different process from opening this session during deletion.
  const handle = exists ? await persistence.open(id, 'write') : undefined
  try { for (const target of targets) await rm(target, { recursive: true, force: false }) }
  finally { await handle?.close() }
  try { if (await persistence.stat(id) === undefined) return }
  catch (error) { if (missing(error)) return; throw error }
  throw new BridgeError('INTERNAL_ERROR', 'Native history deletion did not complete.')
}
