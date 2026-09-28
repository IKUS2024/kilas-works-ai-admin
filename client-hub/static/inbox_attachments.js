(function (root) {
  'use strict';

  function createQueue() {
    let pending = [];
    return {
      add(files) {
        for (const file of Array.from(files || [])) {
          const key = [file.name, file.size, file.lastModified, file.type].join(':');
          if (!pending.some(item => item.key === key)) pending.push({key, file});
        }
        return pending.map(item => item.file);
      },
      remove(index) {
        pending.splice(index, 1);
        return pending.map(item => item.file);
      },
      files() { return pending.map(item => item.file); }
    };
  }

  root.KilasInboxAttachments = {createQueue};
  if (typeof document === 'undefined') return;

  function setup(form) {
    const input = form.querySelector('[data-inbox-attachment-input]');
    const preview = form.querySelector('[data-inbox-attachment-preview]');
    if (!input || !preview || typeof DataTransfer === 'undefined') return;
    const queue = createQueue();
    let objectUrls = [];

    function syncInput() {
      const transfer = new DataTransfer();
      for (const file of queue.files()) transfer.items.add(file);
      input.files = transfer.files;
    }

    function render() {
      for (const url of objectUrls) URL.revokeObjectURL(url);
      objectUrls = [];
      preview.replaceChildren();
      queue.files().forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'kw-pending-attachment';
        if (file.type.startsWith('image/')) {
          const image = document.createElement('img');
          const url = URL.createObjectURL(file);
          objectUrls.push(url);
          image.src = url;
          image.alt = '';
          item.append(image);
        } else {
          const icon = document.createElement('span');
          icon.className = 'kw-pending-file';
          icon.textContent = 'PDF';
          item.append(icon);
        }
        const name = document.createElement('span');
        name.className = 'kw-pending-name';
        name.textContent = file.name;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'kw-pending-remove';
        remove.textContent = '×';
        remove.setAttribute('aria-label', 'Hapus ' + file.name);
        remove.addEventListener('click', () => {
          queue.remove(index);
          syncInput();
          render();
        });
        item.append(name, remove);
        preview.append(item);
      });
    }

    input.addEventListener('change', () => {
      queue.add(input.files);
      syncInput();
      render();
    });
    form.addEventListener('submit', event => {
      if (!queue.files().length) event.preventDefault();
    });
  }

  function init() {
    document.querySelectorAll('[data-inbox-attachment-form]').forEach(setup);
  }
  root.KilasInboxAttachments.setup = setup;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}(globalThis));
