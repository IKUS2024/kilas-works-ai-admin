// Session-local captions. Provider strings are data, never HTML or instructions.
export class GeminiCaptions {
 constructor({root,document,labels,maxTurns=12}){Object.assign(this,{root,document,labels,maxTurns});this.turns=new Map();}
 reset(){this.turns.clear();this.root.replaceChildren();}
 update(text,{operation,source_text='',streams=null}={}){
  if(!operation)return;
  let turn=this.turns.get(operation);
  if(!turn){turn=new Map();this.turns.set(operation,turn);}
  const entries=streams?Object.entries(streams):[['translation',{source_text,translated_text:text}]];
  const nearEnd=this.root.scrollHeight-this.root.scrollTop-this.root.clientHeight<80;
  for(const [target,value] of entries){
   const original=typeof value.source_text==='string'?value.source_text.slice(0,4000):'';
   const translated=typeof value.translated_text==='string'?value.translated_text.slice(0,4000):'';
   // Opposing streams can both transcribe input. Show only a stream that has
   // translated text, avoiding two identical source-only bubbles.
   if(!translated)continue;
   let row=turn.get(target);
   if(!row){
    const section=this.document.createElement('article'),heading=this.document.createElement('h3'),source=this.document.createElement('p'),output=this.document.createElement('p');
    section.className='native-caption';source.className='native-original';output.className='native-translated';
    heading.textContent=this.labels[target]||this.labels.translation;source.setAttribute('aria-label',this.labels.original);output.setAttribute('aria-label',this.labels.translation);
    output.lang=target==='translation'?'':target;section.append(heading,source,output);this.root.append(section);row={section,source,output};turn.set(target,row);
   }
   row.source.textContent=original;row.source.hidden=!original;row.output.textContent=translated;
  }
  while(this.turns.size>this.maxTurns){const key=this.turns.keys().next().value;for(const row of this.turns.get(key).values())row.section.remove();this.turns.delete(key);}
  if(nearEnd)this.root.scrollTop=this.root.scrollHeight;
 }
}
