import assert from 'node:assert/strict'
import test from 'node:test'
import {readFileSync} from 'node:fs'
import {JSDOM} from 'jsdom'
import {registerSource} from './helpers/onboarding-source.mjs'
const dom=new JSDOM('<html><body></body></html>',{url:'https://fixture.example/',pretendToBeVisual:true})
for(const key of ['window','document','navigator','HTMLElement','HTMLInputElement','HTMLButtonElement','Element','Node','NodeFilter','Event','CustomEvent','MutationObserver','getComputedStyle','requestAnimationFrame','cancelAnimationFrame'])Object.defineProperty(globalThis,key,{configurable:true,value:dom.window[key]})
HTMLElement.prototype.scrollIntoView=()=>{}
globalThis.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}}
globalThis.IS_REACT_ACT_ENVIRONMENT=true
const {createElement:h,act}=await import('react')
const {createRoot}=await import('react-dom/client')
const {NextIntlClientProvider}=await import('next-intl')
const hooks=registerSource()
const {FileBrowserDialog}=await import('../src/components/workspace-file-browser-dialog.tsx')
const {dashboardApi}=await import('../src/features/dashboard/api.ts')
hooks.deregister()
const messages=JSON.parse(readFileSync(new URL('../messages/en.json',import.meta.url),'utf8'))

test('Windows workspace picker reaches drive roots, switches drives and refreshes the drive list',async t=>{
 const calls=[];let confirmed
 t.mock.method(dashboardApi,'connectorFsList',async(token,connector,body)=>{
  calls.push(body)
  if(body.path==='')return{ok:true,result:{path:'',entries:[{name:'C:',path:'C:/',type:'directory'},{name:'D:',path:'D:/',type:'directory'}]}}
  const path=body.root==='~'?'C:\\Users':body.root
  return{ok:true,result:{path,entries:[]}}
 })
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 t.after(async()=>{await act(async()=>root.unmount());container.remove()})
 await act(async()=>root.render(h(NextIntlClientProvider,{locale:'en',messages,timeZone:'UTC'},h(FileBrowserDialog,{open:true,onOpenChange(){},connectorId:'device',token:'synthetic',initialPath:'~',onConfirm:path=>confirmed=path}))))
 const parent=()=>[...document.querySelectorAll('button')].find(button=>button.getAttribute('aria-label')===messages.dashboard.workspacePicker.parent)
 const click=async button=>{assert.ok(button);await act(async()=>button.click())}
 await click(parent())
 assert.deepEqual(calls.at(-1),{root:'C:/',path:'.'})
 await click(parent())
 assert.deepEqual(calls.at(-1),{root:'~',path:''})
 assert.match(document.body.textContent,/Drives/)
 await click([...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===messages.dashboard.workspacePicker.refresh))
 assert.equal(calls.at(-1).path,'')
 await click([...document.querySelectorAll('button')].find(b=>b.textContent==='D:'))
 assert.deepEqual(calls.at(-1),{root:'D:/',path:'.'})
 await click([...document.querySelectorAll('button')].find(b=>b.textContent===messages.dashboard.workspacePicker.openWorkspace))
 assert.equal(confirmed,'D:/')
})
