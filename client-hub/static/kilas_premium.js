/* Presentation only: accessible mobile navigation. No application requests. */
(function () {
  'use strict';
  const sidebar = document.getElementById('premium-sidebar');
  const trigger = document.querySelector('[data-premium-menu]');
  const backdrop = document.querySelector('.premium-backdrop');
  if (!sidebar || !trigger || !backdrop) return;
  const desktop = matchMedia('(min-width: 761px)');
  let open = false;
  function update(next, restore) {
    open = next && !desktop.matches;
    document.body.classList.toggle('premium-menu-open', open);
    trigger.setAttribute('aria-expanded', String(open));
    backdrop.hidden = !open;
    sidebar.inert = !desktop.matches && !open;
    if (open) sidebar.querySelector('[data-premium-close]').focus({preventScroll:true});
    else if (restore) trigger.focus({preventScroll:true});
  }
  trigger.addEventListener('click', () => update(!open, true));
  document.querySelectorAll('[data-premium-close]').forEach(el => el.addEventListener('click', () => update(false, true)));
  document.addEventListener('keydown', event => {
    if (!open) return;
    if (event.key === 'Escape') { event.preventDefault(); update(false, true); }
    if (event.key === 'Tab') {
      const items = [...sidebar.querySelectorAll('a,button')].filter(el => !el.disabled);
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  desktop.addEventListener('change', () => update(false, false));
  update(false, false);
})();
