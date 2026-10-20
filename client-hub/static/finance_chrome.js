(() => {
  'use strict';
  const popovers = '.finance-chrome .finance-chrome-popover';
  document.addEventListener('click', event => {
    for (const menu of document.querySelectorAll(`${popovers}[open]`)) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });
  document.addEventListener('focusin', event => {
    const item = event.target.closest?.('.finance-chrome .finance-primary-navigation :is(a,button)');
    const nav = item?.closest('.finance-primary-navigation');
    if (!nav || nav.scrollWidth <= nav.clientWidth) return;
    const row = nav.getBoundingClientRect(), box = item.getBoundingClientRect();
    if (box.left < row.left + 3) nav.scrollLeft += box.left - row.left - 3;
    else if (box.right > row.right - 3) nav.scrollLeft += box.right - row.right + 3;
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const menu = event.target.closest?.(`${popovers}[open]`);
    if (!menu) return;
    event.preventDefault();event.stopPropagation();
    menu.open = false;menu.querySelector('summary').focus();
  });
})();
