export function setFilterChipContent(button, input, fallback) {
  const option = input?.closest('[data-facet-option]');
  const label = input?.getAttribute('aria-label') || fallback;
  button.setAttribute('aria-label', `移除 ${label}`);
  button.title = label;
  const content = option?.querySelector('.filter-option-content');
  if (content) button.append(content.cloneNode(true));
  else button.append(document.createTextNode(label));
  const close = document.createElement('span');
  close.textContent = '×';
  close.setAttribute('aria-hidden', 'true');
  button.append(close);
}
