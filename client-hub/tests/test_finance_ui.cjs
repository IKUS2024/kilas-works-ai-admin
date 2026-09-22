const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/finance_ui.js'),'utf8');
function setup(forms=[]){
 const handlers={},dialogs={};
 const document={
  addEventListener(name,callback){handlers[name]=callback;},
  querySelector(){return {dataset:{financeMonth:'2026-08',financeCurrency:'USD'}};},
  querySelectorAll(){return forms;},
  createElement(){return {};},
  getElementById(id){return dialogs[id];}
 };
 vm.runInNewContext(source,{document,URL,location:{href:'https://finance.test/business/1/finance',origin:'https://finance.test'}});
 return {handlers,dialogs};
}
test('dashboard context changes submit through existing live-period handler',()=>{
 const {handlers}=setup();let live=0,normal=0;
 const form={matches:()=>true,requestSubmit(){live++;},submit(){normal++;}};
 handlers.change({target:{closest:()=>({form})}});
 assert.equal(live,1);assert.equal(normal,0);
 form.matches=()=>false;handlers.change({target:{closest:()=>({form})}});
 assert.equal(live,1);assert.equal(normal,1);
});
test('GET filters preserve context and explicit selections; POST fields remain unchanged',()=>{
 const form=(method,fields={},action='https://finance.test/business/1/finance/payees')=>({
  method,action,fields,elements:{namedItem:key=>fields[key]},append(input){fields[input.name]=input;}
 });
 const get=form('get'),explicit=form('get',{month:{value:'2026-07'},display_currency:{value:'IDR'}}),post=form('post'),other=form('get',{},'https://finance.test/account');
 setup([get,explicit,post,other]);
 assert.equal(get.fields.month.value,'2026-08');assert.equal(get.fields.display_currency.value,'USD');
 assert.equal(explicit.fields.month.value,'2026-07');assert.equal(explicit.fields.display_currency.value,'IDR');
 assert.deepEqual(post.fields,{});assert.deepEqual(other.fields,{});
});
test('delegated help dialog controls work after context toolbar replacement',()=>{
 const {handlers,dialogs}=setup();dialogs.help={open:false,showModal(){this.open=true;},close(){this.open=false;}};
 handlers.click({target:{closest:selector=>selector.includes('open')?{dataset:{financeUiOpen:'help'}}:null}});
 assert.equal(dialogs.help.open,true);
 handlers.click({target:{closest:selector=>selector.includes('close')?{dataset:{financeUiClose:'help'}}:null}});
 assert.equal(dialogs.help.open,false);
});
