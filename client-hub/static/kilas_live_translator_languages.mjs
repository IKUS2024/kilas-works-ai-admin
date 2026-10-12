// Keep both native selects valid after changes, restoration and form reset.
export function validLanguagePair(primary, secondary) {
  const hasValue = field => Boolean(field.value) && Array.from(field.options).some(option => option.value === field.value);
  return hasValue(primary) && hasValue(secondary) && primary.value !== secondary.value;
}

export function syncLanguagePair(primary, secondary, changed = primary) {
  const other = changed === primary ? secondary : primary;
  const choices = field => Array.from(field.options).filter(option => option.value);
  if (!choices(changed).some(option => option.value === changed.value)) changed.value = choices(changed)[0]?.value || '';
  if (!choices(other).some(option => option.value === other.value) || other.value === changed.value) {
    other.value = choices(other).find(option => option.value !== changed.value)?.value || '';
  }
  for (const [field, opposite] of [[primary, secondary], [secondary, primary]]) {
    for (const option of field.options) option.disabled = Boolean(opposite.value) && option.value === opposite.value;
  }
  return validLanguagePair(primary, secondary);
}
