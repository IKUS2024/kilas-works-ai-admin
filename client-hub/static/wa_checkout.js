(async function(){
  const token=location.hash.slice(1);
  if(!token)return;
  history.replaceState(null,'',location.pathname);
  try{
    const response=await fetch('/wa-checkout/access',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.getElementById('csrf').value},body:JSON.stringify({token})});
    if(!response.ok)throw new Error('access');
    location.replace('/wa-checkout');
  }catch(e){document.getElementById('access-error').textContent='Link tidak valid, kedaluwarsa, atau terlalu banyak percobaan. Minta bantuan tim untuk order yang sama.';}
})();
