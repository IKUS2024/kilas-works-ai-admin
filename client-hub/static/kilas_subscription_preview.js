/* Local view navigation only: no account, billing or payment requests. */
(() => {
  const plans = document.getElementById('subscription-plans');
  const payment = document.getElementById('payment-preview');
  const open = document.getElementById('subscription-open-payment');
  const close = document.getElementById('subscription-close-payment');
  if (!plans || !payment || !open || !close) return;
  let openedHere = false;
  function render(focus) {
    const showing = location.hash === '#payment-preview';
    plans.hidden = showing;
    payment.hidden = !showing;
    if (focus) {
      (showing ? document.getElementById('payment-title') : open).focus({preventScroll:true});
      window.scrollTo(0, 0);
    }
  }
  open.addEventListener('click', (event) => {
    event.preventDefault();
    openedHere = true;
    history.pushState(null, '', '#payment-preview');
    render(true);
  });
  function back(event) {
    event.preventDefault();
    if (openedHere) {
      openedHere = false;
      history.back();
    } else {
      history.replaceState(null, '', '#subscription-plans');
      render(true);
    }
  }
  close.addEventListener('click', back);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !payment.hidden) back(event);
  });
  window.addEventListener('popstate', () => render(true));
  window.addEventListener('hashchange', () => render(true));
  render(false);
})();
