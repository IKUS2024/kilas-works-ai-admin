/* Safe, shared progressive Markdown. Model HTML stays text; math assets are local. */
(() => {
  const asset=name=>new URL(name,document.currentScript.src).href;
  const mathScript=asset('vendor/katex-0.19.0/katex.min.js'),mathCSS=asset('vendor/katex-0.19.0/katex.min.css');
  const states=new WeakMap(),waiting=new Set(),mathTemplates=new Map();let mathStatus='idle';
  function loadMath(){
    if(mathStatus!=='idle')return;mathStatus='loading';
    const css=document.createElement('link');css.rel='stylesheet';css.href=mathCSS;
    const script=document.createElement('script');script.src=mathScript;script.async=true;
    let cssReady=false,scriptReady=false,settled=false;
    const finish=failed=>{if(settled||(!failed&&(!cssReady||!scriptReady)))return;settled=true;clearTimeout(timer);mathStatus=failed?'failed':'ready';for(const node of waiting){if(node.isConnected)flush(node);}waiting.clear();};
    const timer=setTimeout(()=>finish(true),8000);
    css.onload=()=>{cssReady=true;finish(false);};script.onload=()=>{scriptReady=Boolean(window.katex);finish(!scriptReady);};css.onerror=script.onerror=()=>finish(true);
    document.head.append(css,script);
  }
  function math(parent,tex,display=false){
    const node=document.createElement('span');node.className=display?'ai-math-display':'ai-math-inline';
    if(mathStatus==='ready'&&tex.length<=8000){
      try{const key=String(display)+'|'+tex;let template=mathTemplates.get(key);if(!template){template=document.createElement('span');window.katex.render(tex,template,{displayMode:display,throwOnError:true,trust:false,strict:'error',maxSize:20,maxExpand:1000,macros:{},output:'htmlAndMathml'});if(mathTemplates.size>=32)mathTemplates.delete(mathTemplates.keys().next().value);mathTemplates.set(key,template);}node.append(...[...template.childNodes].map(n=>n.cloneNode(true)));}catch{node.textContent=tex;node.dataset.mathError='1';}
    }else if(mathStatus==='failed'||tex.length>8000){node.textContent=tex;node.dataset.mathError='1';}
    else {node.textContent='…';node.setAttribute('aria-busy','true');node.dataset.mathPending='1';loadMath();}
    parent.append(node);
  }
  function inline(parent,text,complete=true){
    // Code and TeX are consumed before Markdown emphasis or links can reinterpret them.
    let index=0,plain='';const emit=()=>{if(plain){parent.append(document.createTextNode(plain));plain='';}};
    while(index<text.length){
      const tail=text.slice(index);let match;
      if(tail.startsWith('\\(')||tail.startsWith('\\[')||tail.startsWith('$$')){
        const open=tail.slice(0,2),close=open==='\\('? '\\)':open==='\\['?'\\]':'$$',end=tail.indexOf(close,2);emit();
        if(end<0){const pending=document.createElement('span');pending.textContent=complete?tail:'…';pending.dataset[complete?'mathError':'mathIncomplete']='1';parent.append(pending);break;}
        math(parent,tail.slice(2,end),open!=='\\(');index+=end+2;continue;
      }
      if(tail[0]==='`'){const ticks=tail.match(/^`+/)[0],end=tail.indexOf(ticks,ticks.length);emit();const code=document.createElement('code');code.textContent=tail.slice(ticks.length,end<0?undefined:end);parent.append(code);index+=end<0?tail.length:end+ticks.length;continue;}
      if((match=tail.match(/^\$([^\s$](?:[^$\n]*?[^\s$])?)\$(?!\$)/))){emit();math(parent,match[1]);index+=match[0].length;continue;}
      if(tail[0]==='$'&&/^\$(?:\\|[A-Za-z]|[0-9]+[+^_*\/={}])/.test(tail)&&!tail.slice(1).includes('$')){emit();const pending=document.createElement('span');pending.textContent=complete?tail:'…';pending.dataset[complete?'mathError':'mathIncomplete']='1';parent.append(pending);break;}
      if((match=tail.match(/^\*\*([\s\S]*?)(?:\*\*|$)/))){emit();const strong=document.createElement('strong');inline(strong,match[1],complete);parent.append(strong);index+=match[0].length;continue;}
      if((match=tail.match(/^(?:\*([^*]+)\*|_([^_]+)_)/))){emit();const em=document.createElement('em');inline(em,match[1]||match[2],complete);parent.append(em);index+=match[0].length;continue;}
      if((match=tail.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|^https?:\/\/[^\s<>]+/))){
        try{const url=new URL(match[2]||match[0]);if(!['http:','https:'].includes(url.protocol)||!url.hostname||url.username||url.password)throw Error();emit();const link=document.createElement('a');link.textContent=match[1]||url.hostname.replace(/^www\./,'');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer nofollow';parent.append(link);index+=match[0].length;continue;}catch{}
      }
      if(tail[0]==='\\'&&/[\\`*$[\]_]/.test(tail[1]||'')){plain+=tail[1];index+=2;}else {plain+=text[index];index++;}
    }
    emit();
  }
  function cells(line){
    if(line.startsWith('|'))line=line.slice(1);if(line.endsWith('|')&&!line.endsWith('\\|'))line=line.slice(0,-1);
    const result=[];let text='',close=null;
    for(let i=0;i<line.length;i++){
      if(close){if(line.startsWith(close,i)){text+=close;i+=close.length-1;close=null;}else text+=line[i];continue;}
      if(line[i]==='\\'&&line[i+1]==='|'){text+='\\|';i++;continue;}
      if(line[i]==='`'){close=line.slice(i).match(/^`+/)[0];text+=close;i+=close.length-1;continue;}
      const marker=['\\(','\\[','$$','$'].find(value=>line.startsWith(value,i));
      if(marker){close=marker==='\\('? '\\)':marker==='\\['?'\\]':marker;text+=marker;i+=marker.length-1;continue;}
      if(line[i]==='|'){result.push(text);text='';}else text+=line[i];
    }
    result.push(text);return result;
  }
  function state(element){let value=states.get(element);if(!value){value={text:'',frame:null,blocks:[],complete:true};states.set(element,value);}return value;}
  function source(element){return states.get(element)?.text??element.textContent;}
  function flush(element){
    const current=state(element);if(current.frame!==null){cancelAnimationFrame(current.frame);current.frame=null;}
    const write=(node,text)=>inline(node,text,current.complete);
    const lines=current.text.split(/\r?\n/),plan=[];let index=0;
    const phase=text=>text.includes('\\(')||text.includes('\\[')||text.includes('$')?mathStatus:'';
    const add=(key,make)=>{const old=current.blocks[plan.length];const incomplete=old&&(old.node.matches('[data-math-incomplete]')||old.node.querySelector('[data-math-incomplete]'));plan.push(old?.key===key&&!(current.complete&&incomplete)?old:{key,node:make()});};
    while(index<lines.length){
      const line=lines[index].trim();if(!line){index++;continue;}
      const begin=index;
      if(/^(`{3,}|~{3,})/.test(line)){
        const fence=line.match(/^(`{3,}|~{3,})/)[0],body=[];index++;
        while(index<lines.length&&!new RegExp('^'+fence[0]+'{'+fence.length+',}\\s*$').test(lines[index].trim()))body.push(lines[index++]);if(index<lines.length)index++;
        add('code|'+body.join('\n'),()=>{const pre=document.createElement('pre'),code=document.createElement('code');code.textContent=body.join('\n');pre.append(code);return pre;});continue;
      }
      if(line.startsWith('\\[')||line.startsWith('$$')){
        const close=line.startsWith('\\[')?'\\]':'$$';let text=lines[index++].trim().slice(2);
        while(!text.includes(close)&&index<lines.length)text+='\n'+lines[index++];
        const end=text.indexOf(close),tex=end<0?null:text.slice(0,end);
        add('math|'+(tex??text)+'|'+mathStatus,()=>{const box=document.createElement('div');if(tex===null){box.textContent=current.complete?lines.slice(begin,index).join('\n'):'…';box.dataset[current.complete?'mathError':'mathIncomplete']='1';}else math(box,tex,true);return box;});
        if(end>=0&&text.slice(end+2).trim()){const tail=text.slice(end+2).trim();add('math-tail|'+tail+'|'+mathStatus,()=>{const p=document.createElement('p');write(p,tail);return p;});}continue;
      }
      if(/^#{1,3}\s/.test(line)){index++;add('heading|'+line+'|'+phase(line),()=>{const h=document.createElement('h'+(line.match(/^#+/)[0].length+1));write(h,line.replace(/^#{1,3}\s/,''));return h;});continue;}
      if(/^[-*]\s/.test(line)||/^\d+[.)]\s/.test(line)){
        const ordered=/^\d/.test(line),items=[];while(index<lines.length&&(ordered?/^\d+[.)]\s/:/^[-*]\s/).test(lines[index].trim()))items.push(lines[index++].trim().replace(/^(?:[-*]|\d+[.)])\s/,''));
        add('list|'+ordered+'|'+items.join('\n')+'|'+phase(items.join('\n')),()=>{const list=document.createElement(ordered?'ol':'ul');if(ordered)list.start=Number(line.match(/^\d+/)[0]);for(const text of items){const li=document.createElement('li');write(li,text);list.append(li);}return list;});continue;
      }
      if(line.startsWith('|')&&index+1<lines.length&&/^\|?[\s:|-]+\|?$/.test(lines[index+1].trim())){
        const rows=[];while(index<lines.length&&lines[index].trim().startsWith('|'))rows.push(lines[index++].trim());
        add('table|'+rows.join('\n')+'|'+phase(rows.join('\n')),()=>{const scroller=document.createElement('div');scroller.className='ai-table-scroll';const table=document.createElement('table');rows.forEach((row,i)=>{if(i===1)return;const tr=document.createElement('tr');for(const cell of cells(row)){const node=document.createElement(i===0?'th':'td');write(node,cell.trim().replace(/\\\|/g,'|'));tr.append(node);}table.append(tr);});scroller.append(table);return scroller;});continue;
      }
      if(line.startsWith('> ')){const parts=[];while(index<lines.length&&lines[index].trim().startsWith('> '))parts.push(lines[index++].trim().slice(2));add('quote|'+parts.join('\n')+'|'+phase(parts.join('\n')),()=>{const quote=document.createElement('blockquote');write(quote,parts.join(' '));return quote;});continue;}
      const parts=[line];index++;while(index<lines.length&&lines[index].trim()&&!/^(?:#{1,3}\s|[-*]\s|\d+[.)]\s|`{3,}|~{3,}|\||> |\\\[|\$\$)/.test(lines[index].trim()))parts.push(lines[index++].trim());
      add('paragraph|'+parts.join(' ')+'|'+phase(parts.join(' ')),()=>{const p=document.createElement('p');write(p,parts.join(' '));return p;});
      if(index<=begin)index++;
    }
    plan.forEach(({node},i)=>{if(element.childNodes[i]!==node)element.insertBefore(node,element.childNodes[i]||null);});while(element.childNodes.length>plan.length)element.lastChild.remove();current.blocks=plan;
    element.classList.add('ai-markdown');element.dataset.kilasRendered='1';
    if(element.querySelector('[data-math-pending]'))waiting.add(element);else waiting.delete(element);
    element.dispatchEvent(new Event('kilas:rendered'));
  }
  function render(element,text){const current=state(element);current.text=String(text??'');current.complete=true;flush(element);}
  function stream(element,text){const current=state(element);current.complete=false;current.text+=String(text??'');element.classList.add('ai-markdown');if(current.frame===null)current.frame=requestAnimationFrame(()=>flush(element));}
  function finish(element){state(element).complete=true;flush(element);}
  function hydrate(root=document){root.querySelectorAll('[data-kilas-markdown]').forEach(node=>{if(node.dataset.kilasRendered!=='1')render(node,node.textContent);});}
  window.KilasMarkdown=Object.freeze({render,stream,finish,source,hydrate});
  document.addEventListener('DOMContentLoaded',()=>hydrate());
})();
