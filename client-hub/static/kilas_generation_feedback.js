(() => {
  const panel=document.querySelector('#generation-feedback');if(!panel)return;
  const title=document.querySelector('#generation-feedback-title'),detail=document.querySelector('#generation-feedback-detail'),close=document.querySelector('#generation-feedback-close');
  const t=text=>window.KilasUI?window.KilasUI.t(text):text;
  window.KilasGenerationFeedback={show(state,heading,text){
    panel.dataset.state=state;title.textContent=t(heading);detail.textContent=t(text);close.hidden=state==='busy';panel.hidden=false;
  }};
  close.addEventListener('click',()=>{panel.hidden=true;});
})();
