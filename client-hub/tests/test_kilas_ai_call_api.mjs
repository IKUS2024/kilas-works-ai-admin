import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {requestCallJSON} from '../static/kilas_ai_call_api.mjs';

test('Call readiness sends JSON and CSRF over HTTP while microphone chunks preserve binary PCM',async t=>{
 const received=[];
 const server=createServer(async(req,res)=>{
  const parts=[];for await(const part of req)parts.push(part);
  received.push({path:req.url,headers:req.headers,body:Buffer.concat(parts)});
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(req.url==='/ready'?{ready:true}:{accepted_index:0}));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(()=>new Promise(resolve=>server.close(resolve)));
 const base='http://127.0.0.1:'+server.address().port;
 const ready=await requestCallJSON(base+'/ready',{method:'POST',csrf:'synthetic-csrf',json:{language:'id',user_started_speaking:true}});
 const raw=new Uint8Array([1,0,255,127,0,128]);
 await requestCallJSON(base+'/chunks/0',{method:'POST',csrf:'synthetic-csrf',body:raw});
 assert.deepEqual(ready,{ready:true});
 assert.equal(received[0].headers['content-type'],'application/json');assert.equal(received[0].headers['x-csrf-token'],'synthetic-csrf');
 assert.deepEqual(JSON.parse(received[0].body),{language:'id',user_started_speaking:true});
 assert.deepEqual(received[1].body,Buffer.from(raw));assert.equal(received[1].headers['x-csrf-token'],'synthetic-csrf');assert.equal(received[1].headers['content-type'],undefined);
});
