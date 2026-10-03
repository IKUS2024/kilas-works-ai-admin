/* Only explicitly marked UI strings pass through this function, never user content. */
(() => {
  const messages = JSON.parse(document.getElementById('kw-ui-translations').textContent);
  window.KilasUI = Object.freeze({
    t(message, values = {}) {
      let text = messages[message] ?? message;
      for (const [key, value] of Object.entries(values)) text = text.replaceAll('{' + key + '}', String(value));
      return text;
    }
  });
})();
