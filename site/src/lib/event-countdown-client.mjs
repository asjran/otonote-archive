import {eventCountdown} from './event-time.mjs';

// Keep this initializer self-contained so the first label needs no module download.
export function refreshEventCountdown(node, countdown, now = Date.now()) {
  if (!node) return;
  const start = node.dataset.start ? Number(node.dataset.start) : null;
  const end = node.dataset.end ? Number(node.dataset.end) : null;
  const state = countdown(start, end, now, node.dataset.en === 'true');
  node.dataset.state = state.state;
  const label = node.querySelector('span');
  if (label) label.textContent = state.label;
}

export function eventCountdownInitScript() {
  return `(${refreshEventCountdown.toString()})(document.currentScript.previousElementSibling,${eventCountdown.toString()});`;
}
