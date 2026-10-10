import {ListeningSession,syntheticStream} from './kilas_listening_core.mjs';
const root=document.querySelector('#listening-demo');
if(root) {
  const start=root.querySelector('#listen-start'),stop=root.querySelector('#listen-stop');
  const source=root.querySelector('#listen-source'),target=root.querySelector('#listen-target');
  const consent=root.querySelector('#listen-consent'),suggest=root.querySelector('#listen-suggest');
  const status=root.querySelector('#listen-status'),original=root.querySelector('#listen-original');
  const translated=root.querySelector('#listen-translated'),reply=root.querySelector('#listen-reply');
  const messages={consent_required:'Setujui penjelasan demo sebelum mulai.',audio_missing:'Sumber tidak menyediakan audio. Pilih tab dan aktifkan berbagi audio.',
    permission_denied:'Pemilihan sumber dibatalkan atau izin ditolak.',tab_required:'Pilih tab Chrome dengan audio, bukan jendela atau seluruh layar.',
    source_ended:'Sumber sudah berhenti.',real_disabled:'Capture nyata belum diaktifkan.',unsupported:'Browser ini belum mendukung pemilihan sumber.',gesture_required:'Pemilihan sumber harus dimulai dari klik pengguna.'};
  const clear=()=>{original.replaceChildren();translated.replaceChildren();reply.value='';};
  const session=new ListeningSession({selectStream:async()=>syntheticStream(),
    onState:({state,reason})=>{
      root.dataset.state=state;
      const busy=state==='starting'||state==='active';start.disabled=busy;stop.disabled=!busy;
      source.disabled=target.disabled=consent.disabled=suggest.disabled=busy;
      if(state==='active') status.textContent='Demo berjalan · teks sintetis, bukan audio tab.';
      else if(state==='starting') status.textContent='Menyiapkan contoh sintetis…';
      else if(state==='error') {clear();status.textContent=messages[reason]||'Demo gagal. Berhenti lalu coba lagi.';}
      else {clear();status.textContent=reason==='disconnected'?'Sumber demo terputus. Sesi dibersihkan.':reason==='complete'?'Contoh selesai. Sesi dibersihkan.':'Berhenti. Tidak ada rekaman atau teks yang disimpan.';}
    },
    onSegment:segment=>{
      for(const [node,text] of [[original,segment.original],[translated,segment.translated]]) {
        const line=document.createElement('p');line.textContent=text;node.append(line);
      }
      if(suggest.checked) reply.value=source.value==='en'?'Could you clarify which option you mean?':'Bisa jelaskan pilihan yang kamu maksud?';
    }});
  start.addEventListener('click',event=>{
    if(source.value===target.value) {status.textContent='Pilih bahasa sumber dan tujuan yang berbeda.';return;}
    clear();
    const pairs=[['Let us compare the two options.','Mari kita bandingkan dua pilihan.'],['What should we discuss next?','Apa yang perlu kita bahas berikutnya?']];
    const segments=pairs.map(([en,id])=>({original:source.value==='en'?en:id,translated:target.value==='id'?id:en}));
    session.start({consent:consent.checked,userGesture:event.isTrusted,segments});
  });
  stop.addEventListener('click',()=>session.stop());
  window.addEventListener('pagehide',()=>session.stop('disconnected'));
}
