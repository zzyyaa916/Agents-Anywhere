import assert from 'node:assert/strict'
import test from 'node:test'
import { registerHooks } from 'node:module'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://test.example/' })
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event']) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { createElement: h, act } = await import('react')
const { createRoot } = await import('react-dom/client')
let failure = false
const calls = []
globalThis.readinessCatalog = async () => { calls.push('catalog'); if (failure) throw Error('Sign in again'); return {catalog:{models:[{},{}]}} }
globalThis.readinessRetry = async () => { calls.push('retry') }
const source = registerSource()
const hook = registerHooks({load(url, context, next) {
  const mocks = {
    '/components/auth/auth-context.tsx': 'export const useAuth=()=>({session:{accessToken:"test-only"}})',
    '/components/account-usage.tsx': 'export const useAccountUsage=()=>({data:{snapshots:[{fetchedAt:"2026-01-01",stale:true,bindings:[{connectorId:"device",runtimeId:"codex"}]}]}})',
    '/features/dashboard/api.ts': 'export const dashboardApi={getConnectorRuntimeModelCatalog:()=>globalThis.readinessCatalog()}',
    '/features/model-config/api.ts': 'export const modelConfigApi={retryChannel:()=>globalThis.readinessRetry()}',
    '/components/ui/button.tsx': 'import * as React from "react";export const Button=({children,variant,size,...props})=>React.createElement("button",props,children)',
  }
  for (const [path, text] of Object.entries(mocks)) if(url.endsWith(path)) return {format:'module',shortCircuit:true,source:text}
  if(url.includes('/next-intl/') || url.endsWith('/next-intl')) return {format:'module',shortCircuit:true,source:'export const useTranslations=()=> (key,values)=>key+(values?.count??"")'}
  return next(url,context)
}})
const { RuntimeReadiness } = await import('../src/components/runtime-readiness.tsx')
hook.deregister();source.deregister()

test('failed channel retry is scoped and old model success is discarded after a runtime update', async () => {
  const container=document.createElement('div');document.body.append(container)
  const root=createRoot(container)
  const runtime={connectorId:'device',runtimeId:'codex',status:'running',updatedAt:'one'}
  const channel={state:'failed',updatedAt:'one'}
  const render=async (value)=>act(async()=>root.render(h(RuntimeReadiness,{runtime:value,channel,onChanged:()=>calls.push('refresh')})))
  await render(runtime)
  assert.match(container.textContent,/channelFailed/)
  assert.match(container.textContent,/accountStale/)
  assert.match(container.textContent,/modelsUnknown/)
  await act(async()=>container.querySelector('button').click())
  assert.deepEqual(calls,['retry','refresh','catalog'])
  assert.match(container.textContent,/modelsReady2/)
  await render({...runtime,updatedAt:'two'})
  assert.match(container.textContent,/modelsUnknown/)
  failure=true
  await act(async()=>container.querySelector('button').click())
  assert.match(container.textContent,/modelsFailed/)
  assert.equal(container.querySelector('[role="alert"]').textContent,'Sign in again')
  await act(async()=>root.unmount())
})
