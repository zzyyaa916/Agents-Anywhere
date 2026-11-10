import assert from 'node:assert/strict'
import test from 'node:test'
import { registerHooks } from 'node:module'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'

const dom = new JSDOM('<html><body></body></html>', { url: 'https://test.example/' })
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event']) Object.defineProperty(globalThis, key, { configurable: true, value: dom.window[key] })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { createElement: h, act } = await import('react')
const { createRoot } = await import('react-dom/client')
const calls = []
let group
const target = { runtime: 'codex', runtimeId: 'codex', selections: {} }
const pending = () => ({ phase: 'pending', sessionId: null })
globalThis.testTaskGroups = {
  list: async () => ({ groups: [] }),
  create: async (_token, body) => { calls.push(['prepare', body]); group = { id: 'a'.repeat(40), phase: 'ready', selected: null, base: 'base', request: body, candidates: body.candidates.map(pending) }; return structuredClone(group) },
  get: async () => structuredClone(group),
  start: async (_token, _id, slot) => { calls.push(['start', slot]); group.candidates[slot] = { phase: 'sent', status: 'idle', sessionId: `session-${slot}` }; return structuredClone(group) },
  diff: async () => ({ stat: 'new.txt | 1 +', diff: '+independent result', base: 'base', head: 'snapshot' }),
  select: async (_token, _id, slot) => { group.selected = slot; return structuredClone(group) },
  handoff: async (_token, _id, body) => { calls.push(['handoff', body]); group = { id: 'b'.repeat(40), phase: 'ready', selected: null, base: 'snapshot', handoffBrief: 'Review this fixed snapshot', request: { content: 'Review', candidates: [body.target] }, candidates: [pending()] }; return structuredClone(group) },
}
globalThis.testWorkspace = {
  projects: [{ id: 'p', connectorId: 'c', name: 'Project' }],
  runtimes: ['codex', 'claude'].map(runtime => ({ connectorId: 'c', runtimeId: runtime, runtimeType: runtime, displayName: runtime, status: 'running' })),
  refreshData: async () => {}, openSession: id => calls.push(['open', id]),
}
const source = registerSource()
const hooks = registerHooks({ load(url, context, next) {
  const mocks = {
    '/components/auth/auth-context.tsx': 'export const useAuth=()=>({session:{accessToken:"test-token",userId:"user",serverUrl:"https://test.example"}})',
    '/components/workspace-context.tsx': 'export const useWorkspace=()=>globalThis.testWorkspace',
    '/features/task-groups/api.ts': 'export const taskGroupsApi=globalThis.testTaskGroups;export const candidateStopped=c=>c.phase==="sent"&&c.status==="idle"',
    '/features/dashboard/api.ts': 'export const dashboardApi={getLatestSessionTimeline:async()=>({items:[{type:"message",role:"assistant",content:{text:"Tested candidate summary"}}]})}',
    '/components/ui/button.tsx': 'import * as React from "react";export const Button=({children,variant,size,...props})=>React.createElement("button",props,children)',
    '/components/ui/label.tsx': 'import * as React from "react";export const Label=({children,...props})=>React.createElement("label",props,children)',
    '/components/ui/textarea.tsx': 'import * as React from "react";export const Textarea=props=>React.createElement("textarea",props)',
    '/components/ui/native-select.tsx': 'import * as React from "react";export const NativeSelect=props=>React.createElement("select",props);export const NativeSelectOption=props=>React.createElement("option",props)',
    '/components/ui/dialog.tsx': 'import * as React from "react";export const Dialog=({open,children})=>open?React.createElement("div",null,children):null;export const DialogContent=({children})=>React.createElement("div",null,children);export const DialogTitle=DialogContent;export const DialogDescription=DialogContent;export const DialogHeader=DialogContent',
  }
  for (const [path, text] of Object.entries(mocks)) if (url.endsWith(path)) return { format: 'module', shortCircuit: true, source: text }
  if (url.includes('/next-intl/') || url.endsWith('/next-intl')) return { format: 'module', shortCircuit: true, source: 'export const useTranslations=()=>key=>key' }
  return next(url, context)
} })
const { TaskGroupsButton } = await import('../src/components/task-groups.tsx')
hooks.deregister(); source.deregister()

test('three candidates require explicit start; selected result prepares a separate review without automatically dispatching it', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const click = async text => {
    const button = [...container.querySelectorAll('button')].find(b => b.textContent === text)
    assert.ok(button, `Missing button ${text}`); assert.equal(button.disabled, false)
    await act(async () => button.click())
  }
  try {
    await act(async () => root.render(h(TaskGroupsButton)))
    await click('entry')
    assert.equal(calls.length, 0)
    await act(async () => {
      const input = container.querySelector('textarea')
      Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set.call(input, 'Improve the implementation')
      input.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    })
    await click('prepare')
    assert.equal(calls[0][1].candidates.length, 3)
    assert.equal(calls.filter(c => c[0] === 'start').length, 0)
    await click('start')
    assert.equal(calls.filter(c => c[0] === 'start').length, 3)
    await click('inspect')
    assert.match(container.textContent, /Tested candidate summary/)
    assert.match(container.textContent, /independent result/)
    await click('select')
    await click('prepareHandoff')
    assert.equal(calls.filter(c => c[0] === 'start').length, 3)
    assert.equal(calls.find(c => c[0] === 'handoff')[1].mode, 'review')
    assert.match(container.textContent, /Review this fixed snapshot/)
    await click('start')
    assert.equal(calls.filter(c => c[0] === 'start').length, 4)
  } finally { await act(async () => root.unmount()) }
})
