(() => {
  const supportsDialog = typeof HTMLDialogElement !== 'undefined';

  const dialogFor = (trigger) => {
    const selector = trigger.dataset.dialogOpen;
    if (!selector) return null;
    try {
      return document.querySelector(selector);
    } catch (_error) {
      return null;
    }
  };

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-dialog-open]');
    if (opener) {
      const dialog = dialogFor(opener);
      if (!supportsDialog || !dialog?.showModal) return; // Keep the href fallback working.
      event.preventDefault();
      if (!dialog.open) dialog.showModal();
      requestAnimationFrame(() => dialog.querySelector('[autofocus], input, textarea, select')?.focus());
      return;
    }

    const closer = event.target.closest('[data-dialog-close]');
    if (closer) {
      event.preventDefault();
      closer.closest('dialog')?.close();
      return;
    }

    const dialog = event.target instanceof HTMLDialogElement ? event.target : null;
    if (!dialog) return;
    const box = dialog.getBoundingClientRect();
    const inside =
      event.clientX >= box.left &&
      event.clientX <= box.right &&
      event.clientY >= box.top &&
      event.clientY <= box.bottom;
    if (!inside) dialog.close();
  });
})();
