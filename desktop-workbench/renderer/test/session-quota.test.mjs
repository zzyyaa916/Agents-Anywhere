import assert from 'node:assert/strict'
import test from 'node:test'
import { registerHooks } from 'node:module'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://test.example/' })
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node']) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { createElement: h, act } = await import('react')
const { createRoot } = await import('react-dom/client')
const source = registerSource()
const calls = []
let interrupted = false
let quota = { state: 'limited', resetsAt: null }
globalThis.quotaRequest = async (method, path) => { calls.push([method, path]); if (path.endsWith("/runtime/interrupt")) { interrupted = true; quota = { state: "stopped", resetsAt: null }; return { ok: true } } return { quotaLimit: quota } }
const hook = registerHooks({ load(url, context, next) {
  if (url.endsWith('/components/account-usage.tsx')) return { format: 'module', shortCircuit: true, source: 'export const localTime=value=>new Date(value).toLocaleTimeString()' }
  if (url.endsWith('/lib/api/index.ts')) return { format: 'module', shortCircuit: true, source: 'export const apiClient={get:p=>globalThis.quotaRequest("GET",p),post:p=>globalThis.quotaRequest("POST",p)}' }
  return next(url, context)
}})
const { SessionQuotaNotice } = await import('../src/components/session-quota.tsx')
hook.deregister(); source.deregister()

test('unknown quota deadline can be checked on the same session and ready state invites manual continuation', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let recoveries = 0
  await act(async () => root.render(h(SessionQuotaNotice, {token:'synthetic-app-token',sessionId:'original',onReady:()=>recoveries++})))
  assert.match(container.textContent, /恢复时间未知/)
  assert.deepEqual(calls, [['GET','/sessions/original/quota']])
  quota = { state:'ready', resetsAt:'2030-01-01T00:00:00Z' }
  await act(async () => container.querySelector('button').click())
  assert.deepEqual(calls.at(-1), ['POST','/sessions/original/quota/recheck'])
  assert.match(container.textContent, /可以在原会话继续/)
  assert.equal(recoveries, 1)
  assert.equal(container.querySelector('button').textContent, '结束等待')
  assert.ok(calls.every(([,path])=>!path.includes('messages') && !path.includes('create')))
  await act(async () => root.unmount()); container.remove()
})


test('unknown deadline offers explicit stop and refreshes the original chat without sending a model task', async () => {
  calls.length = 0
  quota = { state: 'limited', resetsAt: null }
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let recoveries = 0
  await act(async () => root.render(h(SessionQuotaNotice, { token: 'test', sessionId: 'same/id', onReady: () => recoveries++ })))
  const stop = [...container.querySelectorAll('button')].find(button => button.textContent === '结束等待')
  assert.ok(stop)
  await act(async () => stop.click())
  assert.equal(interrupted, true)
  assert.equal(container.textContent, '')
  assert.equal(recoveries, 1)
  assert.deepEqual(calls, [['GET', '/sessions/same%2Fid/quota'], ['POST', '/sessions/same%2Fid/runtime/interrupt'], ['GET', '/sessions/same%2Fid/quota']])
  await act(async () => root.unmount()); container.remove()
})

test('first ready snapshot also refreshes capabilities; identical polling does not refresh repeatedly', async () => {
  quota = { state: 'ready', resetsAt: null }
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let recoveries = 0
  await act(async () => root.render(h(SessionQuotaNotice, { token: 'test', sessionId: 'already-ready', onReady: () => recoveries++ })))
  assert.equal(recoveries, 1)
  await act(async () => root.render(h(SessionQuotaNotice, { token: 'test', sessionId: 'already-ready', onReady: () => recoveries++ })))
  assert.equal(recoveries, 1)
  await act(async () => root.unmount()); container.remove()
})


test('deadline polling refreshes send capabilities once when waiting becomes ready', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] })
  quota = { state: 'limited', resetsAt: '2030-01-01T00:00:00Z' }
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let recoveries = 0
  await act(async () => root.render(h(SessionQuotaNotice, { token: 'test', sessionId: 'timer', onReady: () => recoveries++ })))
  assert.equal(recoveries, 0)
  quota = { state: 'ready', resetsAt: '2030-01-01T00:00:00Z' }
  await act(async () => t.mock.timers.tick(15_000))
  assert.equal(recoveries, 1)
  quota = { ...quota }
  await act(async () => t.mock.timers.tick(15_000))
  assert.equal(recoveries, 1)
  await act(async () => root.unmount()); container.remove()
})


test('ready quota keeps the escape action when the original runtime identity is unavailable', async () => {
  calls.length = 0
  quota = { state: 'ready', resetsAt: null }
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let recoveries = 0
  await act(async () => root.render(h(SessionQuotaNotice, { token: 'test', sessionId: 'missing-native-id', onReady: () => recoveries++ })))
  const stop = container.querySelector('button')
  assert.equal(stop.textContent, '结束等待')
  await act(async () => stop.click())
  assert.equal(container.textContent, '')
  assert.equal(recoveries, 2)
  assert.ok(calls.some(([method, path]) => method === 'POST' && path === '/sessions/missing-native-id/runtime/interrupt'))
  await act(async () => root.unmount()); container.remove()
})
