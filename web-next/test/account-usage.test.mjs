import assert from 'node:assert/strict'
import test from 'node:test'
import { registerHooks } from 'node:module'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://test.example/', pretendToBeVisual: true })
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'NodeFilter', 'MutationObserver', 'CustomEvent', 'Event', 'KeyboardEvent', 'getComputedStyle']) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { createElement: h, act } = await import('react')
const { createRoot } = await import('react-dom/client')
const source = registerSource()
let fail = false
const requests = []
const body = { snapshots: [{ runtime: 'codex', accountKey: 'a'.repeat(64), accountLabel: 'aaaaaaaa', planType: 'plus', fetchedAt: '2030-01-01T10:00:00Z', stale: false, bindings: [{ connectorId: 'device', runtimeId: 'native' }], windows: [{ kind: 'five_hour', remainingPercent: 12, resetsAt: '2030-01-01T14:30:00Z', windowDurationMins: 300 }] }], unavailable: ['claude_code'] }
globalThis.usageTestRequest = async (method, path) => { requests.push([method, path]); if (fail) throw Error('offline'); return body }
const hook = registerHooks({ load(url, context, next) {
  if (url.endsWith('/components/auth/auth-context.tsx')) return { format: 'module', shortCircuit: true, source: 'export const useAuth = () => ({session:{accessToken:"synthetic-app-session"}})' }
  if (url.endsWith('/lib/api/index.ts')) return { format: 'module', shortCircuit: true, source: 'export const apiClient={get:p=>globalThis.usageTestRequest("GET",p),post:p=>globalThis.usageTestRequest("POST",p)}' }
  return next(url, context)
}})
const { AccountUsageProvider, AccountUsagePanel, SessionUsageNotice } = await import('../src/components/account-usage.tsx')
hook.deregister(); source.deregister()

test('usage stays collapsed until clicked, supports Escape, and retains cached values offline', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  await act(async () => {
    root.render(h(AccountUsageProvider, {}, h(AccountUsagePanel), h(SessionUsageNotice, { connectorId: 'device', runtimeId: 'native' }), h(SessionUsageNotice, { connectorId: 'other-device', runtimeId: 'native' })))
  })
  assert.deepEqual(requests, [['GET', '/account-usage']])
  assert.equal(document.querySelector('[role="dialog"]'), null)
  assert.doesNotMatch(container.textContent, /Claude Code · 用量不可用/)
  const trigger = container.querySelector('button[aria-label="查看账号用量"]')
  assert.equal(trigger.getAttribute('aria-expanded'), 'false')
  await act(async () => trigger.click())
  assert.deepEqual(requests, [['GET', '/account-usage']])
  const details = document.querySelector('[role="dialog"]')
  assert.match(details.textContent, /剩余 12%/)
  assert.match(details.textContent, /Claude Code · 用量不可用/)
  assert.equal(container.querySelectorAll('[role="status"]').length, 1)
  assert.equal(details.querySelector('progress').value, 12)
  fail = true
  await act(async () => details.querySelector('button').click())
  assert.deepEqual(requests.at(-1), ['POST', '/account-usage/refresh'])
  assert.match(details.textContent, /数据已过期/)
  assert.equal(details.querySelector('progress').value, 12)
  await act(async () => {
    details.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  })
  assert.equal(document.querySelector('[role="dialog"]'), null)
  assert.equal(trigger.getAttribute('aria-expanded'), 'false')
  await act(async () => trigger.click())
  assert.match(document.querySelector('[role="dialog"]').textContent, /剩余 12%/)
  await act(async () => root.unmount())
  container.remove()
})
