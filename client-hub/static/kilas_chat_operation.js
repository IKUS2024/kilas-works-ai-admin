/* An uncertain retry keeps its key; a changed payload or terminal result does not. */
((root)=>{
  const random=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
  function create(initial){
    let key=initial||random(),previous=null;
    const snapshot=data=>[...data.entries()].filter(([name,value])=>!['csrf_token','operation_key'].includes(name)&&(typeof value==='string'||value.name));
    const equal=(a,b)=>a.length===b.length&&a.every(([name,value],i)=>name===b[i][0]&&value===b[i][1]);
    return {
      begin(data){const next=snapshot(data);if(previous&&!equal(previous,next))key=random();previous=next;return key;},
      terminal(){key=random();previous=null;return key;}
    };
  }
  if(typeof module!=='undefined')module.exports={create};else root.KilasChatOperation={create};
})(typeof window==='undefined'?globalThis:window);
