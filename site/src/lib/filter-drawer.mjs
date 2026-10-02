import { selectedControlValues } from './filter-controls.mjs';

function observeStickyToolbar(toolbar, signal) {
  if (!toolbar) return;
  let frame = 0;
  const update = () => {
    frame = 0;
    const style = getComputedStyle(toolbar);
    const inset = Number.parseFloat(style.top);
    let scrollTop = 0;
    // A toolbar inside a dialog sticks to its scroll container, not the page.
    for (let parent = toolbar.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      if (/(auto|scroll|hidden|overlay)/.test(getComputedStyle(parent).overflowY)) {
        scrollTop = parent.getBoundingClientRect().top + parent.clientTop;
        break;
      }
    }
    toolbar.toggleAttribute('data-filter-stuck',
      style.position === 'sticky' && Number.isFinite(inset)
      && toolbar.getClientRects().length > 0
      && toolbar.getBoundingClientRect().top <= scrollTop + inset + 0.5);
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
  document.addEventListener('scroll', schedule, { capture: true, passive: true, signal });
  window.addEventListener('resize', schedule, { passive: true, signal });
  const resize = new ResizeObserver(schedule);
  resize.observe(toolbar);
  resize.observe(document.documentElement);
  signal.addEventListener('abort', () => {
    cancelAnimationFrame(frame);
    resize.disconnect();
    toolbar.removeAttribute('data-filter-stuck');
  }, { once: true });
  schedule();
}

class FilterDrawer extends HTMLElement {
  connectedCallback() {
    this.abort?.abort();
    this.observer?.disconnect();
    this.abort = new AbortController();
    const { signal } = this.abort;
    const dialog = this.querySelector('dialog');
    const trigger = this.querySelector('[data-drawer-open]');
    const scope = this.closest('[data-filter-scope]');
    const count = scope?.querySelector('[data-filter-count]');
    const result = this.querySelector('[data-drawer-result]');
    const badge = this.querySelector('[data-panel-count]');
    if (!dialog || !trigger || !scope) return;
    observeStickyToolbar(this.parentElement, signal);

    const selectionControls = this.hasAttribute('data-selection-controls');
    const summary = scope.querySelector('[data-filter-summary]');
    const sync = () => {
      const active = selectionControls ? [
        ...[...scope.querySelectorAll('select')].filter(control => control.value !== control.options[0]?.value)
          .map(control => ({label:control.selectedOptions[0]?.textContent ?? control.value,clear:()=>{
            control.selectedIndex=0;control.dispatchEvent(new Event('change',{bubbles:true}));
          }})),
        ...[...scope.querySelectorAll('input[type="number"]')].filter(control=>control.value!=='')
          .map(control=>({label:`${control.closest('label')?.firstChild?.textContent.trim() ?? ''} ${control.value}`,clear:()=>{
            control.value='';control.dispatchEvent(new Event('input',{bubbles:true}));
          }})),
        ...[...scope.querySelectorAll('[data-attribute-value][aria-pressed="true"]')].filter(control=>control.dataset.attributeValue)
          .map(control=>({label:control.getAttribute('aria-label')??control.textContent.trim(),clear:()=>control.click()}))
      ] : [];
      const total = selectionControls ? active.length : this.querySelectorAll('input[type="checkbox"]:checked').length
        + [...this.querySelectorAll('select[data-inline-filter], select[data-filter]')]
          .reduce((sum, control) => sum + selectedControlValues(control).length, 0);
      if (badge) {
        badge.textContent = String(total);
        badge.hidden = total === 0;
      }
      if (count && result) result.textContent = `${count.textContent} ${this.dataset.resultNoun ?? ''}`;
      if (selectionControls && summary) {
        // Keep focus on a surviving chip when clearing a condition with the keyboard.
        const focused=[...summary.children].indexOf(document.activeElement);
        summary.replaceChildren(...active.map(entry=>{
          const button=document.createElement('button');button.type='button';
          button.textContent=entry.label+' ×';button.setAttribute('aria-label',`取消筛选：${entry.label}`);
          button.addEventListener('click',entry.clear);return button;
        }));
        summary.hidden=active.length===0;
        if(focused>=0)(summary.children[Math.min(focused,active.length-1)]??trigger).focus({preventScroll:true});
      }
    };
    // All controls stay in their original container; its existing handlers own the results and URL.
    const scheduleSync = () => queueMicrotask(sync);
    for (const type of ['input', 'change', 'reset', 'click']) {
      scope.addEventListener(type, scheduleSync, { signal });
    }
    window.addEventListener('popstate', scheduleSync, { signal });
    document.addEventListener('DOMContentLoaded', sync, { once: true, signal });
    if (count) {
      this.observer = new MutationObserver(sync);
      this.observer.observe(count, { childList: true, characterData: true, subtree: true });
    }
    sync();

    this.querySelector('[data-drawer-reset]')?.addEventListener('click', event => {
      // Delegate to the original controller, including its query and pagination reset.
      scope.querySelector('[data-filter-reset]')?.click();
      if (dialog.open) event.currentTarget.focus({ preventScroll: true });
      scheduleSync();
    }, { signal });

    trigger.addEventListener('click', () => {
      if (!dialog.open) dialog.showModal();
      trigger.setAttribute('aria-expanded', 'true');
    }, { signal });
    this.querySelectorAll('[data-drawer-close]').forEach(button => {
      button.addEventListener('click', () => dialog.close(), { signal });
    });
    dialog.addEventListener('close', () => {
      trigger.setAttribute('aria-expanded', 'false');
      trigger.focus({ preventScroll: true });
    }, { signal });
    // Only a click that starts and ends on the backdrop closes the drawer.
    let backdropPress = false;
    const outside = event => {
      const box = dialog.getBoundingClientRect();
      return event.clientX < box.left || event.clientX > box.right
        || event.clientY < box.top || event.clientY > box.bottom;
    };
    dialog.addEventListener('pointerdown', event => {
      backdropPress = event.target === dialog && outside(event);
    }, { signal });
    dialog.addEventListener('click', event => {
      if (backdropPress && event.target === dialog && outside(event)) dialog.close();
      backdropPress = false;
    }, { signal });
  }

  disconnectedCallback() {
    this.abort?.abort();
    this.observer?.disconnect();
  }
}

if (!customElements.get('filter-drawer')) customElements.define('filter-drawer', FilterDrawer);
