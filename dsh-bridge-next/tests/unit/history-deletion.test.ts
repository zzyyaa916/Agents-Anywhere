import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, access, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { deleteNativeHistory } from '../../src/host/dsh-runtime/history-deletion.js'

// The real JSONL backend returns undefined for missing sessions in 0.2.2.
class JsonlSessionPersistence {
  closes = 0
  constructor(readonly root: string) {}
  async stat(id: string) {
    try { await access(join(this.root, 'project', id)); return { header: { id } } }
    catch { return undefined }
  }
  async open(_id: string, _access: 'write') { return { close: async () => { this.closes++ } } }
}
test('cold native deletion preserves other sessions, takes a writer lease and is repeatable', async () => {
  const root = await mkdtemp(join(tmpdir(), 'aa-history-'))
  try {
    for (const id of ['selected', 'other']) {
      await mkdir(join(root, 'project', id), { recursive: true })
      await writeFile(join(root, 'project', id, 'events.jsonl'), '{}')
    }
    const backend = new JsonlSessionPersistence(root)
    await deleteNativeHistory(backend, 'selected', false, false)
    await access(join(root, 'project', 'selected'))
    await deleteNativeHistory(backend, 'selected', false, true)
    await assert.rejects(access(join(root, 'project', 'selected')))
    await access(join(root, 'project', 'other'))
    assert.equal(backend.closes, 1)
    await deleteNativeHistory(backend, 'selected', false, true)
    await assert.rejects(deleteNativeHistory(backend, 'other', true, true))
    await assert.rejects(deleteNativeHistory(backend, '../other', false, true))
    await assert.rejects(deleteNativeHistory({ root }, 'other', false, true))
    await access(join(root, 'project', 'other'))
  } finally { await rm(root, { recursive: true, force: true }) }
})
