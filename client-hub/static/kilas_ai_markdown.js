/* Shared safe Markdown: model HTML is always text, only HTTP(S) links become anchors. */
(() => {
  function inline(parent,text) {
    const pattern=/(\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*([^*]+)\*|_([^_]+)_|https?:\/\/[^\s<>]+)/g;
    let start=0,match;
    while ((match=pattern.exec(text))) {
      parent.append(document.createTextNode(text.slice(start,match.index)));
      let node;
      if(match[2]){node=document.createElement('strong');node.textContent=match[2];}
      else if(match[3]){node=document.createElement('code');node.textContent=match[3];}
      else if(match[6]||match[7]){node=document.createElement('em');node.textContent=match[6]||match[7];}
      else {
        try {
          const url=new URL(match[5]||match[0]);
          if(!['https:','http:'].includes(url.protocol)||!url.hostname||url.username||url.password)throw new Error('url');
          node=document.createElement('a');node.textContent=match[4]||url.hostname.replace(/^www\./,'');
          node.href=url.href;node.target='_blank';node.rel='noopener noreferrer nofollow';
        } catch (_) {node=document.createTextNode(match[0]);}
      }
      parent.append(node);start=pattern.lastIndex;
    }
    if(start<text.length)parent.append(document.createTextNode(text.slice(start)));
  }
  function render(element,text){
    const lines=text.split(/\r?\n/),fragment=document.createDocumentFragment();let index=0;
    while(index<lines.length){
      const line=lines[index].trim();if(!line){index++;continue;}
      if(line.startsWith('```')){const code=document.createElement('code'),pre=document.createElement('pre'),block=[];index++;while(index<lines.length&&!lines[index].trim().startsWith('```'))block.push(lines[index++]);code.textContent=block.join('\n');pre.append(code);fragment.append(pre);index++;continue;}
      if(/^#{1,3}\s/.test(line)){const level=line.match(/^#+/)[0].length,heading=document.createElement('h'+Math.min(level+1,4));inline(heading,line.replace(/^#{1,3}\s/,''));fragment.append(heading);index++;continue;}
      if(/^[-*]\s/.test(line)||/^\d+[.)]\s/.test(line)){const ordered=/^\d/.test(line),list=document.createElement(ordered?'ol':'ul');while(index<lines.length&&(ordered?/^\d+[.)]\s/:/^[-*]\s/).test(lines[index].trim())){const item=document.createElement('li');inline(item,lines[index].trim().replace(/^(?:[-*]|\d+[.)])\s/,''));list.append(item);index++;}fragment.append(list);continue;}
      if(line.startsWith('|')&&index+1<lines.length&&/^\|?[\s:|-]+\|?$/.test(lines[index+1].trim())){const table=document.createElement('table');let rowIndex=0;while(index<lines.length&&lines[index].trim().startsWith('|')){if(rowIndex!==1){const row=document.createElement('tr');for(const cell of lines[index].trim().replace(/^\||\|$/g,'').split('|')){const node=document.createElement(rowIndex===0?'th':'td');inline(node,cell.trim());row.append(node);}table.append(row);}rowIndex++;index++;}const scroller=document.createElement('div');scroller.className='ai-table-scroll';scroller.append(table);fragment.append(scroller);continue;}
      const paragraph=document.createElement('p'),parts=[line];index++;while(index<lines.length&&lines[index].trim()&&!/^(?:#{1,3}\s|[-*]\s|\d+[.)]\s|```|\|)/.test(lines[index].trim()))parts.push(lines[index++].trim());inline(paragraph,parts.join(' '));fragment.append(paragraph);
    }
    element.replaceChildren(fragment);
    element.dataset.kilasRendered='1';
  }
  function hydrate(root=document) {
    root.querySelectorAll('[data-kilas-markdown]').forEach(node => {if(node.dataset.kilasRendered!=='1')render(node,node.textContent);});
  }
  window.KilasMarkdown=Object.freeze({render,hydrate});
  document.addEventListener('DOMContentLoaded',()=>hydrate());
})();
