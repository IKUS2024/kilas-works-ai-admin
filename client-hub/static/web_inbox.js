(() => {
  const panel=document.querySelector('[data-owner-chat]'); if(!panel) return;
  const thread=panel.querySelector('[data-thread]'), status=panel.querySelector('[data-status]');
  let after=0;
  async function refresh(){
    try {
      const response=await fetch(panel.dataset.base+'?after='+after,{cache:'no-store'});
      if(!response.ok) throw new Error('Percakapan belum dapat dimuat.');
      const data=await response.json();
      for(const message of data.messages){
        const bubble=document.createElement('div'); bubble.className='web-bubble '+message.role;
        const label=document.createElement('small');label.textContent=message.role==='user'?'Pengunjung':(message.role==='human'?'Tim':'AI');
        bubble.append(label,document.createTextNode(message.content));thread.append(bubble);after=message.id;
      }
      if(data.messages.length) thread.scrollTop=thread.scrollHeight;
      panel.querySelector('[data-mode]').textContent=data.mode==='HUMAN_TAKEOVER'?'Ditangani tim':'AI aktif';
      status.textContent='';
    } catch(error){status.textContent='Koneksi terputus. Mencoba kembali…';}
    setTimeout(refresh,3000);
  }
  refresh();
})();
