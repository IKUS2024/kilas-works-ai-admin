/* Compact operator groups on initial mobile load; native details preserve keyboard access. */
if (window.matchMedia('(max-width:760px)').matches) {
  document.querySelectorAll('.kw-operator-group, .kw-finance-menu').forEach(function (group) { group.open = false; });
}
