'use strict';
for (const form of document.querySelectorAll('form')) {
  if (form.method.toLowerCase() === 'post') {
    for (const control of form.querySelectorAll('button,input,select,textarea')) control.disabled = true;
    form.addEventListener('submit', event => event.preventDefault());
  }
}
