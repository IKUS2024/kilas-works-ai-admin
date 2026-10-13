// Independent of the module graph: failed loading must leave visible feedback.
(()=>{
  const root=document.querySelector('[data-learning]');if(!root)return;
  const form=root.querySelector('[data-learning-form]'),start=form?.querySelector('[data-learning-start]'),status=root.querySelector('[data-status]');
  if(!form||!start||!status)return;
  const failure=()=>{
    if(root.dataset.boot==='ready')return;
    root.dataset.boot='failed';start.disabled=true;
    status.textContent='Kontrol Learning belum berhasil dimuat. Periksa koneksi browser dan buka kembali halaman Learning.';
  };
  // Also stop native GET fallback from sending consent/settings/CSRF into a URL.
  form.addEventListener('submit',event=>{if(root.dataset.boot!=='ready'){event.preventDefault();failure();}});
  root.dataset.boot='loading';start.disabled=true;
  const timer=setTimeout(failure,15000);
  root.addEventListener('kilas-learning-booted',()=>clearTimeout(timer),{once:true});
  window.addEventListener('error',event=>{if(event.target?.matches?.('[data-learning-module]')){clearTimeout(timer);failure();}},true);
})();
