import assert from 'node:assert/strict'
import test from 'node:test'
import { access, mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { SessionId } from '@deepseek-ai/dsh-session'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import * as JsonlPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import SqliteQuery from '@deepseek-ai/dsh-session-query-sqlite'
import Storage from '@deepseek-ai/dsh-storage'
import * as StorageJson from '@deepseek-ai/dsh-storage-json'
import * as StorageDomain from '@deepseek-ai/dsh-storage-domain'
import WorkspaceRegistry from '@deepseek-ai/dsh-workspace'
import { bridgePath, nativeRuntime, useHome } from '../fixtures/native-runtime.js'
import { NativeRuntime } from '../../src/host/dsh-runtime/native.js'

async function sessionDirs(home: string, id: string): Promise<string[]> {
  const root = join(home, 'native-sessions')
  const found: string[] = []
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    try { await access(join(root, entry.name, id)); found.push(join(root, entry.name, id)) } catch { /* absent */ }
  }
  return found
}

test('a session DSH still holds is hidden at once and erased on the next start', { timeout: 40_000 }, async () => {
  const home = await mkdtemp(join(tmpdir(), 'aa-dsh-deferred-'))
  const fixture = await nativeRuntime(home)
  const native = fixture.ctx.agentsAnywhereRuntime.native
  try {
    const live = SessionId('deferred-live')
    const session = fixture.ctx.sessions.create(live, { meta: { cwd: home } })
    session.append('user/message', createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'hi' }] }), { surfaceOp: 'append' })
    await fixture.ctx.sessions.flush(session)
    assert.ok(fixture.ctx.sessions.get(live), 'fixture session must be loaded in DSH')
    assert.equal((await sessionDirs(home, live)).length, 1)
    assert.ok((await native.inventory()).some(entry => entry.header.id === live))

    await native.deleteHistory(live, false)
    await native.deleteHistory(live, true)

    // Accepted, hidden and refused immediately; files stay while DSH holds the session.
    assert.ok(!(await native.inventory()).some(entry => entry.header.id === live))
    assert.equal(await native.visible(live), false)
    await assert.rejects(native.send(live, 'hello', 'after-delete'), /deleted/)
    assert.equal((await sessionDirs(home, live)).length, 1)
    const pending = JSON.parse(await readFile(bridgePath(home, 'pending-deletions.json'), 'utf8')) as { sessions: string[] }
    assert.deepEqual(pending.sessions, ['deferred-live'])
    // Repeating the deletion is idempotent.
    await native.deleteHistory(live, true)

    // A loaded session is never erased underneath DSH.
    await native.purgePendingDeletions()
    assert.equal((await sessionDirs(home, live)).length, 1)

    // Next start: DSH is restarted and nothing has loaded the session yet.
    await fixture.ctx.fiber.dispose()
    const ctx = new Context()
    ctx.effect(() => useHome(home))
    try {
      await ctx.plugin(SessionStore).await()
      await ctx.plugin(Reflect.get(JsonlPersistence, 'default') ?? JsonlPersistence, { root: join(home, 'native-sessions'), compression: 'none' }).await()
      await ctx.plugin(SqliteQuery, { path: ':memory:', openAt: 'never' }).await()
      await ctx.plugin(Storage).await()
      await ctx.plugin(StorageJson, { root: join(home, 'storage') }).await()
      await ctx.plugin(StorageDomain, { backend: 'json' }).await()
      await ctx.plugin(WorkspaceRegistry).await()
      const restarted = new NativeRuntime(ctx, bridgePath(home, 'create-intents'))
      await restarted.purgePendingDeletions()
      assert.equal((await sessionDirs(home, live)).length, 0)
      assert.equal(restarted.source.pendingDeletion.size, 0)
      const after = JSON.parse(await readFile(bridgePath(home, 'pending-deletions.json'), 'utf8')) as { sessions: string[] }
      assert.deepEqual(after.sessions, [])
      assert.equal((await sessionDirs(home, 'persisted-only')).length, 1, 'other sessions are untouched')
      await restarted.close()
    } finally { await ctx.fiber.dispose() }
  } finally { await fixture.ctx.fiber.dispose(); await rm(home, { recursive: true, force: true }) }
})

test('a cold session is still erased immediately', { timeout: 40_000 }, async () => {
  const home = await mkdtemp(join(tmpdir(), 'aa-dsh-cold-delete-'))
  const fixture = await nativeRuntime(home)
  const native = fixture.ctx.agentsAnywhereRuntime.native
  try {
    const cold = SessionId('persisted-only')
    assert.equal(fixture.ctx.sessions.get(cold), undefined)
    assert.equal((await sessionDirs(home, cold)).length, 1)
    await native.deleteHistory(cold, false)
    await native.deleteHistory(cold, true)
    assert.equal((await sessionDirs(home, cold)).length, 0)
    assert.equal(native.source.pendingDeletion.size, 0)
  } finally { await fixture.ctx.fiber.dispose(); await rm(home, { recursive: true, force: true }) }
})

test('the Bridge publishes an activity heartbeat for scheduled restarts', { timeout: 40_000 }, async () => {
  const home = await mkdtemp(join(tmpdir(), 'aa-dsh-activity-'))
  const fixture = await nativeRuntime(home)
  const native = fixture.ctx.agentsAnywhereRuntime.native
  try {
    native.publishActivity()
    await native.close()
    const activity = JSON.parse(await readFile(bridgePath(home, 'activity.json'), 'utf8')) as { version: number, pid: number, updatedAt: string, running: string[] }
    assert.equal(activity.version, 1)
    assert.equal(activity.pid, process.pid)
    assert.ok(Date.now() - Date.parse(activity.updatedAt) < 10_000)
    assert.deepEqual(activity.running, [])
  } finally { await fixture.ctx.fiber.dispose(); await rm(home, { recursive: true, force: true }) }
})
