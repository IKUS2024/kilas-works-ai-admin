// Execute the actual Stop handler with a delayed cancellation response.
// No browser/provider calls; exposes mutation of a newer request after await.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(process.env.KILAS_WORK_CHAT_SCRIPT||path.join(__dirname,'../static/kilas_ai_agent_chat.js'),'utf8');
const start=source.indexOf("  stop?.addEventListener('click'");
const finish=source.indexOf('  const canAutoFocus',start);
assert.ok(start>=0&&finish>start,'actual Stop handler exists');
function fixture(){
 let click,settle,terminalCalls=0;const requests=[];
 const original=new AbortController();
 const form={elements:{operation_key:{value:'first-key'},csrf_token:{value:'synthetic'}}};
 const context={stop:{addEventListener:(name,fn)=>{assert.equal(name,'click');click=fn;}},controller:original,activeStream:1,fetch:(url,options)=>{requests.push({url,options});return new Promise((resolve,reject)=>settle=error=>error?reject(error):resolve({ok:true}));},form,submission:{terminal:()=>{terminalCalls++;return 'retired-first-key';}},AbortSignal};
 vm.runInNewContext(source.slice(start,finish),context);
 return {context,original,form,requests,click:()=>click(),settle:error=>settle(error),calls:()=>terminalCalls};
}
for(const fails of [false,true])test(`late ${fails?'failed':'successful'} cancel cannot abort or rotate the next request`,async()=>{
 const f=fixture();const pending=f.click();assert.equal(f.original.signal.aborted,true);
 const repeated=f.click();assert.equal(f.requests.length,1,'repeated Stop sends only one cancel');
 assert.equal(f.calls(),1,'operation retired exactly once before await');
 const next=new AbortController();f.context.controller=next;f.context.activeStream=2;f.form.elements.operation_key.value='second-key';
 f.settle(fails?new Error('synthetic timeout'):null);await pending;await repeated;
 assert.equal(next.signal.aborted,false);assert.equal(f.form.elements.operation_key.value,'second-key');assert.equal(f.calls(),1);
 assert.equal(f.requests[0].url,'/kilas-ai/work/streams/1/cancel');assert.equal(f.requests[0].options.method,'POST');
 assert.equal(f.requests[0].options.headers['X-CSRF-Token'],'synthetic');
});
test('Stop with no stream aborts current request; idle Stop does nothing',async()=>{
 const f=fixture();f.context.activeStream=null;await f.click();assert.equal(f.original.signal.aborted,true);assert.equal(f.requests.length,0);assert.equal(f.calls(),1);
 f.context.controller=null;await f.click();assert.equal(f.calls(),1);
});
