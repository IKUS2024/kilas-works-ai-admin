import test from 'node:test';
import assert from 'node:assert/strict';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs';
function fixture(json){
 const states=[],requests=[];
 const session=new GeminiSession({json:async(url,options)=>{requests.push({url,options});return json(url,options);},capture:{cancel(){}},player:{cancel(){}},onState:state=>states.push(state),readRetries:2});
 session.active=true;session.controller=new AbortController();session.turn={cursor:4};session.pause=async()=>{};
 return {session,states,requests};
}
test('two bounded read reconnects retain session/cursor and never replay audio or admission',async()=>{
 let attempts=0;const f=fixture(()=>{if(attempts++<2)throw new TypeError('network');return {frames:[],next_index:4};});
 const result=await f.session.readSnapshot(0,f.session.turn,'/owned?after=4');
 assert.equal(result.next_index,4);assert.equal(f.requests.length,3);assert.ok(f.requests.every(r=>r.url==='/owned?after=4'&&!r.options.method));assert.equal(f.states.filter(s=>s==='reconnecting').length,2);
});
test('retry bound and authentication failures do not open a replacement provider session',async()=>{
 for(const error of [new TypeError('network'),Object.assign(Error(),{code:'auth_required'})]){
  const f=fixture(()=>{throw error;});await assert.rejects(f.session.readSnapshot(0,f.session.turn,'/owned?after=4'));
  assert.equal(f.requests.length,error.code?1:3);
 }
});
test('End during reconnect stops immediately and prevents a delayed read from resuming',async()=>{
 const f=fixture(()=>{throw new TypeError('network');});let release;
 f.session.pause=()=>new Promise(resolve=>{release=resolve;});
 const result=f.session.readSnapshot(0,f.session.turn,'/owned?after=4');await new Promise(resolve=>setImmediate(resolve));
 await f.session.end();release();await assert.rejects(result,{name:'AbortError'});assert.equal(f.requests.length,1);assert.equal(f.session.active,false);
});
