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
let quota = { state: 'limited', resetsAt: null }
globalThis.quotaRequest = async (method, path) => { calls.push([method, path]); return { quotaLimit: quota } }
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
  await act(async () => root.render(h(SessionQuotaNotice, {token:'synthetic-app-token',sessionId:'original'})))
  assert.match(container.textContent, /恢复时间未知/)
  assert.deepEqual(calls, [['GET','/sessions/original/quota']])
  quota = { state:'ready', resetsAt:'2030-01-01T00:00:00Z' }
  await act(async () => container.querySelector('button').click())
  assert.deepEqual(calls.at(-1), ['POST','/sessions/original/quota/recheck'])
  assert.match(container.textContent, /可以在原会话继续/)
  assert.equal(container.querySelector('button'), null)
  assert.ok(calls.every(([,path])=>!path.includes('messages') && !path.includes('create')))
  await act(async () => root.unmount()); container.remove()
})
