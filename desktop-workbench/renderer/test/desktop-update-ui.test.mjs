import assert from 'node:assert/strict'
import test from 'node:test'
import { registerHooks } from 'node:module'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'
const dom = new JSDOM('<html><body></body></html>', {url:'https://test.example/'})
for (const name of ['window','document','navigator','HTMLElement','Element','Node','Event']) Object.defineProperty(globalThis,name,{configurable:true,value:dom.window[name]})
globalThis.IS_REACT_ACT_ENVIRONMENT=true
const {createElement:h,act}=await import('react')
const {createRoot}=await import('react-dom/client')
const calls=[]
let state={revision:1,currentVersion:'2.5.6',available:false,checking:false,phase:'idle',dialogOpen:false}
let receive
let poll
const originalInterval=globalThis.setInterval
const originalClear=globalThis.clearInterval
globalThis.setInterval=(fn)=>{poll=fn;return 1}
globalThis.clearInterval=()=>{}
globalThis.updateBridge={updates:{
  syncSession:async(server)=>{calls.push(server?'check':'logout');return state},
  onState:fn=>{receive=fn;return ()=>{}},
  open:async()=>{calls.push('open');state={...state,revision:state.revision+1,dialogOpen:true};return state},
  download:async()=>{calls.push('download');return state},
  ignore:async()=>state,
}}
globalThis.updateToast={success:key=>calls.push(key),error:key=>calls.push(key)}
const source=registerSource()
const hooks=registerHooks({load(url,context,next){
  const mocks={
    '/components/auth/auth-context.tsx':'export const useAuth=()=>({session:{userId:"user",serverUrl:"https://server.test"},isAuthenticated:true,loading:false,screen:"app"})',
    '/features/desktop/bridge.ts':'export const getDesktopWorkbenchBridge=()=>globalThis.updateBridge',
    '/components/ui/button.tsx':'import * as React from "react";export const Button=({children,variant,size,...props})=>React.createElement("button",props,children)',
    '/components/ui/dialog.tsx':'import * as React from "react";export const Dialog=({open,children})=>open?React.createElement("div",null,children):null;export const DialogContent=({children})=>React.createElement("div",null,children);export const DialogDescription=DialogContent;export const DialogFooter=DialogContent;export const DialogHeader=DialogContent;export const DialogTitle=DialogContent',
    '/components/ui/badge.tsx':'export const Badge=()=>null',
    '/components/ui/progress.tsx':'export const Progress=()=>null',
    '/components/ui/spinner.tsx':'export const Spinner=()=>null',
  }
  for(const [path,text]of Object.entries(mocks))if(url.endsWith(path))return {format:'module',shortCircuit:true,source:text}
  if(url.includes('/next-intl/')||url.endsWith('/next-intl'))return {format:'module',shortCircuit:true,source:'export const useTranslations=()=>key=>key'}
  if(url.includes('/sonner/'))return {format:'module',shortCircuit:true,source:'export const toast=globalThis.updateToast'}
  return next(url,context)
}})
const {DesktopUpdateProvider,DesktopUpdateButton}=await import('../src/features/desktop/desktop-update-provider.tsx')
hooks.deregister();source.deregister()

test('update entry always exists; manual and periodic checks discover releases and wire download/install',async()=>{
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
  try {
    await act(async()=>root.render(h(DesktopUpdateProvider,null,h(DesktopUpdateButton))))
    assert.ok(container.querySelector('[aria-label="check"]'))
    await act(async()=>container.querySelector('button').click())
    assert.ok(calls.includes('upToDate'))
    state={...state,revision:2,available:true,latestVersion:'2.5.7'}
    await act(async()=>poll())
    assert.ok(container.querySelector('[aria-label="entry"]'))
    await act(async()=>container.querySelector('button').click())
    assert.ok(calls.includes('open'))
    assert.match(container.textContent,/updateNow/)
    await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='updateNow').click())
    assert.ok(calls.includes('download'))
  } finally {
    await act(async()=>root.unmount());globalThis.setInterval=originalInterval;globalThis.clearInterval=originalClear
  }
})
