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
let body, fail, requests
function initial() {
  return { serverTime: '2033-05-18T03:33:20Z', refresh: { status: 'idle' }, snapshots: [{ runtime: 'claude_code', accountKey: 'a'.repeat(64), accountLabel: 'aaaaaaaa', fetchedAt: '2033-05-18T03:21:20Z', stale: false,
    bindings: [{ connectorId: 'device', runtimeId: 'claude' }], windows: [
      { kind: 'five_hour', remainingPercent: 29, resetsAt: '2033-05-18T14:30:00Z', windowDurationMins: 300, source: 'event', receivedAt: '2033-05-18T03:21:20Z', ageSeconds: 720 },
      { kind: 'seven_day', remainingPercent: 72, resetsAt: '2033-05-25T14:30:00Z', windowDurationMins: 10080, source: 'probe', receivedAt: '2033-05-18T02:43:20Z', ageSeconds: 3000 }
    ] }], unavailable: [] }
}
globalThis.usageTestRequest = async (method, path) => { requests.push([method, path]); if (fail) throw Error('offline'); return structuredClone(body) }
const hook = registerHooks({ load(url, context, next) {
  if (url.endsWith('/components/auth/auth-context.tsx')) return { format: 'module', shortCircuit: true, source: 'export const useAuth = () => ({session:{accessToken:"synthetic-app-session"}})' }
  if (url.endsWith('/lib/api/index.ts')) return { format: 'module', shortCircuit: true, source: 'export const apiClient={get:p=>globalThis.usageTestRequest("GET",p),post:p=>globalThis.usageTestRequest("POST",p)}' }
  return next(url, context)
}})
const { AccountUsageProvider, AccountUsagePanel } = await import('../src/components/account-usage.tsx')
hook.deregister(); source.deregister()
async function render(t, configure = () => {}) {
  body = initial(); fail = false; requests = []; configure()
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  t.after(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(h(AccountUsageProvider, {}, h(AccountUsagePanel))))
  await act(async () => container.querySelector('button[aria-label="查看账号用量"]').click())
  return document.querySelector('[role="dialog"]')
}
const refresh = () => document.querySelector('button[aria-label="刷新用量"]')

test('opening only reads cache, windows show individual sources and server ages', async t => {
  const panel = await render(t)
  assert.ok(requests.length >= 1 && requests.every(([method]) => method === 'GET'))
  assert.match(panel.textContent, /05\/18 03:21 更新 · 缓存/)
  assert.doesNotMatch(panel.textContent, /更新 · 探针/)
  assert.equal(refresh().textContent, '刷新')
})
test('only refresh posts; successful data starts at server age zero', async t => {
  const panel = await render(t)
  body.refresh.status = 'success'; body.refresh.completedAt = body.serverTime; body.snapshots[0].windows[0].source = 'probe'; body.snapshots[0].windows[0].ageSeconds = 0; body.snapshots[0].windows[0].receivedAt = body.serverTime
  await act(async () => refresh().click())
  assert.deepEqual(requests.filter(([method]) => method === 'POST'), [['POST', '/account-usage/refresh']])
  assert.match(panel.textContent, /更新 · 探针/)
  assert.equal(refresh().textContent, '刷新')
})
test('transport failure keeps the exact prior values, source and age', async t => {
  const panel = await render(t)
  fail = true
  await act(async () => refresh().click())
  assert.match(refresh().textContent, /稍后重试/)
  assert.match(panel.textContent, /05\/18 03:21 更新 · 缓存/)
  assert.match(panel.textContent, /剩余 29%/)
  assert.match(panel.textContent, /原有数据保留/)
})
for (const status of ['retry', 'offline', 'circuit']) {
  test(`${status} disables refresh until server retry time without discarding data`, async t => {
    const panel = await render(t, () => { body.refresh = { status, nextAllowedAt: '2033-05-19T00:00:00Z' } })
    assert.equal(refresh().disabled, true)
    await act(async () => refresh().click())
    assert.ok(requests.every(([method]) => method === 'GET'))
    assert.match(panel.textContent, /剩余 29%/)
    assert.match(panel.textContent, /可重试时间/)
    if (status === 'offline') assert.match(panel.textContent, /探针节点离线/)
    if (status === 'circuit') assert.match(refresh().textContent, /今日探针已熔断，明日恢复/)
  })
}


test('device wall-clock skew does not bypass server retry time or change data age', async t => {
  const original = Date.now
  Date.now = () => Date.parse('2099-01-01T00:00:00Z')
  t.after(() => { Date.now = original })
  const panel = await render(t, () => { body.refresh = { status: 'retry', nextAllowedAt: '2033-05-19T00:00:00Z' } })
  assert.equal(refresh().disabled, true)
  assert.match(panel.textContent, /05\/18 03:21 更新 · 缓存/)
})


test('usage stays compact and combines matching Claude update labels', async t => {
  const panel = await render(t, () => {
    for (const window of body.snapshots[0].windows) { window.source = 'probe'; window.receivedAt = '2033-05-18T03:33:20Z' }
  })
  assert.equal(refresh().textContent, '刷新')
  assert.doesNotMatch(panel.textContent, /已用|报告重置|分钟前|只有点击刷新/)
  assert.equal((panel.textContent.match(/05\/18 03:33 更新 · 探针/g) || []).length, 1)
  assert.match(panel.textContent, /重置时间/)
})


test('one Claude footer follows the newest window source in either direction', async t => {
  let panel = await render(t, () => { body.snapshots[0].windows[1].receivedAt = '2033-05-18T03:30:00Z' })
  assert.match(panel.textContent, /05\/18 03:30 更新 · 探针/)
  assert.doesNotMatch(panel.textContent, /更新 · 缓存/)
  body.snapshots[0].windows[0].receivedAt = '2033-05-18T03:33:20Z'
  await act(async () => refresh().click())
  assert.match(panel.textContent, /05\/18 03:33 更新 · 缓存/)
  assert.doesNotMatch(panel.textContent, /更新 · 探针/)
})
