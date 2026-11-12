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
const source = registerSource()
const hooks = registerHooks({ load(url, context, next) {
  const mocks = {
    '/hooks/use-mobile.ts': 'export const useIsMobile=()=>Boolean(globalThis.testHeaderMobile)',
    '/components/workspace-context.tsx': 'export const useWorkspace=()=>({renameSession:async()=>true,panels:{},setPanelMode:()=>{}})',
    '/components/workspace-header.tsx': 'import * as React from "react";export const WorkspaceHeader=({children})=>React.createElement("header",null,children)',
    '/components/dashboard-sidebar-toggle.tsx': 'export const DashboardSidebarToggle=()=>null',
    '/components/ui/button.tsx': 'import * as React from "react";export const Button=({children,variant,size,...props})=>React.createElement("button",props,children)',
    '/components/ui/badge.tsx': 'import * as React from "react";export const Badge=({children})=>React.createElement("span",null,children)',
    '/components/ui/input.tsx': 'import * as React from "react";export const Input=props=>React.createElement("input",props)',
    '/components/ui/tooltip.tsx': 'export const Tooltip=({children})=>children;export const TooltipTrigger=Tooltip;export const TooltipContent=Tooltip;export const TooltipProvider=Tooltip',
    '/components/ui/hover-card.tsx': 'export const HoverCard=({children})=>children;export const HoverCardContent=HoverCard;export const HoverCardTrigger=HoverCard',
  }
  for (const [path, text] of Object.entries(mocks)) if (url.endsWith(path)) return { format: 'module', shortCircuit: true, source: text }
  if (url.includes('/next-intl/') || url.endsWith('/next-intl')) return { format: 'module', shortCircuit: true, source: 'export const useTranslations=()=>key=>key' }
  return next(url, context)
} })
const { SessionViewHeader } = await import('../src/components/session-view-header.tsx')
hooks.deregister(); source.deregister()

for (const [mobile, portals] of [[false, true], [false, false], [true, true]]) test(`forward control stays inside the ${mobile ? 'page header' : 'session pane'} with portals=${portals} and remains clickable`, async () => {
  globalThis.testHeaderMobile = mobile
  const container = document.createElement('div')
  const title = document.createElement('div'); title.dataset.slot = 'desktop-shell-header-session'
  const actions = document.createElement('div'); actions.dataset.slot = 'desktop-shell-header-session-actions'
  document.body.append(container)
  if (portals) document.body.append(title, actions)
  const root = createRoot(container); let clicked = 0
  try {
    await act(async () => root.render(h(SessionViewHeader, {
      session: { id: 's', title: 'Task', runtime: 'codex', connectorId: 'c', connectorStatus: 'online', status: 'idle' },
      memorySnapshot: null, toolsOpen: false, toolsExpanded: false, toolsOverlayWidth: 0, toolsMotionEnabled: false, onToggleTools: () => {},
      forwardControl: h('button', { 'aria-label': 'forward-test', onClick: () => { clicked++ } }, '转发给其他 AI'),
    })))
    const host = mobile ? container : container.querySelector('[data-slot="session-forward-toolbar"]')
    assert.ok(host, 'desktop forwarding must have a toolbar inside the session pane')
    assert.equal(actions.querySelector('[aria-label="forward-test"]'), null, 'forwarding must not share the global tool sidebar actions')
    if (!mobile && portals) assert.ok(actions.querySelector('[data-slot="session-tool-sidebar-toggle"]'), 'the tool sidebar control stays in the window header')
    const button = host.querySelector('[aria-label="forward-test"]')
    assert.ok(button, 'the active header branch must render the forwarding control')
    assert.equal(document.querySelectorAll('[aria-label="forward-test"]').length, 1)
    await act(async () => button.click())
    assert.equal(clicked, 1)
  } finally { await act(async () => root.unmount()); container.remove(); title.remove(); actions.remove(); delete globalThis.testHeaderMobile }
})
