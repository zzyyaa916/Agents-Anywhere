import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { registerSource } from './helpers/onboarding-source.mjs'
const dom=new JSDOM('<html><body></body></html>',{url:'https://queue.example/'})
for(const key of ['window','document','navigator','HTMLElement','Element','Node','localStorage']) Object.defineProperty(globalThis,key,{configurable:true,value:dom.window[key]})
globalThis.IS_REACT_ACT_ENVIRONMENT=true
const React=await import('react')
const {createElement:h,act,StrictMode}=React
const {createRoot}=await import('react-dom/client')
const hook=registerSource()
const {useSessionMessageQueue}=await import('../src/components/session/use-session-message-queue.ts')
const {useConversationBroadcast}=await import('../src/features/task-groups/use-conversation-broadcast.ts')
hook.deregister()
let queue
function Host(props){queue=useSessionMessageQueue(props);return h('span',{},queue.items.map(item=>item.text).join('|'))}
async function mount(t,props,strict=false){
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const render=async next=>act(async()=>root.render(strict?h(StrictMode,{},h(Host,next)):h(Host,next)))
 await render(props)
 t.after(async()=>{await act(async()=>root.unmount());container.remove()})
 return {root,render}
}

test('saved queues restore paused, preserve message identity and require explicit resume',async t=>{
 const scope='queue:server:user:session:restore';const calls=[]
 const props={scope,canSend:false,canSteer:false,onSend:async(text,files,options)=>{calls.push({text,options});return true}}
 const mounted=await mount(t,props)
 await act(async()=>{assert.equal(queue.enqueue('supplement',[]),true)})
 const id=queue.items[0].id
 assert.equal(calls.length,0)
 await mounted.render({...props,scope:'another-session',canSend:true})
 assert.equal(queue.items.length,0);assert.equal(calls.length,0)
 await mounted.render({...props,canSend:true})
 assert.equal(queue.paused,true);assert.equal(calls.length,0)
 await act(async()=>queue.resume())
 assert.deepEqual(calls,[{text:'supplement',options:{clientMessageId:id,steer:false}}])
 assert.equal(queue.items.length,0);assert.equal(localStorage.getItem(scope),null)
})

test('failed supplements are retained and never automatically retried',async t=>{
 const scope='queue:failure';let attempts=0
 const props={scope,canSend:false,canSteer:true,onSend:async()=>{attempts++;return false}}
 const mounted=await mount(t,props)
 await act(async()=>queue.enqueue('keep me',[]))
 const id=queue.items[0].id
 await act(async()=>queue.deliver(id,true))
 assert.equal(attempts,1);assert.equal(queue.items[0].status,'failed')
 await mounted.render({...props,canSend:true})
 assert.equal(attempts,1);assert.equal(queue.items[0].id,id)
 await act(async()=>queue.remove(id))
 assert.equal(queue.items.length,0)
})

test('Strict Mode and double clicks admit exactly one in-flight send',async t=>{
 const scope='queue:double';let release,attempts=0
 await mount(t,{scope,canSend:false,canSteer:true,onSend:async()=>{attempts++;return new Promise(resolve=>release=resolve)}},true)
 await act(async()=>queue.enqueue('one',[]))
 const id=queue.items[0].id;let pending
 await act(async()=>{pending=queue.deliver(id,true);await queue.deliver(id,true)})
 assert.equal(attempts,1);assert.equal(queue.items[0].status,'sending')
 await act(async()=>{release(true);await pending})
 assert.equal(queue.items.length,0)
})

test('storage failure does not accept or erase the pending draft',async t=>{
 await mount(t,{scope:'queue:full',canSend:false,canSteer:false,onSend:async()=>true})
 t.mock.method(dom.window.Storage.prototype,'setItem',()=>{throw new Error('storage quota')})
 await act(async()=>assert.equal(queue.enqueue('do not lose',[]),false))
 assert.equal(queue.items.length,0);assert.equal(queue.error,'storage')
})

test('restored in-flight messages require manual review, not an automatic replay',async t=>{
 const scope='queue:unknown'
 localStorage.setItem(scope,JSON.stringify([{id:'stable-id',text:'unknown outcome',attachments:[],status:'sending'}]))
 let attempts=0
 await mount(t,{scope,canSend:true,canSteer:false,onSend:async()=>{attempts++;return true}})
 assert.equal(queue.paused,true);assert.equal(queue.items[0].status,'failed');assert.equal(attempts,0)
 await act(async()=>queue.resume())
 assert.equal(attempts,0)
})


test('queued messages drain in order only as each task becomes idle',async t=>{
 const scope='queue:fifo';const calls=[],replies=[]
 const props={scope,canSend:false,canSteer:false,onSend:async text=>{calls.push(text);return new Promise(resolve=>replies.push(resolve))}}
 const mounted=await mount(t,props)
 await act(async()=>{queue.enqueue('first',[]);queue.enqueue('second',[])})
 await mounted.render({...props,canSend:true})
 assert.deepEqual(calls,['first'])
 await mounted.render(props)
 await act(async()=>replies[0](true))
 assert.equal(queue.items[0].text,'second');assert.deepEqual(calls,['first'])
 await mounted.render({...props,canSend:true})
 assert.deepEqual(calls,['first','second'])
 await mounted.render(props)
 await act(async()=>replies[1](true))
 assert.equal(queue.items.length,0)
})

test('stopping the current task pauses rather than discards pending messages',async t=>{
 const props={scope:'queue:stop',canSend:false,canSteer:false,onSend:async()=>{assert.fail('paused queue must not send')}}
 const mounted=await mount(t,props)
 await act(async()=>queue.enqueue('wait for me',[]))
 await act(async()=>queue.pause())
 await mounted.render({...props,canSend:true})
 assert.equal(queue.items.length,1);assert.equal(queue.paused,true)
})

test('uploaded attachment references survive restore without copying local file bytes',async t=>{
 const scope='queue:attachment';const props={scope,canSend:false,canSteer:false,onSend:async()=>true}
 const mounted=await mount(t,props)
 const file={id:'attachment',name:'note.txt',type:'file',size:12,mediaType:'text/plain',file:new File(['private bytes'],'note.txt'),uploadStatus:'uploaded',uploaded:{fileId:'uploaded-file',sessionId:'session',name:'note.txt',size:12,mediaType:'text/plain'}}
 await act(async()=>queue.enqueue('read note',[file]))
 assert.doesNotMatch(localStorage.getItem(scope),/private bytes/)
 await mounted.render({...props,scope:'queue:other'})
 await mounted.render(props)
 assert.equal(queue.items[0].attachments[0].uploaded.fileId,'uploaded-file')
 assert.equal(queue.items[0].attachments[0].file.size,0)
})


test('error recovery permits explicit continuation without automatically retrying work',async t=>{
 const calls=[]
 await mount(t,{scope:'queue:error-recovery',canSend:true,canSteer:false,autoSend:false,onSend:async text=>{calls.push(text);return true}})
 await act(async()=>queue.enqueue('continue after reset',[]))
 assert.equal(calls.length,0)
 await act(async()=>queue.deliver(queue.items[0].id,false))
 assert.deepEqual(calls,['continue after reset']);assert.equal(queue.items.length,0)
})


test('storage failure after acceptance cannot leave a message permanently sending',async t=>{
 const scope='queue:cleanup-failed'
 await mount(t,{scope,canSend:false,canSteer:true,onSend:async()=>true})
 await act(async()=>queue.enqueue('accepted',[]))
 const id=queue.items[0].id
 t.mock.method(dom.window.Storage.prototype,'removeItem',()=>{throw new Error('blocked storage')})
 await act(async()=>queue.deliver(id,true))
 assert.equal(queue.items.length,0);assert.equal(queue.error,'storage')
 assert.equal(JSON.parse(localStorage.getItem(scope))[0].status,'sending')
})


test('joint queue registration settles and navigation can unmount both panes',async t=>{
 let renders=0,broadcast
 const props={canSend:false,canSteer:false,onSend:async()=>true}
 function Pane({id,onQueueReady}){
  const current=useSessionMessageQueue({...props,scope:'queue:joint-regression:'+id})
  React.useEffect(()=>{onQueueReady(text=>current.enqueue(text,[]));return()=>onQueueReady(null)},[onQueueReady,current.enqueue])
  return h('span',{},id)
 }
 function JointHost(){
  assert.ok(++renders<30,'joint queue registration must settle instead of repeatedly rendering')
  const [page,setPage]=React.useState('joint')
  broadcast=useConversationBroadcast('joint-registration-test',['a','b'])
  return h('div',{},h('button',{onClick:()=>setPage('home')},'navigate-home'),page==='joint'
   ? ['a','b'].map(id=>h(Pane,{key:id,id,onQueueReady:broadcast.registerQueue(id)})) : h('p',{},'home-page'))
 }
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 t.after(async()=>{await act(async()=>root.unmount());container.remove()})
 await act(async()=>root.render(h(JointHost)))
 assert.equal(broadcast.ready,true)
 await act(async()=>container.querySelector('button').click())
 assert.ok(container.textContent.includes('home-page'))
 assert.equal(broadcast.ready,false)
})
