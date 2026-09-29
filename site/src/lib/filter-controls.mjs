export function filterValues(value) {
  return (Array.isArray(value) ? value : String(value ?? '').split(',')).filter(value => value && value !== 'all');
}
export function matchesFilter(actual, selected) {
  const wanted = filterValues(selected);
  const values = Array.isArray(actual) ? actual.map(String) : [String(actual)];
  return !wanted.length || wanted.some(value => values.includes(value));
}
export function restoreFilterControl(control, value) {
  if (control.multiple) {
    const values = filterValues(value);
    for (const option of control.options) option.selected = values.length ? values.includes(option.value) : option.value === 'all' || option.value === '';
  } else control.value = value;
}
export function selectedControlValues(control) {
  return filterValues(control?.multiple ? [...control.selectedOptions].map(option => option.value) : control?.value);
}
