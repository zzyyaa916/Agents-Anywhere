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
  newSessionProject: { id: 'p', connectorId: 'c', name: 'Project' },
  runtimes: ['codex', 'claude', 'dsh'].map(runtime => ({ connectorId: 'c', runtimeId: runtime, runtimeType: runtime, displayName: runtime, status: 'running' })),
  resolveProject: async body => { calls.push(['resolveProject', body]); return { id: 'p', connectorId: body.connectorId, workspacePath: body.workspacePath, name: 'Project' } },
  refreshData: async () => {}, upsertSession: () => {}, reportSessionStreamProgress: () => {},
}
const fullInventory = globalThis.testWorkspace.runtimes
globalThis.testWorkspace.runtimes = fullInventory.filter(row => row.runtimeType !== 'dsh')
globalThis.testDashboard = {
  getConnectorRuntimes: async () => ({ runtimes: fullInventory }),
  getConnectorRuntimeCapabilities: async (_token, _connector, id) => ({ capabilitySet: { capabilities: id === 'dsh' ? ['catalog.model', 'catalog.permission'].map(capabilityId => ({ capabilityId, runtime: 'dsh', supported: true, available: true, allowed: true })) : [] } }),
  getConnectorRuntimeModelCatalog: async () => ({ catalog: { models: [
    { id: 'deepseek', displayName: 'DeepSeek', default: true, selectionId: 'dsh-model-1', reasoningItems: [], metadata: {} },
    { id: 'other', displayName: 'Other model', default: false, selectionId: 'dsh-model-2', reasoningItems: [], metadata: {} },
  ] } }),
  getConnectorRuntimePermissionCatalog: async () => ({ catalog: { permissions: [
    { id: 'read', displayName: 'Read only', default: true, selectionId: 'dsh-permission-read', metadata: {} },
    { id: 'write', displayName: 'Workspace write', default: false, selectionId: 'dsh-permission-write', metadata: {} },
  ] } }),
}
const source = registerSource()
const hooks = registerHooks({ load(url, context, next) {
  const mocks = {
    '/features/dashboard/api.ts': 'export const dashboardApi=globalThis.testDashboard',
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
    await act(async () => root.render(h(TaskGroupsButton, { workspace: { connectorId: 'c', path: '/chosen/project' } })))
    await click('entry')
    assert.deepEqual(calls.shift(), ['resolveProject', { connectorId: 'c', workspacePath: '/chosen/project' }])
    assert.equal(calls.length, 0)
    assert.equal(container.querySelector('[aria-label="execution"]').value, '1')
    assert.equal(container.querySelector('[aria-label="project"]'), null)
    await act(async () => { const select = container.querySelector('[aria-label="execution"]'); select.value = String(count); select.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    for (let slot = 0; slot < count; slot++) await act(async () => {
      const select = container.querySelector(`[aria-label="candidate${slot + 1}"]`)
      assert.ok([...select.options].some(option => option.value === 'dsh'))
      select.value = slot === count - 1 ? 'dsh' : 'codex'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
    })
    await act(async () => { const select = container.querySelector(`[aria-label="candidate${count} model"]`); select.value = 'other'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await input(container.querySelector('[aria-label="task"]'), 'Improve the implementation')
    await click('prepare')
    assert.equal(calls[0][1].projectId, 'p')
    assert.equal(calls[0][1].candidates.length, count)
    assert.deepEqual(calls[0][1].candidates[count - 1], { runtime: 'dsh', runtimeId: 'dsh', selections: { model: 'dsh-model-2', permission: 'dsh-permission-read' } })
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
    assert.equal(container.querySelector('[aria-label="handoffAgent"]').value, count === 1 ? 'codex' : 'claude')
    assert.equal([...container.querySelectorAll('button')].find(b => b.textContent === 'sendForward').disabled, true)
    await click('cancel')
    assert.equal(calls.filter(c => c[0] === 'handoff').length, 0)
    await act(async () => pane(0).querySelector('[aria-label="forward"]').click())
    await act(async () => { const select = container.querySelector('[aria-label="handoffAgent"]'); select.value = 'dsh'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await input(container.querySelector('[aria-label="forwardInstructions"]'), 'Check this result; do not change any code.')
    assert.match(container.textContent, /Result for session-a-0/)
    await click('sendForward')
    const forwarded = calls.find(c => c[0] === 'handoff')[2]
    assert.equal(forwarded.target.runtime, 'dsh')
    assert.deepEqual(forwarded.target.selections, { model: 'dsh-model-1', permission: 'dsh-permission-read' })
    assert.equal(forwarded.instructions, 'Check this result; do not change any code.')
    assert.equal(calls.filter(c => c[0] === 'start').length, count + 1)
    assert.equal(container.querySelectorAll('[data-chat]').length, count + 1)
    assert.ok(pane(0), 'Forwarding must retain the source chat')
    if (count > 1) assert.equal(pane(1).querySelector('textarea').value, 'Unsent draft for AI 2')
  } finally { await act(async () => root.unmount()); container.remove() }
})

test('collaboration works without a project route, explains missing workspace and retries failed DSH settings', async () => {
  const project = globalThis.testWorkspace.newSessionProject
  const original = globalThis.testDashboard.getConnectorRuntimeModelCatalog
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  try {
    globalThis.testWorkspace.newSessionProject = null
    await act(async () => root.render(h(TaskGroupsButton, { workspace: null })))
    assert.equal(container.querySelector('button').disabled, false)
    await act(async () => container.querySelector('button').click())
    assert.match(container.textContent, /workspaceRequired/)
    assert.equal(container.querySelector('[aria-label="task"]'), null)
    await act(async () => root.render(h(TaskGroupsButton, { workspace: { connectorId: 'c', path: '/chosen/project' } })))
    await act(async () => container.querySelector('button').click())
    globalThis.testDashboard.getConnectorRuntimeModelCatalog = async () => { throw new Error('DSH catalog unavailable') }
    await act(async () => {
      const select = container.querySelector('[aria-label="candidate1"]'); select.value = 'dsh'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
    })
    await input(container.querySelector('[aria-label="task"]'), 'Task')
    assert.match(container.textContent, /DSH catalog unavailable/)
    assert.equal([...container.querySelectorAll('button')].find(b => b.textContent === 'prepare').disabled, true)
    globalThis.testDashboard.getConnectorRuntimeModelCatalog = original
    await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent === 'retry').click())
    assert.equal([...container.querySelectorAll('button')].find(b => b.textContent === 'prepare').disabled, false)
  } finally {
    globalThis.testDashboard.getConnectorRuntimeModelCatalog = original
    globalThis.testWorkspace.newSessionProject = project
    await act(async () => root.unmount()); container.remove()
  }
})
