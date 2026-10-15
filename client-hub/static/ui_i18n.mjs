/* Explicit UI copy only. Content and language/voice settings never pass here. */
export function uiText(message, values = {}) {
  if (globalThis.KilasUI) return globalThis.KilasUI.t(message, values);
  let text = message;
  for (const [key, value] of Object.entries(values)) text = text.replaceAll('{' + key + '}', String(value));
  return text;
}
