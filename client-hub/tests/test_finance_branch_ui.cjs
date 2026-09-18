// Focused regression: visible category matches direction; Lainnya retains entered notes.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
test('direction changes and Lainnya visibility preserve notes',()=>{
  const input={value:'Servis mesin kopi',required:false,disabled:false};
  const other={hidden:true,querySelector:()=>input};
  const kind={value:'INCOME',addEventListener(_,callback){this.change=callback;}};
  const options=[['1','INCOME','false'],['2','INCOME','true'],['3','EXPENSE','false'],['4','EXPENSE','true']].map(([value,direction,other])=>({value,dataset:{direction,other},disabled:false,hidden:false}));
  const category={value:'1',options,get selectedOptions(){return options.filter(o=>o.value===this.value);},addEventListener(_,callback){this.change=callback;},closest(){return form;}};
  const form={querySelector:selector=>selector==='[name="direction"]'?kind:other};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/finance_branches.js'),'utf8'),{document:{querySelectorAll:()=>[category]}});
  assert.equal(options[2].disabled,true);
  assert.equal(input.disabled,true);
  category.value='2';category.change();
  assert.equal(other.hidden,false);assert.equal(input.required,true);assert.equal(input.disabled,false);
  kind.value='EXPENSE';kind.change();
  assert.equal(category.value,'3');assert.equal(options[0].disabled,true);assert.equal(other.hidden,true);
  category.value='4';category.change();
  assert.equal(input.value,'Servis mesin kopi');assert.equal(input.required,true);
});
