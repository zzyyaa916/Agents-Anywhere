import assert from 'node:assert/strict'
import test from 'node:test'
import { registerSource } from './helpers/onboarding-source.mjs'
const hook=registerSource()
const {DashboardApi}=await import('../src/features/dashboard/api.ts')
hook.deregister()

test('public API preserves empty and long exact raw without splitting >32 words',async()=>{
  const requests=[]
  const client={post:async(path,body)=>{requests.push({path,body});return {ok:true,result:{executionState:'accepted'}}},get:async(path)=>{requests.push({path});return {commands:[]}}}
  const api=new DashboardApi(client)
  const raw=`/feedback ${Array.from({length:50},(_,i)=>`word${i}`).join(' ')}\ncontinued  `
  await api.sendSessionCommand('token','s1','feedback',{args:[raw.slice('/feedback '.length)],raw})
  await api.sendSessionCommand('token','s1','feedback',{args:['ignored'],raw:''})
  await api.getSessionCommands('token','s1',{query:'goal status',limit:1000})
  assert.deepEqual(requests[0].body,{command:'feedback',args:[raw.slice('/feedback '.length)],raw})
  assert.equal(requests[1].body.raw,'')
  assert.equal(requests[2].path,'/sessions/s1/runtime/commands?query=goal+status&limit=1000')
})


test('supplements use existing steer endpoint and preserve attachment and message identity',async()=>{
  const calls=[]
  const api=new DashboardApi({post:async(path,body)=>{calls.push({path,body});return {ok:true}}})
  const options={clientMessageId:'same-message',attachments:[{fileId:'file-1'}]}
  await api.sendSessionMessage('synthetic','session/id','extra detail',{...options,steer:true})
  await api.sendSessionMessage('synthetic','session/id','new turn',options)
  assert.deepEqual(calls,[{path:'/sessions/session%2Fid/runtime/steer',body:{content:'extra detail',...options}},{path:'/sessions/session%2Fid/runtime/messages',body:{content:'new turn',...options}}])
})
