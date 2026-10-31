import test from 'node:test';
import assert from 'node:assert/strict';
import {pollOperation} from '../static/kilas_copilot.mjs';
test('polls are read-only; repeated snapshots do not redraw; final result terminates',async()=>{
 const previous=globalThis.fetch;let calls=0;const seen=[];
 const views=[{state:'processing',version:1,text:'A'},{state:'processing',version:1,text:'A'},{state:'complete',version:2,result:{turn:{reply:'Answer'}}}];
 globalThis.fetch=async(url,options)=>{assert.equal(url,'/owned-status');assert.equal(options.method,undefined);calls++;return {ok:true,json:async()=>views.shift()};};
 try{await pollOperation('/owned-status',view=>seen.push(view),new AbortController().signal);assert.equal(calls,3);assert.equal(seen.length,2);assert.equal(seen[1].result.turn.reply,'Answer');}finally{globalThis.fetch=previous;}
});
test('cancel interrupts delay and never retries a paid submission',async()=>{
 const previous=globalThis.fetch;const controller=new AbortController();let calls=0;
 globalThis.fetch=async()=>{calls++;return {ok:true,json:async()=>({state:'processing',version:0})};};
 try{await assert.rejects(pollOperation('/status',()=>controller.abort(),controller.signal),/cancelled/);assert.equal(calls,1);}finally{globalThis.fetch=previous;}
});
test('network or provider failure is terminal; there is no implicit resubmission',async()=>{
 const previous=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;return {ok:true,json:async()=>({state:'failed',code:'capacity_unavailable'})};};
 try{await assert.rejects(pollOperation('/status',()=>{},new AbortController().signal),/capacity_unavailable/);assert.equal(calls,1);}finally{globalThis.fetch=previous;}
});
