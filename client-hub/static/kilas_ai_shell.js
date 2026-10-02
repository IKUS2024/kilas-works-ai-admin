/* One navigation shell; conversation and task lifecycles stay in their own scripts. */
(() => {
  const shell = document.querySelector('[data-ai-shell]');
  if (!shell) return;
  const sidebar = shell.querySelector('[data-ai-sidebar]');
  const menu = shell.querySelector('[data-ai-menu]');
  const close = shell.querySelector('[data-ai-close]');
  const backdrop = shell.querySelector('[data-ai-backdrop]');
  const mobile = matchMedia('(max-width:760px)');
  const main = shell.querySelector('.ai-main');
  function toggle(open) {
    shell.classList.toggle('menu-open', open);
    menu?.setAttribute('aria-expanded', String(open));
    sidebar.inert = mobile.matches && !open;
    main.inert = mobile.matches && open;
    if (open) close?.focus(); else menu?.focus({preventScroll:true});
  }
  menu?.addEventListener('click', () => toggle(true));
  close?.addEventListener('click', () => toggle(false));
  backdrop?.addEventListener('click', () => toggle(false));
  document.addEventListener('keydown', event => {
    if (!shell.classList.contains('menu-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); toggle(false); }
    if (event.key === 'Tab') {
      const items = [...sidebar.querySelectorAll('a,button,input')].filter(item => item.getClientRects().length && !item.disabled);
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
    }
  });
  mobile.addEventListener('change', () => toggle(false));
  sidebar.inert = mobile.matches;
})();
