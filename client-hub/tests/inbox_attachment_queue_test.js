(function () {
  const make = (name, type, size, lastModified) => ({name, type, size, lastModified});
  const imageA = make('a.png', 'image/png', 10, 1);
  const imageB = make('b.jpg', 'image/jpeg', 20, 2);
  const imageC = make('c.png', 'image/png', 30, 3);
  const pdf = make('offer.pdf', 'application/pdf', 40, 4);
  const assert = (value, message) => { if (!value) throw new Error(message); };

  const single = KilasInboxAttachments.createQueue();
  single.add([imageA]);
  assert(single.files()[0] === imageA, 'single image selection failed');
  single.remove(0);
  assert(single.files().length === 0, 'single image removal failed');

  const images = KilasInboxAttachments.createQueue();
  images.add([imageA, imageB]);
  images.add([imageC]);
  assert(images.files().map(file => file.name).join(',') === 'a.png,b.jpg,c.png',
    'additional image selection replaced pending images');
  images.remove(1);
  assert(images.files().map(file => file.name).join(',') === 'a.png,c.png',
    'removing one image changed another pending image');

  const documentQueue = KilasInboxAttachments.createQueue();
  documentQueue.add([pdf]);
  assert(documentQueue.files()[0].name === 'offer.pdf', 'PDF selection failed');
  documentQueue.remove(0);
  assert(documentQueue.files().length === 0, 'PDF removal failed');

  if (typeof document !== 'undefined' && typeof File !== 'undefined') {
    const form = document.createElement('form');
    form.innerHTML = '<input type="file" data-inbox-attachment-input multiple>' +
      '<div data-inbox-attachment-preview></div>';
    document.body.append(form);
    KilasInboxAttachments.setup(form);
    const input = form.querySelector('input');
    const preview = form.querySelector('div');
    const select = files => {
      const transfer = new DataTransfer();
      files.forEach(file => transfer.items.add(file));
      input.files = transfer.files;
      input.dispatchEvent(new Event('change'));
    };
    const first = new File(['a'], 'first.png', {type: 'image/png', lastModified: 11});
    const second = new File(['b'], 'second.jpg', {type: 'image/jpeg', lastModified: 12});
    const third = new File(['c'], 'third.png', {type: 'image/png', lastModified: 13});
    select([first, second]);
    assert(preview.querySelectorAll('img').length === 2, 'image thumbnails were not rendered');
    preview.querySelectorAll('.kw-pending-remove')[1].click();
    assert(input.files.length === 1 && input.files[0].name === 'first.png',
      'image remove button removed the wrong pending file');
    select([third]);
    assert([...input.files].map(file => file.name).join(',') === 'first.png,third.png',
      'additional image selection replaced an existing preview');
    while (preview.querySelector('.kw-pending-remove')) {
      preview.querySelector('.kw-pending-remove').click();
    }
    select([new File(['pdf'], 'offer.pdf', {type: 'application/pdf', lastModified: 14})]);
    assert(preview.querySelector('.kw-pending-file')?.textContent === 'PDF',
      'PDF preview row was not rendered');
    assert(preview.querySelector('.kw-pending-name')?.textContent === 'offer.pdf',
      'PDF filename was not rendered');
    preview.querySelector('.kw-pending-remove').click();
    assert(input.files.length === 0 && preview.children.length === 0,
      'PDF remove button did not clear the pending file');
    form.remove();
  }

  globalThis.__inboxAttachmentQueueTest = JSON.stringify({
    ok: true, remaining: images.files().map(file => file.name)
  });
}());
