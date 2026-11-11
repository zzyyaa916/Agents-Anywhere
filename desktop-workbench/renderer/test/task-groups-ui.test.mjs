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
    const existing = [...groups.values()].find(row => row.operationId === body.operationId)
    if (existing) return structuredClone(existing)
    const row = { id: String.fromCharCode(97 + groups.size).repeat(40), operationId: body.operationId, projectId: 'p', phase: 'ready', selected: null, base: 'snapshot', handoffBrief: body.instructions,
      request: { content: 'Forwarded task', candidates: [body.target], source: { groupId: id, slot: body.slot } }, candidates: [pending()] }
    groups.set(row.id, row); return structuredClone(row)
  },
}
globalThis.testWorkspace = {
  sessions: [], jointGroupId: null, navigate: (...args) => calls.push(["navigate", ...args]),
  projects: [{ id: 'p', connectorId: 'c', name: 'Project', workspacePath: '/chosen/project' }], connectors: [{ id: 'c', name: 'Device', status: 'online', deviceOs: 'linux' }],
  newSessionProject: { id: 'p', connectorId: 'c', name: 'Project', workspacePath: '/chosen/project' },
  runtimes: ['codex', 'claude', 'dsh'].map(runtime => ({ connectorId: 'c', runtimeId: runtime, runtimeType: runtime, displayName: runtime, status: 'running', configured: true, active: true })),
  resolveProject: async body => { calls.push(['resolveProject', body]); return { id: 'p', connectorId: body.connectorId, workspacePath: body.workspacePath, name: 'Project' } },
  startSessionCreation: body => { calls.push(['single', body]); return Promise.resolve() },
  saveCreationEditor: () => {}, discardCreationEditor: () => {}, goHome: () => {},
  refreshData: async () => {}, upsertSession: () => {}, reportSessionStreamProgress: () => {},
}
const fullInventory = globalThis.testWorkspace.runtimes
globalThis.testWorkspace.runtimes = fullInventory.filter(row => row.runtimeType !== 'dsh')
globalThis.testDashboard = {
  getConnectorRuntimes: async () => ({ runtimes: fullInventory }),
  sendSessionMessage: async (_token, id, content, options) => { calls.push(['broadcast', id, content, options]); return { ok: true } },
  getConnectorRuntimeCapabilities: async (_token, _connector, id) => ({ capabilitySet: { capabilities: id === 'dsh' ? ['catalog.model', 'catalog.permission'].map(capabilityId => ({ capabilityId, runtime: 'dsh', supported: true, available: true, allowed: true })) : [] } }),
  getConnectorRuntimeModelCatalog: async () => ({ catalog: { models: [
    { id: 'deepseek', displayName: 'DeepSeek', default: true, selectionId: 'dsh-model-1', reasoningItems: [{ id: 'low', displayName: 'Low', default: true, selectionId: 'dsh-model-low', metadata: {} }, { id: 'high', displayName: 'High', default: false, selectionId: 'dsh-model-high', metadata: {} }], metadata: {} },
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
    '/components/ui/sidebar.tsx': 'export const useSidebar=()=>({isMobile:true,state:"collapsed"})',
    '/hooks/use-element-width.ts': 'export const useElementWidth=()=>320',
    '/components/session-tool-sidebar-state.tsx': 'export const useSessionToolSidebarStore=()=>({migrateSession:()=>{}})',
    '/components/session/use-workspace-preparation.ts': 'export const useWorkspacePreparation=()=>({operation:null,pending:false,error:null,retry:()=>{}})',
    '/components/session/runtime-workflow-panel.tsx': 'export const RuntimeWorkflowPanel=()=>null',
    '/components/session/runtime-creation-status.tsx': 'export const RuntimeCreationStatus=()=>null',
    '/components/sidebar/project-editor-dialog.tsx': 'export const ProjectEditorDialog=()=>null',
    '/components/workspace-picker.tsx': 'export const WorkspacePicker=()=>null',
    '/components/attachment-input.tsx': 'export const AttachmentButton=()=>null;export const AttachmentPreviewList=()=>null;export const DragOverlay=()=>null;const result={attachments:[],attachmentsAllowed:true,clear:()=>{},add:()=>{},remove:()=>{}};export const useAttachments=()=>({...result,attachments:globalThis.testInitialAttachments??[]})',
    '/components/ui/badge.tsx': 'import * as React from "react";export const Badge=({children})=>React.createElement("span",null,children)',
    '/components/ui/separator.tsx': 'import * as React from "react";export const Separator=()=>React.createElement("hr")',
    '/components/ui/drawer.tsx': `import * as React from "react";const Context=React.createContext(null);
      export const Drawer=({children,open,onOpenChange})=>{const [value,setValue]=React.useState(false);return React.createElement(Context.Provider,{value:{open:open??value,setOpen:onOpenChange??setValue}},children)};
      export const DrawerTrigger=({children})=>{const ctx=React.useContext(Context);return React.cloneElement(children,{onClick:()=>ctx.setOpen(true)})};
      export const DrawerContent=({children})=>{const ctx=React.useContext(Context);return ctx.open?React.createElement('div',{role:'dialog'},children,React.createElement('button',{onClick:()=>ctx.setOpen(false)},'drawer-close')):null};
      export const DrawerHeader=({children})=>React.createElement('div',null,children);export const DrawerTitle=DrawerHeader;export const DrawerDescription=DrawerHeader;`,
    '/components/ui/dropdown-menu.tsx': `import * as React from "react";const Part=({children})=>React.createElement('div',null,children);export {Part as DropdownMenu,Part as DropdownMenuTrigger,Part as DropdownMenuContent,Part as DropdownMenuGroup,Part as DropdownMenuItem,Part as DropdownMenuLabel,Part as DropdownMenuSeparator,Part as DropdownMenuSub,Part as DropdownMenuSubContent,Part as DropdownMenuSubTrigger};`,
    '/components/auth/auth-context.tsx': 'export const useAuth=()=>({session:{accessToken:"test-token",userId:globalThis.testUserId??"user"}})',
    '/components/workspace-context.tsx': 'export const useWorkspace=()=>globalThis.testWorkspace',
    '/features/task-groups/api.ts': 'export const taskGroupsApi=globalThis.testTaskGroups;export const candidateStopped=c=>c.phase==="sent"&&c.status==="idle"',
    '/components/session-detail.tsx': `import * as React from "react";
      export function SessionDetail({sessionId,onMemorySnapshotUpdated,onQueueReady,onForwardCommand}) {
        const [value,setValue]=React.useState('');
        React.useEffect(()=>{onQueueReady?.(text=>{globalThis.testChatCalls.push(['queued',sessionId,text]);return !globalThis.testQueueFailure?.(sessionId)});return ()=>onQueueReady?.(null)},[sessionId,onQueueReady]);
        React.useEffect(()=>{onMemorySnapshotUpdated?.({items:[{type:'message',role:'assistant',content:{text:'Result for '+sessionId}}]})},[sessionId,onMemorySnapshotUpdated]);
        return React.createElement('div',{'data-chat':sessionId},React.createElement('textarea',{'aria-label':'chat-'+sessionId,value,onChange:e=>setValue(e.target.value)}),
          React.createElement('button',{onClick:async()=>{const forwarded=await onForwardCommand?.(value,[]);if(forwarded==null)globalThis.testChatCalls.push(['message',sessionId,value]);if(forwarded!==false)setValue('')}},'chat-send'))
      }`,
    '/components/ui/button.tsx': 'import * as React from "react";export const Button=({children,variant,size,...props})=>React.createElement("button",props,children)',
    '/components/ui/label.tsx': 'import * as React from "react";export const Label=({children,...props})=>React.createElement("label",props,children)',
    '/components/ui/textarea.tsx': 'import * as React from "react";export const Textarea=props=>React.createElement("textarea",props)',
    '/components/ui/native-select.tsx': 'import * as React from "react";export const NativeSelect=props=>React.createElement("select",props);export const NativeSelectOption=props=>React.createElement("option",props)',
    '/components/ui/dialog.tsx': 'import * as React from "react";export const Dialog=({open,children})=>open?React.createElement("div",null,children):null;export const DialogContent=({children})=>React.createElement("div",{role:"dialog"},children);export const DialogTitle=DialogContent;export const DialogDescription=DialogContent;export const DialogHeader=DialogContent;export const DialogFooter=DialogContent',
  }
  for (const [path, text] of Object.entries(mocks)) if (url.endsWith(path)) return { format: 'module', shortCircuit: true, source: text }
  if (url.includes('/next-intl/') || url.endsWith('/next-intl')) return { format: 'module', shortCircuit: true, source: 'const translate=(key,values)=>key+(values?.n??"");export const useTranslations=()=>translate' }
  return next(url, context)
} })
const { TaskGroupConversation } = await import('../src/components/task-groups.tsx')
const { AgentSelectionDrawer } = await import('../src/components/session/agent-selection-drawer.tsx')
const { useSessionForward } = await import('../src/components/session/session-forward.tsx')
const { TaskComposer } = await import('../src/components/task-composer.tsx')
const { JointConversations } = await import('../src/components/joint-conversations.tsx')
const { forwardToTargets } = await import('../src/features/task-groups/forward-to-targets.ts')
hooks.deregister(); source.deregister()

async function input(element, value) {
  assert.ok(element)
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set.call(element, value)
    element.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
  })
}

for (const count of [1, 2, 3]) test(`${count} agents open independent chats; panes minimize, close and reopen; forwarding preserves source chats and custom instructions`, async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const click = async (text, scope = container) => {
    const button = [...scope.querySelectorAll('button')].find(b => b.textContent === text)
    assert.ok(button, `Missing button ${text}`); assert.equal(button.disabled, false)
    await act(async () => button.click())
  }
  const pane = slot => container.querySelector(`[data-pane-key="${'a'.repeat(40)}:${slot}"]`)
  try {
    const body = { projectId: 'p', content: 'Improve the implementation', candidates: Array.from({ length: count }, (_, slot) => ({ runtime: slot === count - 1 ? 'dsh' : 'codex', runtimeId: slot === count - 1 ? 'dsh' : 'codex', selections: {} })) }
    const initialGroup = await globalThis.testTaskGroups.create('', body)
    for (let slot = 0; slot < count; slot++) await globalThis.testTaskGroups.start('', initialGroup.id, slot)
    const started = await globalThis.testTaskGroups.get('', initialGroup.id)
    await act(async () => root.render(h(TaskGroupConversation, { initialGroup: started, onBack: () => {} })))
    assert.equal(container.querySelectorAll('[data-chat]').length, count)
    for (let slot = 0; slot < count; slot++) {
      const title = pane(slot).querySelector('h3')?.textContent ?? pane(slot).querySelector('[data-pane-title]')?.textContent
      assert.ok(title, 'Pane title is visible')
      assert.doesNotMatch(title, /^(?:AI\s*\d|candidate\d)/)
    }
    assert.equal(container.querySelector('[data-chat-grid]').style.gridTemplateColumns.split('minmax').length - 1, count)
    await input(container.querySelector('[aria-label^="broadcastLabel"]'), 'Run the tests for your result')
    await click('broadcastSend')
    const broadcasts = calls.filter(row => row[0] === 'queued')
    assert.equal(broadcasts.length, count)
    assert.ok(broadcasts.every(row => row[2] === 'Run the tests for your result'))
    await input(pane(0).querySelector('textarea'), 'Message only for AI 1')
    if (count > 1) await input(pane(1).querySelector('textarea'), 'Unsent draft for AI 2')
    await click('chat-send', pane(0))
    assert.deepEqual(calls.filter(c => c[0] === 'message'), [['message', 'session-a-0', 'Message only for AI 1']])
    if (count > 1) assert.equal(pane(1).querySelector('textarea').value, 'Unsent draft for AI 2')
    await act(async () => pane(0).querySelector('[aria-label="minimize"]').click())
    assert.ok(pane(0).querySelector('[data-chat]').closest('.hidden'))
    await act(async () => pane(0).querySelector('[aria-label="restore"]').click())
    await act(async () => pane(0).querySelector('[aria-label="close"]').click())
    assert.ok(pane(0).classList.contains("hidden"))
    const reopen = [...container.querySelectorAll('button')].find(b => b.textContent.startsWith('reopen'))
    await act(async () => reopen.click())
    assert.ok(pane(0))
    await click('inspect', pane(0))
    assert.match(pane(0).textContent, /independent result/)
    await act(async () => pane(0).querySelector('[aria-label="forward"]').click())
    assert.equal(calls.filter(c => c[0] === 'start').length, count)
    assert.equal(container.querySelector('[aria-label="目标 AI 1"]').value, count === 1 ? 'codex' : 'claude')
    assert.equal([...container.querySelectorAll('button')].find(b => b.textContent === '发送').disabled, true)
    await click('取消')
    assert.equal(calls.filter(c => c[0] === 'handoff').length, 0)
    await act(async () => pane(0).querySelector('[aria-label="forward"]').click())
    await act(async () => { const select = container.querySelector('[aria-label="目标 AI 1"]'); select.value = 'dsh'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await input(container.querySelector('[aria-label="补充指令"]'), 'Check this result; do not change any code.')
    assert.match(container.textContent, /Result for session-a-0/)
    await click('发送')
    const forwarded = calls.find(c => c[0] === 'handoff')[2]
    assert.equal(forwarded.target.runtime, 'dsh')
    assert.deepEqual(forwarded.target.selections, { model: 'dsh-model-low', permission: 'dsh-permission-read' })
    assert.equal(forwarded.instructions, 'Check this result; do not change any code.')
    assert.equal(calls.filter(c => c[0] === 'start').length, count + 1)
    assert.equal(container.querySelectorAll('[data-chat]').length, count + 1)
    assert.ok(pane(0), 'Forwarding must retain the source chat')
    if (count > 1) assert.equal(pane(1).querySelector('textarea').value, 'Unsent draft for AI 2')
  } finally { await act(async () => root.unmount()); container.remove() }
})


for (const count of [1, 2, 3]) test(`main composer selects ${count} agents and sends the original prompt with each agent's settings`, async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear(); window.localStorage.clear()
  globalThis.testInitialAttachments = count > 1 ? [{id:"spec-file",name:"task.txt",type:"file",size:5,mediaType:"text/plain",file:new File(["hello"],"task.txt",{type:"text/plain"}),uploadStatus:"local"}] : []
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const clickText = async text => {
    const button = [...container.querySelectorAll('button')].find(row => (row.textContent === text || row.getAttribute('aria-label') === text))
    assert.ok(button, `Missing button ${text}`); assert.equal(button.disabled, false)
    await act(async () => button.click())
  }
  try {
    await act(async () => root.render(h(TaskComposer)))
    assert.equal([...container.querySelectorAll('button')].some(row => row.textContent === 'entry'), false)
    await act(async () => container.querySelector('[aria-label="agent"]').click())
    const agents = [...container.querySelectorAll('[role="checkbox"]')].filter(row => ['claude', 'codex', 'dsh'].includes(row.textContent))
    assert.equal(agents.length, 3)
    assert.equal(agents.filter(row => row.getAttribute('aria-checked') === 'true').length, 1)
    if (count >= 2) await clickText('codex')
    if (count === 3) await clickText('dsh')
    assert.equal(agents.filter(row => row.getAttribute('aria-checked') === 'true').length, count)
    await clickText('drawer-close')
    if (count > 1) {
      await clickText('settings')
      if (count === 3) {
        const reasoning = container.querySelector('[aria-label="dsh reasoning"]')
        assert.ok(reasoning)
        await act(async () => { reasoning.value = 'high'; reasoning.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
        const permission = container.querySelector('[aria-label="dsh permission"]')
        await act(async () => { permission.value = 'write'; permission.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
      }
      await clickText('drawer-close')
      // Closing settings must retain the selections used by the send button.
    }
    await input(container.querySelector('textarea[placeholder="placeholder"]'), 'Implement exactly this shared task')
    const send = container.querySelector('[aria-label="sendTask"]')
    assert.equal(send.disabled, false)
    await act(async () => { send.click(); for (let n=0; n<50 && !calls.some(row => row[0] === "single" || row[0] === "start"); n++) await new Promise(resolve => setTimeout(resolve, 5)) })
    if (count === 1) {
      const single = calls.find(row => row[0] === 'single')
      assert.ok(single)
      assert.equal(single[1].request.content, 'Implement exactly this shared task')
      assert.equal(calls.some(row => row[0] === 'prepare'), false)
    } else {
      const prepared = calls.find(row => row[0] === 'prepare')[1]
      assert.equal(prepared.content, 'Implement exactly this shared task')
      assert.equal(prepared.projectId, 'p')
      assert.equal(prepared.candidates.length, count)
      assert.equal(prepared.attachments[0].contentBase64, 'aGVsbG8=')
      assert.equal(prepared.attachments[0].name, 'task.txt')
      assert.equal(calls.filter(row => row[0] === 'start').length, count)
      assert.equal(container.querySelectorAll('[data-chat]').length, count)
      if (count === 3) assert.deepEqual(prepared.candidates.find(row => row.runtime === 'dsh').selections, { model: 'dsh-model-high', permission: 'dsh-permission-write' })
    }
  } finally { globalThis.testInitialAttachments=[]; await act(async () => root.unmount()); container.remove() }
})

test('agent selection keeps one selected, caps at three and retains choices when the drawer closes', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const { useState } = await import('react')
  function Harness() {
    const [ids,setIds] = useState(['a'])
    return h(AgentSelectionDrawer, { buttonLabel:'agents', title:'Device and agents', deviceLabel:'Device',agentLabel:'Agents',deviceItems:[{id:'device',label:'Device'}],selectedDevice:'device',onDeviceChange:()=>{},
      agentItems:['a','b','c','d'].map(id=>({id,label:id})),selectedAgent:ids[0],selectedAgents:ids,onAgentChange:id=>setIds(rows=>rows.includes(id)?rows.length===1?rows:rows.filter(row=>row!==id):rows.length===3?rows:[...rows,id]) })
  }
  const click = async text => { const button=[...container.querySelectorAll('button')].find(row=>row.textContent===text);assert.ok(button);await act(async()=>button.click()) }
  try {
    await act(async()=>root.render(h(Harness)))
    await act(async()=>container.querySelector('[aria-label="agents"]').click())
    await click('a')
    assert.equal(container.querySelectorAll('[role="checkbox"][aria-checked="true"]').length,1)
    await click('b');await click('c')
    assert.equal([...container.querySelectorAll('button')].find(row=>row.textContent==='d').disabled,true)
    await click('b');await click('d')
    await click('drawer-close')
    await act(async()=>container.querySelector('[aria-label="agents"]').click())
    assert.deepEqual([...container.querySelectorAll('[role="checkbox"][aria-checked="true"]')].map(row=>row.textContent),['a','c','d'])
  } finally { await act(async()=>root.unmount());container.remove() }
})

test('shared follow-up queues busy and hidden panes independently and retries only rejected queues', async () => {
  calls.length=0;groups.clear();window.localStorage.clear()
  const row=await globalThis.testTaskGroups.create('',{content:'Task',candidates:[{runtime:'codex',runtimeId:'codex'},{runtime:'dsh',runtimeId:'dsh'}]})
  await globalThis.testTaskGroups.start('',row.id,0);await globalThis.testTaskGroups.start('',row.id,1)
  const started=await globalThis.testTaskGroups.get('',row.id)
  started.candidates[1].status='running'
  let failed=false
  globalThis.testQueueFailure=id=>id.endsWith('-1')&&!failed&&(failed=true)
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
  try {
    await act(async()=>root.render(h(TaskGroupConversation,{initialGroup:started,onBack:()=>{}})))
    await act(async()=>container.querySelectorAll('[aria-label="close"]')[1].click())
    await input(container.querySelector('[aria-label^="broadcastLabel"]'),'Review your result')
    const send=()=>act(async()=>[...container.querySelectorAll('button')].find(row=>row.textContent==='broadcastSend').click())
    await send();assert.match(container.textContent,/不会重复发送/)
    await send()
    const sent=calls.filter(row=>row[0]==='queued')
    assert.equal(sent.filter(row=>row[1].endsWith('-0')).length,1)
    assert.equal(sent.filter(row=>row[1].endsWith('-1')).length,2)
    assert.equal(container.querySelector('[aria-label^="broadcastLabel"]').value,'')
  } finally { delete globalThis.testQueueFailure;await act(async()=>root.unmount());container.remove() }
})

test('main composer blocks multi-agent dispatch when an agent configuration fails and recovers via settings', async () => {
  calls.length=0;groups.clear();window.localStorage.clear();window.localStorage.clear()
  const original=globalThis.testDashboard.getConnectorRuntimeCapabilities
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
  const click=async text=>{const button=[...container.querySelectorAll('button')].find(row=>row.textContent===text);assert.ok(button);await act(async()=>button.click())}
  try {
    await act(async()=>root.render(h(TaskComposer)))
    globalThis.testDashboard.getConnectorRuntimeCapabilities=async (...args)=>{if(args[2]==='codex')throw new Error('Catalog temporarily unavailable');return original(...args)}
    await act(async()=>container.querySelector('[aria-label="agent"]').click())
    await click('codex');await click('drawer-close')
    await input(container.querySelector('textarea[placeholder="placeholder"]'),'Shared task')
    assert.equal(container.querySelector('[aria-label="sendTask"]').disabled,true)
    await click('settings');assert.match(container.textContent,/Catalog temporarily unavailable/)
    globalThis.testDashboard.getConnectorRuntimeCapabilities=original
    await click('retry');await click('drawer-close')
    assert.equal(container.querySelector('[aria-label="sendTask"]').disabled,false)
    assert.equal(calls.some(row=>row[0]==='prepare'||row[0]==='start'),false)
  } finally {globalThis.testDashboard.getConnectorRuntimeCapabilities=original;await act(async()=>root.unmount());container.remove()}
})


test('explicit forward commands dispatch directly without adding a source AI turn', async () => {
  calls.length=0;groups.clear();window.localStorage.clear()
  const row=await globalThis.testTaskGroups.create('',{content:'Original task',candidates:[{runtime:'claude',runtimeId:'claude',selections:{}},{runtime:'codex',runtimeId:'codex',selections:{model:'chosen'}}]})
  await globalThis.testTaskGroups.start('',row.id,0);await globalThis.testTaskGroups.start('',row.id,1)
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
  try {
    await act(async()=>root.render(h(TaskGroupConversation,{initialGroup:await globalThis.testTaskGroups.get('',row.id),onBack:()=>{}})))
    const pane=container.querySelector('[data-session-id="session-a-0"]')
    await input(pane.querySelector('textarea'),'转发给 Codex：请审核未提交的改动')
    await act(async()=>pane.querySelector('[data-chat] button').click())
    const forwarded=calls.find(row=>row[0]==='handoff')
    assert.equal(forwarded[2].instructions,'请审核未提交的改动')
    assert.deepEqual(forwarded[2].target.selections,{model:'chosen'})
    assert.equal(calls.some(row=>row[0]==='message'),false)
    assert.equal(container.querySelectorAll('[data-chat]').length,3)
  } finally { await act(async()=>root.unmount());container.remove() }
})


test('reopening a task restores chained forwards regardless of list order', async () => {
  calls.length=0;groups.clear();window.localStorage.clear()
  const row=await globalThis.testTaskGroups.create('',{content:'Task',candidates:[{runtime:'codex',runtimeId:'codex',selections:{}}]})
  await globalThis.testTaskGroups.start('',row.id,0)
  const child={...structuredClone(row),id:'b'.repeat(40),request:{...row.request,source:{groupId:row.id,slot:0}}}
  const grandchild={...structuredClone(row),id:'c'.repeat(40),request:{...row.request,source:{groupId:child.id,slot:0}}}
  groups.set(child.id,child);groups.set(grandchild.id,grandchild)
  await globalThis.testTaskGroups.start('',child.id,0);await globalThis.testTaskGroups.start('',grandchild.id,0)
  const original=globalThis.testTaskGroups.list
  globalThis.testTaskGroups.list=async()=>({groups:[grandchild,child,row]})
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
  try {
    await act(async()=>root.render(h(TaskGroupConversation,{initialGroup:await globalThis.testTaskGroups.get("",row.id),onBack:()=>{}})))
    assert.equal(container.querySelectorAll('[data-chat]').length,3)
  } finally {globalThis.testTaskGroups.list=original;await act(async()=>root.unmount());container.remove()}
})


test('a failed forward keeps its operation identity when another pane forwards before retry', async () => {
  calls.length=0;groups.clear();window.localStorage.clear()
  const row=await globalThis.testTaskGroups.create('',{content:'Task',candidates:[{runtime:'claude',runtimeId:'claude',selections:{}},{runtime:'codex',runtimeId:'codex',selections:{}}]})
  await globalThis.testTaskGroups.start('',row.id,0);await globalThis.testTaskGroups.start('',row.id,1)
  const original=globalThis.testTaskGroups.handoff;let failed=false
  globalThis.testTaskGroups.handoff=async(...args)=>{const result=await original(...args);if(args[2].slot===0&&!failed){failed=true;throw new Error('Lost response')}return result}
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
  try {
    await act(async()=>root.render(h(TaskGroupConversation,{initialGroup:await globalThis.testTaskGroups.get('',row.id),onBack:()=>{}})))
    const first=container.querySelector('[data-session-id="session-a-0"]');const second=container.querySelector('[data-session-id="session-a-1"]')
    await input(first.querySelector('textarea'),'转发给 Codex：审核')
    await act(async()=>first.querySelector('[data-chat] button').click())
    await input(second.querySelector('textarea'),'转发给 Claude：继续执行')
    await act(async()=>second.querySelector('[data-chat] button').click())
    await act(async()=>first.querySelector('[data-chat] button').click())
    const forwards=calls.filter(row=>row[0]==='handoff')
    assert.equal(forwards.length,3)
    assert.equal(forwards[0][2].operationId,forwards[2][2].operationId)
    assert.notEqual(forwards[0][2].operationId,forwards[1][2].operationId)
  } finally {globalThis.testTaskGroups.handoff=original;await act(async()=>root.unmount());container.remove()}
})


test('ordinary session forwards and opens target in the original project', async () => {
  calls.length = 0
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  globalThis.testWorkspace.openSession = id => calls.push(['open', id])
  globalThis.testTaskGroups.handoffSession = async (_token, id, body) => {
    calls.push(['single-handoff', id, body])
    const row = { id: 'c'.repeat(40), projectId: 'p', phase: 'ready', request: { candidates: [body.target] }, candidates: [pending()] }
    groups.set(row.id, row); return row
  }
  function Ordinary() {
    const forward = useSessionForward('test-token', { id: 'ordinary', projectId: 'p', connectorId: 'c', status: 'idle' }, true)
    return forward.control
  }
  await act(async () => root.render(h(Ordinary)))
  const click = async text => {
    const button = [...container.querySelectorAll('button')].find(row => (row.textContent === text || row.getAttribute('aria-label') === text))
    assert.ok(button, text); assert.equal(button.disabled, false)
    await act(async () => button.click())
  }
  await click('转发给其他 AI')
  assert.match(container.textContent, /当前项目下/)
  await click('发送')
  const sent = calls.find(row => row[0] === 'single-handoff')
  assert.equal(sent[1], 'ordinary')
  assert.equal(sent[2].target.runtime, 'codex')
  assert.ok(calls.some(row => row[0] === 'open' && row[1] === 'session-c-0'))
  assert.equal(calls.filter(row => row[0] === 'start').length, 1)
  await act(async () => root.unmount()); container.remove()
})


test('ordinary session forwards attachments to three configured recipients without creating projects', async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  globalThis.testInitialAttachments = [{ id: 'extra', uploaded: { fileId: 'file_extra' }, uploadStatus: 'uploaded' }]
  const operations = new Map()
  globalThis.testTaskGroups.handoffSession = async (_token, id, body) => {
    calls.push(['single-handoff', id, body])
    if (operations.has(body.operationId)) return operations.get(body.operationId)
    const row = { id: String.fromCharCode(98 + operations.size).repeat(40), projectId: 'p', phase: 'ready', request: { candidates: [body.target] }, candidates: [pending()] }
    operations.set(body.operationId, row); groups.set(row.id, row); return row
  }
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container)
  function Ordinary() { return useSessionForward('test-token', { id: 'ordinary', connectorId: 'c', status: 'idle' }, true).control }
  const click = async text => {
    const button = [...container.querySelectorAll('button')].find(row => (row.textContent === text || row.getAttribute('aria-label') === text))
    assert.ok(button, text); assert.equal(button.disabled, false)
    await act(async () => button.click())
  }
  try {
    await act(async () => root.render(h(Ordinary)))
    await click('转发给其他 AI'); await click('添加目标 AI'); await click('添加目标 AI')
    assert.equal(container.querySelector('[aria-label="目标 AI 3"]').value, 'dsh')
    await click('发送')
    const sent = calls.filter(row => row[0] === 'single-handoff')
    assert.deepEqual(sent.map(row => row[2].target.runtimeId), ['codex', 'claude', 'dsh'])
    assert.ok(sent.every(row => row[1] === 'ordinary' && row[2].attachments[0].fileId === 'file_extra'))
    assert.deepEqual(sent[2][2].target.selections, { model: 'dsh-model-low', permission: 'dsh-permission-read' })
    assert.equal(new Set(sent.map(row => row[2].operationId)).size, 3)
    assert.equal(calls.filter(row => row[0] === 'start').length, 3)
    assert.equal(calls.some(row => row[0] === 'resolveProject'), false)
  } finally { delete globalThis.testInitialAttachments; await act(async () => root.unmount()); container.remove() }
})

test('multi-AI pane uses the same multiple-recipient attachment forwarding dialog', async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  globalThis.testInitialAttachments = [{ id: 'extra', uploaded: { fileId: 'file_extra' }, uploadStatus: 'uploaded' }]
  const row = await globalThis.testTaskGroups.create('', { content: 'Task', candidates: [{ runtime: 'codex', runtimeId: 'codex', selections: {} }] })
  await globalThis.testTaskGroups.start('', row.id, 0)
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container)
  const click = async text => {
    const button = [...container.querySelectorAll('button')].find(row => (row.textContent === text || row.getAttribute('aria-label') === text))
    assert.ok(button, text); assert.equal(button.disabled, false); await act(async () => button.click())
  }
  try {
    await act(async () => root.render(h(TaskGroupConversation, { initialGroup: groups.get(row.id), onBack: () => {} })))
    await act(async () => container.querySelector('[aria-label="forward"]').click())
    await click('添加目标 AI')
    await input(container.querySelector('[aria-label="补充指令"]'), 'Review with the attachment')
    await click('发送')
    const sent = calls.filter(row => row[0] === 'handoff')
    assert.equal(sent.length, 2)
    assert.ok(sent.every(item => item[1] === row.id && item[2].attachments[0].fileId === 'file_extra'))
    assert.equal(container.querySelectorAll('[data-chat]').length, 3)
    assert.equal(calls.some(row => row[0] === 'resolveProject'), false)
  } finally { delete globalThis.testInitialAttachments; await act(async () => root.unmount()); container.remove() }
})

test('partial recipient failure keeps successful recipients and stable operation identities on retry', async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const operations = new Map(); const identities = []; const rows = new Map(); let fail = true
  const targets = ['codex', 'claude'].map(runtime => ({ runtime, runtimeId: runtime, selections: {} }))
  const updates = []
  const options = { token: '', source: 'ordinary', targets, instructions: 'Review', attachments: [{ fileId: 'extra' }], operations, operationScope: 'test-forward-operations',
    create: async (target, operationId) => {
      identities.push([target.runtimeId, operationId])
      if (!rows.has(operationId)) {
        const row = { id: String.fromCharCode(98 + rows.size).repeat(40), candidates: [pending()], request: { candidates: [target] } }
        rows.set(operationId, row); groups.set(row.id, row)
      }
      if (target.runtimeId === 'claude' && fail) { fail = false; throw new Error('Lost response') }
      return rows.get(operationId)
    }, onUpdate: group => updates.push(group.id),
  }
  await assert.rejects(() => forwardToTargets(options), /claude: Lost response/)
  assert.ok(updates.includes('b'.repeat(40)), 'successful recipient stays visible')
  const completed = await forwardToTargets({ ...options, operations: new Map() })
  assert.equal(completed.length, 2)
  assert.deepEqual(identities.slice(0, 2), identities.slice(2))
  assert.equal(rows.size, 2, 'retry reuses both prepared groups')
})


const runtimeNames = { codex: 'Codex', claude: 'Claude Code', dsh: 'DSH' }
for (const sourceRuntime of ['codex', 'claude', 'dsh']) test(`${sourceRuntime} pane command forwards to both other AIs without calling the source model`, async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const row = await globalThis.testTaskGroups.create('', { content: 'Original task', candidates: [{ runtime: sourceRuntime, runtimeId: sourceRuntime, selections: {} }] })
  await globalThis.testTaskGroups.start('', row.id, 0)
  const targets = Object.keys(runtimeNames).filter(name => name !== sourceRuntime)
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container)
  try {
    await act(async () => root.render(h(TaskGroupConversation, { initialGroup: groups.get(row.id), onBack: () => {} })))
    await input(container.querySelector('[data-chat] textarea'), `转发给 ${targets.map(name => runtimeNames[name]).join('、')}：请分别审核`)
    await act(async () => container.querySelector('[data-chat] button').click())
    const sent = calls.filter(row => row[0] === 'handoff')
    assert.deepEqual(sent.map(row => row[2].target.runtimeId), targets)
    assert.ok(sent.every(item => item[1] === row.id && item[2].instructions === '请分别审核'))
    assert.equal(calls.some(row => row[0] === 'message'), false)
    assert.equal(container.querySelectorAll('[data-chat]').length, 3)
  } finally { await act(async () => root.unmount()); container.remove() }
})

for (const sourceRuntime of ['codex', 'claude', 'dsh']) test(`${sourceRuntime} ordinary session command forwards to both other AIs with attachment references`, async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const targets = Object.keys(runtimeNames).filter(name => name !== sourceRuntime)
  globalThis.testTaskGroups.handoffSession = async (_token, sourceId, body) => {
    calls.push(['single-handoff', sourceId, body])
    const row = { id: String.fromCharCode(98 + groups.size).repeat(40), projectId: 'p', request: { candidates: [body.target] }, candidates: [pending()] }
    groups.set(row.id, row); return row
  }
  function Ordinary() {
    const forward = useSessionForward('test-token', { id: `ordinary-${sourceRuntime}`, connectorId: 'c', status: 'idle', runtime: sourceRuntime }, true)
    return h('button', { onClick: async () => calls.push(['command-result', await forward.handleCommand(`转发给 ${targets.map(name => runtimeNames[name]).join('、')}：检查附件`, [{ uploaded: { fileId: 'source-file' } }])]) }, 'command')
  }
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container)
  try {
    await act(async () => root.render(h(Ordinary)))
    await act(async () => container.querySelector('button').click())
    const sent = calls.filter(row => row[0] === 'single-handoff')
    assert.deepEqual(sent.map(row => row[2].target.runtimeId), targets)
    assert.ok(sent.every(row => row[1] === `ordinary-${sourceRuntime}` && row[2].attachments[0].fileId === 'source-file'))
    assert.ok(calls.some(row => row[0] === 'command-result' && row[1] === true))
  } finally { await act(async () => root.unmount()); container.remove() }
})

const pairSessions = ['codex', 'claude', 'dsh'].map(runtime => ({ id: `existing-${runtime}`, projectId: 'p', connectorId: 'c', runtime, runtimeId: runtime, runtimeName: runtimeNames[runtime], status: 'idle', connectorStatus: 'online', archived: false, title: `Existing ${runtime} task` }))
globalThis.testDashboard.listProjectSessions = async () => ({ sessions: pairSessions, hasMore: false, nextCursor: null })
async function changeSelect(element, value) {
  assert.ok(element)
  await act(async () => { element.value = value; element.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
}
async function clickText(container, text) {
  const button = [...container.querySelectorAll('button')].find(row => row.textContent === text || row.getAttribute('aria-label') === text)
  assert.ok(button, text); assert.equal(button.disabled, false); await act(async () => button.click())
}
async function selectPair(container) {
  await changeSelect(container.querySelector('[aria-label="联立会话 1"]'), 'existing-codex')
  await changeSelect(container.querySelector('[aria-label="联立会话 2"]'), 'existing-claude')
  await clickText(container, '联立显示')
}

test('two existing different AI sessions broadcast without creating sessions or projects and restore drafts and panes after page switches', async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const container = document.createElement('div'); document.body.append(container); let root = createRoot(container)
  try {
    await act(async () => root.render(h(JointConversations)))
    await selectPair(container)
    assert.equal(container.querySelectorAll('[data-joint-session]').length, 2)
    assert.equal(container.querySelectorAll('[aria-label="转发给其他 AI"]').length, 2)
    await input(container.querySelector('[aria-label="联立发布"]'), 'Keep my joint draft')
    await act(async () => container.querySelector('[aria-label="收起会话"]').click())
    await act(async () => root.unmount()); root = createRoot(container)
    await act(async () => root.render(h(JointConversations)))
    assert.equal(container.querySelector('[aria-label="联立会话 1"]').value, 'existing-codex')
    assert.equal(container.querySelector('[aria-label="联立会话 2"]').value, 'existing-claude')
    assert.equal(container.querySelector('[aria-label="联立发布"]').value, 'Keep my joint draft')
    assert.ok(container.querySelector('[aria-label="展开会话"]'))
    await clickText(container, '统一发送')
    assert.deepEqual(calls.filter(row => row[0] === 'queued').map(row => row[1]), ['existing-codex', 'existing-claude'])
    assert.equal(calls.some(row => ['prepare', 'start', 'resolveProject', 'single'].includes(row[0])), false)
    assert.equal(container.querySelector('[aria-label="联立发布"]').value, '')
    globalThis.testUserId = 'other-account'
    await act(async () => root.render(h(JointConversations)))
    assert.equal(container.querySelectorAll('[data-joint-session]').length, 0)
    assert.equal(container.querySelector('[aria-label="联立会话 1"]').value, '')
  } finally { delete globalThis.testUserId; await act(async () => root.unmount()); container.remove() }
})

test('a partially accepted joint broadcast can be retried after a page switch without resending to the successful AI', async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  let rejected = false
  globalThis.testQueueFailure = id => id === 'existing-claude' && !rejected && (rejected = true)
  const container = document.createElement('div'); document.body.append(container); let root = createRoot(container)
  try {
    await act(async () => root.render(h(JointConversations))); await selectPair(container)
    await input(container.querySelector('[aria-label="联立发布"]'), 'Send once to each AI')
    await clickText(container, '统一发送')
    assert.match(container.textContent, /不会重复发送/)
    await act(async () => root.unmount()); root = createRoot(container)
    await act(async () => root.render(h(JointConversations)))
    await clickText(container, '统一发送')
    assert.equal(calls.filter(row => row[0] === 'queued' && row[1] === 'existing-codex').length, 1)
    assert.equal(calls.filter(row => row[0] === 'queued' && row[1] === 'existing-claude').length, 2)
  } finally { delete globalThis.testQueueFailure; await act(async () => root.unmount()); container.remove() }
})

test('the persistent joint workspace restores a task group without restarting its paid turns', async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const row = await globalThis.testTaskGroups.create('', { content: 'History task', candidates: ['codex', 'claude'].map(runtime => ({ runtime, runtimeId: runtime, selections: {} })) })
  await globalThis.testTaskGroups.start('', row.id, 0); await globalThis.testTaskGroups.start('', row.id, 1)
  globalThis.testWorkspace.jointGroupId = row.id
  const container = document.createElement('div'); document.body.append(container); let root = createRoot(container)
  try {
    await act(async () => root.render(h(JointConversations)))
    await input(container.querySelector('[aria-label^="broadcastLabel"]'), 'Restore group draft')
    await act(async () => container.querySelector('[aria-label="minimize"]').click())
    await act(async () => root.unmount()); globalThis.testWorkspace.jointGroupId = null; root = createRoot(container)
    await act(async () => root.render(h(JointConversations)))
    assert.equal(container.querySelectorAll('[data-chat]').length, 2)
    assert.equal(container.querySelector('[aria-label^="broadcastLabel"]').value, 'Restore group draft')
    assert.ok(container.querySelector('[aria-label="restore"]'))
    assert.equal(calls.filter(row => row[0] === 'start').length, 2)
  } finally { globalThis.testWorkspace.jointGroupId = null; await act(async () => root.unmount()); container.remove() }
})


for (const sourceRuntime of ['codex', 'claude', 'dsh']) test(`${sourceRuntime} small forward button offers both other AIs instead of the source`, async () => {
  calls.length = 0; groups.clear(); window.localStorage.clear()
  const targets = Object.keys(runtimeNames).filter(name => name !== sourceRuntime)
  globalThis.testTaskGroups.handoffSession = async (_token, sourceId, body) => {
    calls.push(['single-handoff', sourceId, body])
    const row = { id: String.fromCharCode(98 + groups.size).repeat(40), projectId: 'p', request: { candidates: [body.target] }, candidates: [pending()] }
    groups.set(row.id, row); return row
  }
  function Ordinary() { return useSessionForward('test-token', { id: `ordinary-${sourceRuntime}`, connectorId: 'c', status: 'idle', runtimeId: sourceRuntime }, true).control }
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container)
  try {
    await act(async () => root.render(h(Ordinary)))
    await clickText(container, '转发给其他 AI'); await clickText(container, '添加目标 AI')
    const options = [...container.querySelector('[aria-label="目标 AI 1"]').options].map(row => row.value)
    assert.deepEqual(options, targets)
    await clickText(container, '发送')
    assert.deepEqual(calls.filter(row => row[0] === 'single-handoff').map(row => row[2].target.runtimeId), targets)
  } finally { await act(async () => root.unmount()); container.remove() }
})
