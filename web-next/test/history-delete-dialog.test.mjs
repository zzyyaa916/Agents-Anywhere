import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { setTimeout as delay } from 'node:timers/promises'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://test.example/', pretendToBeVisual: true })
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLButtonElement', 'Element', 'Node', 'NodeFilter', 'CustomEvent', 'MutationObserver', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame']) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { createElement: h, act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { NextIntlClientProvider } = await import('next-intl')
const source = registerSource()
const workspaceHook = registerHooks({ load(url, context, next) {
  if (url.endsWith('/components/workspace-context.tsx')) return { format: 'module', shortCircuit: true, source: 'export const useWorkspace = () => globalThis.historyWorkspace' }
  return next(url, context)
}})
const { HistoryDeleteDialog } = await import('../src/components/sidebar/history-delete-dialog.tsx')
const { ApiError } = await import('../src/lib/api/errors.ts')
workspaceHook.deregister(); source.deregister()
const messages = JSON.parse(readFileSync(new URL('../messages/zh-CN.json', import.meta.url), 'utf8'))

async function render(t, props = {}, workspace = {}) {
  globalThis.historyWorkspace = {
    projectDeletionCount: async () => 3,
    deleteProject: async () => true,
    deleteSession: async () => {},
    ...workspace,
  }
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let closed = 0
  await act(async () => {
    root.render(h(NextIntlClientProvider, { locale: 'zh-CN', messages, timeZone: 'UTC' }, h(HistoryDeleteDialog, {
      open: true, id: 'object', name: 'My Project', onOpenChange: value => { if (!value) closed++ }, ...props,
    })))
    await delay(10)
  })
  t.after(async () => { await act(async () => root.unmount()); container.remove() })
  return { closed: () => closed }
}
function button(text) { return [...document.querySelectorAll('button')].find(node => node.textContent === text) }
async function click(text) {
  const target = button(text); assert.ok(target, `Missing ${text}`)
  assert.equal(target.disabled, false)
  await act(async () => { target.click(); await delay(10) })
}
async function type(value) {
  const input = document.querySelector('input')
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new window.Event('input', { bubbles: true }))
    await delay(1)
  })
}

test('cancelling a session confirmation never sends deletion', async t => {
  let calls = 0
  const ui = await render(t, {}, { deleteSession: async () => { calls++ } })
  await click('取消')
  assert.equal(calls, 0); assert.equal(ui.closed(), 1)
})

test('project deletion displays the exact total and requires typing the project name', async t => {
  const calls = []
  await render(t, { project: true }, { deleteProject: async (...args) => { calls.push(args); return true } })
  assert.match(document.body.textContent, /全部 3 个会话/)
  assert.equal(button('删除').disabled, true)
  await type('wrong'); assert.equal(button('删除').disabled, true)
  await type('My Project'); await click('删除')
  assert.deepEqual(calls, [['object', 3]])
})

test('running conflict keeps confirmation open and points to the blocking session', async t => {
  const ui = await render(t, {}, { deleteSession: async () => { throw new ApiError({
    status: 409, kind: 'http', detail: 'busy', code: 'session_running', payload: { detail: { sessionIds: ['sess_busy'] } },
  }) } })
  await click('删除')
  assert.equal(ui.closed(), 0)
  assert.match(document.querySelector('[role="alert"]').textContent, /请先停止.*sess_busy/)
})

test('project count changes require a fresh preview and another confirmation', async t => {
  let checks = 0
  await render(t, { project: true }, {
    projectDeletionCount: async () => ++checks,
    deleteProject: async () => { throw new ApiError({ status: 409, kind: 'http', detail: 'changed', code: 'deletion_count_changed' }) },
  })
  await type('My Project'); await click('删除')
  assert.equal(button('删除').disabled, true)
  assert.match(document.querySelector('[role="alert"]').textContent, /数量已变化/)
  await click('重新核对')
  assert.match(document.body.textContent, /全部 2 个会话/)
  assert.equal(document.querySelector('input').value, '')
  assert.equal(button('删除').disabled, true)
})

test('a preview failure cannot silently confirm a zero-session project', async t => {
  let deletes = 0
  await render(t, { project: true }, {
    projectDeletionCount: async () => { throw new Error('offline') },
    deleteProject: async () => { deletes++; return true },
  })
  assert.equal(button('删除').disabled, true)
  assert.match(document.querySelector('[role="alert"]').textContent, /无法核对/)
  await click('取消')
  assert.equal(deletes, 0)
})

test('a repeated click while deletion is pending sends only one request', async t => {
  let calls = 0, finish
  const ui = await render(t, {}, { deleteSession: () => { calls++; return new Promise(resolve => { finish = resolve }) } })
  const confirm = button('删除')
  await act(async () => { confirm.click(); confirm.click(); await delay(1) })
  assert.equal(calls, 1)
  assert.equal(button('正在删除…').disabled, true)
  await act(async () => { finish(); await delay(1) })
  assert.equal(ui.closed(), 1)
})


test('abandoning failed device cleanup requires a separate confirmation', async t => {
  const calls = []
  const ui = await render(t, {}, {
    deleteSession: async () => { throw new ApiError({ status: 503, kind: 'http', detail: 'device unavailable', code: 'device_cleanup_incomplete' }) },
    abandonHistoryCleanup: async (...args) => { calls.push(args) },
  })
  await click('删除')
  assert.equal(ui.closed(), 0)
  await click('放弃剩余设备清理')
  assert.equal(calls.length, 0)
  assert.match(document.body.textContent, /尚未删除的设备文件和原生历史将保留/)
  await click('确认保留剩余文件并放弃清理')
  assert.deepEqual(calls, [['object', false]])
  assert.equal(ui.closed(), 1)
})


test('unexpected server errors never offer device cleanup abandonment', async t => {
  await render(t, {}, { deleteSession: async () => { throw new ApiError({ status: 500, kind: 'http', detail: 'database failure' }) } })
  await click('删除')
  assert.equal(button('放弃剩余设备清理'), undefined)
})
