// Offline DOM/SDK simulation: no Facebook SDK or HTTP loaded.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/whatsapp_signup.js'), 'utf8');
function harness() {
  let listener, click, callback, options, calls = [], fail = false;
  const elements = {
    'wa-config': {textContent: JSON.stringify({appId:'1', configId:'2', version:'v21.0', state:'nonce',endpoint:'/complete'})},
    'wa-signup': {disabled:true,addEventListener: (_,fn)=>click=fn},
    'wa-status': {textContent:''}, 'wa-csrf': {value:'csrf'}
  };
  const context = {document: {getElementById:id=>elements[id],createElement:()=>({}),head:{appendChild:()=>{}}},
    window: {addEventListener:(_,fn)=>listener=fn},
    FB: {init:()=>{},login:(fn,opts)=>{callback=fn;options=opts;}},
    fetch:async (url,opts)=>{calls.push([url,opts]);if(fail) throw Error('offline');return {ok:true,json:async()=>({message:'Kilas Brain aktif.'})};}
  };
  vm.runInNewContext(source, context);context.window.fbAsyncInit();
  return {click:()=>click(), code:()=>callback({authResponse:{code:'private'}}),
    finish:(origin='https://www.facebook.com',event='FINISH',data={waba_id:'5',phone_number_id:'6'})=>listener({origin,data:JSON.stringify({type:'WA_EMBEDDED_SIGNUP',event,data})}),
    calls,elements,get options(){return options;},fail:()=>fail=true};
}
(async()=>{
  let h = harness(); assert.equal(h.calls.length,0); console.log('PASS page load zero HTTP');
  h.click();h.code();assert.equal(h.calls.length,0);h.finish();await new Promise(setImmediate);
  assert.equal(h.calls.length,1);assert.equal(h.elements['wa-status'].textContent,'Kilas Brain aktif.');
  assert.equal(h.options.extras.featureType,'whatsapp_business_app_onboarding');
  assert.equal(JSON.stringify(h.options.extras.setup),'{}');console.log('PASS v4 code-first completion');
  h.finish();h.click();assert.equal(h.calls.length,1);console.log('PASS duplicate events no second request');
  h=harness();h.click();h.finish();assert.equal(h.calls.length,0);h.code();await new Promise(setImmediate);assert.equal(h.calls.length,1);console.log('PASS assets-first completion');
  h=harness();h.click();h.code();h.finish('https://evilfacebook.com');h.finish('https://facebook.com.evil.test');assert.equal(h.calls.length,0);console.log('PASS strict Meta origins');
  h=harness();h.click();h.finish('https://www.facebook.com','CANCEL');h.code();assert.equal(h.calls.length,0);console.log('PASS cancellation');
  h=harness();h.click();h.code();h.finish('https://www.facebook.com','FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING',{waba_id:'5'});await new Promise(setImmediate);
  assert.equal(h.calls.length,1);let body=JSON.parse(h.calls[0][1].body);assert.equal(body.coexistence,true);assert.equal(body.phone_number_id,null);console.log('PASS coexistence completion without phone id');
  h=harness();h.click();h.code();h.finish('https://www.facebook.com','FINISH',{waba_id:'5',is_wa_login_user:true});await new Promise(setImmediate);
  assert.equal(h.calls.length,1);body=JSON.parse(h.calls[0][1].body);assert.equal(body.coexistence,true);console.log('PASS coexistence FINISH compatibility');
  h=harness();h.fail();h.click();h.code();h.finish();await new Promise(setImmediate);assert.equal(h.calls.length,1);h.click();assert.equal(h.calls.length,1);console.log('PASS no automatic retry on failure');
})().catch(e=>{console.error(e);process.exit(1);});
