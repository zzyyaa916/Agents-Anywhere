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
const calls = globalThis.testChatCalls = []
const groups = new Map()
const pending = () => ({ phase: 'pending', sessionId: null })
globalThis.testTaskGroups = {
  list: async () => ({ groups: [] }),
  create: async (_token, body) => {
    calls.push(['prepare', body])
    const row = { id: 'a'.repeat(40), projectId: 'p', phase: 'ready', selected: null, base: 'base', request: body, candidates: body.candidates.map(pending) }
    groups.set(row.id, row); return structuredClone(row)
  },
  get: async (_token, id) => structuredClone(groups.get(id)),
  start: async (_token, id, slot) => {
    calls.push(['start', id, slot]); const row = groups.get(id)
    row.candidates[slot] = { phase: 'sent', status: 'idle', sessionId: `session-${id[0]}-${slot}` }
    return structuredClone(row)
  },
  diff: async () => ({ stat: 'new.txt | 1 +', diff: '+independent result', base: 'base', head: 'snapshot' }),
  select: async (_token, id, slot) => { const row = groups.get(id); row.selected = slot; return structuredClone(row) },
  handoff: async (_token, id, body) => {
    calls.push(['handoff', id, body])
    const row = { id: 'b'.repeat(40), projectId: 'p', phase: 'ready', selected: null, base: 'snapshot', handoffBrief: body.instructions,
      request: { content: 'Forwarded task', candidates: [body.target], source: { groupId: id, slot: body.slot } }, candidates: [pending()] }
    groups.set(row.id, row); return structuredClone(row)
  },
}
globalThis.testWorkspace = {
  projects: [{ id: 'p', connectorId: 'c', name: 'Project' }], connectors: [{ id: 'c', deviceOs: 'linux' }],
  runtimes: ['codex', 'claude'].map(runtime => ({ connectorId: 'c', runtimeId: runtime, runtimeType: runtime, displayName: runtime, status: 'running' })),
  refreshData: async () => {}, upsertSession: () => {}, reportSessionStreamProgress: () => {},
}
const source = registerSource()
const hooks = registerHooks({ load(url, context, next) {
  const mocks = {
    '/components/auth/auth-context.tsx': 'export const useAuth=()=>({session:{accessToken:"test-token",userId:"user"}})',
    '/components/workspace-context.tsx': 'export const useWorkspace=()=>globalThis.testWorkspace',
    '/features/task-groups/api.ts': 'export const taskGroupsApi=globalThis.testTaskGroups;export const candidateStopped=c=>c.phase==="sent"&&c.status==="idle"',
    '/components/session-detail.tsx': `import * as React from "react";
      export function SessionDetail({sessionId,onMemorySnapshotUpdated}) {
        const [value,setValue]=React.useState('');
        React.useEffect(()=>{onMemorySnapshotUpdated({items:[{type:'message',role:'assistant',content:{text:'Result for '+sessionId}}]})},[sessionId,onMemorySnapshotUpdated]);
        return React.createElement('div',{'data-chat':sessionId},React.createElement('textarea',{'aria-label':'chat-'+sessionId,value,onChange:e=>setValue(e.target.value)}),
          React.createElement('button',{onClick:()=>{globalThis.testChatCalls.push(['message',sessionId,value]);setValue('')}},'chat-send'))
      }`,
    '/components/ui/button.tsx': 'import * as React from "react";export const Button=({children,variant,size,...props})=>React.createElement("button",props,children)',
    '/components/ui/label.tsx': 'import * as React from "react";export const Label=({children,...props})=>React.createElement("label",props,children)',
    '/components/ui/textarea.tsx': 'import * as React from "react";export const Textarea=props=>React.createElement("textarea",props)',
    '/components/ui/native-select.tsx': 'import * as React from "react";export const NativeSelect=props=>React.createElement("select",props);export const NativeSelectOption=props=>React.createElement("option",props)',
    '/components/ui/dialog.tsx': 'import * as React from "react";export const Dialog=({open,children})=>open?React.createElement("div",null,children):null;export const DialogContent=({children})=>React.createElement("div",{role:"dialog"},children);export const DialogTitle=DialogContent;export const DialogDescription=DialogContent;export const DialogHeader=DialogContent;export const DialogFooter=DialogContent',
  }
  for (const [path, text] of Object.entries(mocks)) if (url.endsWith(path)) return { format: 'module', shortCircuit: true, source: text }
  if (url.includes('/next-intl/') || url.endsWith('/next-intl')) return { format: 'module', shortCircuit: true, source: 'export const useTranslations=()=>(key,values)=>key+(values?.n??"")' }
  return next(url, context)
} })
const { TaskGroupsButton } = await import('../src/components/task-groups.tsx')
hooks.deregister(); source.deregister()

async function input(element, value) {
  assert.ok(element)
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set.call(element, value)
    element.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
  })
}

for (const count of [1, 2, 3]) test(`${count} agents open independent chats; panes minimize, close and reopen; forwarding preserves source chats and custom instructions`, async () => {
  calls.length = 0; groups.clear()
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const click = async (text, scope = container) => {
    const button = [...scope.querySelectorAll('button')].find(b => b.textContent === text)
    assert.ok(button, `Missing button ${text}`); assert.equal(button.disabled, false)
    await act(async () => button.click())
  }
  const pane = slot => container.querySelector(`[data-pane-key="${'a'.repeat(40)}:${slot}"]`)
  try {
    await act(async () => root.render(h(TaskGroupsButton)))
    await click('entry')
    assert.equal(calls.length, 0)
    assert.equal(container.querySelector('[aria-label="execution"]').value, '1')
    await act(async () => { const select = container.querySelector('[aria-label="execution"]'); select.value = String(count); select.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await input(container.querySelector('[aria-label="task"]'), 'Improve the implementation')
    await click('prepare')
    assert.equal(calls[0][1].candidates.length, count)
    assert.equal(calls.filter(c => c[0] === 'start').length, 0)
    await click('start')
    assert.equal(calls.filter(c => c[0] === 'start').length, count)
    assert.equal(container.querySelectorAll('[data-chat]').length, count)
    assert.equal(container.querySelector('[data-chat-grid]').style.gridTemplateColumns.split('minmax').length - 1, count)
    await input(pane(0).querySelector('textarea'), 'Message only for AI 1')
    if (count > 1) await input(pane(1).querySelector('textarea'), 'Unsent draft for AI 2')
    await click('chat-send', pane(0))
    assert.deepEqual(calls.filter(c => c[0] === 'message'), [['message', 'session-a-0', 'Message only for AI 1']])
    if (count > 1) assert.equal(pane(1).querySelector('textarea').value, 'Unsent draft for AI 2')
    await act(async () => pane(0).querySelector('[aria-label="minimize"]').click())
    assert.ok(pane(0).querySelector('[data-chat]').closest('.hidden'))
    await act(async () => pane(0).querySelector('[aria-label="restore"]').click())
    await act(async () => pane(0).querySelector('[aria-label="close"]').click())
    assert.equal(pane(0), null)
    const reopen = [...container.querySelectorAll('button')].find(b => b.textContent.startsWith('reopen'))
    await act(async () => reopen.click())
    assert.ok(pane(0))
    await click('inspect', pane(0))
    assert.match(pane(0).textContent, /independent result/)
    await act(async () => pane(0).querySelector('[aria-label="forward"]').click())
    assert.equal(calls.filter(c => c[0] === 'start').length, count)
    assert.equal(container.querySelector('[aria-label="handoffAgent"]').value, 'claude')
    assert.equal([...container.querySelectorAll('button')].find(b => b.textContent === 'sendForward').disabled, true)
    await click('cancel')
    assert.equal(calls.filter(c => c[0] === 'handoff').length, 0)
    await act(async () => pane(0).querySelector('[aria-label="forward"]').click())
    await input(container.querySelector('[aria-label="forwardInstructions"]'), 'Check this result; do not change any code.')
    assert.match(container.textContent, /Result for session-a-0/)
    await click('sendForward')
    const forwarded = calls.find(c => c[0] === 'handoff')[2]
    assert.equal(forwarded.target.runtime, 'claude')
    assert.equal(forwarded.instructions, 'Check this result; do not change any code.')
    assert.equal(calls.filter(c => c[0] === 'start').length, count + 1)
    assert.equal(container.querySelectorAll('[data-chat]').length, count + 1)
    assert.ok(pane(0), 'Forwarding must retain the source chat')
    if (count > 1) assert.equal(pane(1).querySelector('textarea').value, 'Unsent draft for AI 2')
  } finally { await act(async () => root.unmount()); container.remove() }
})
