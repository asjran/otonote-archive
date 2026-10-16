/** Keep modal Tab navigation in the topmost dialog, including nested dialogs. */
export function containModalFocus(dialog,event) {
  if(event.key!=='Tab'||event.altKey||event.ctrlKey||event.metaKey||!dialog.open||!dialog.matches(':modal')||dialog.querySelector('dialog[open]'))return;
  const fields=[...dialog.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')]
    .filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length);
  const first=fields[0],last=fields.at(-1),active=dialog.ownerDocument.activeElement;
  if(!first){event.preventDefault();dialog.focus();return;}
  if(!dialog.contains(active)||(event.shiftKey?active===first:active===last)){
    event.preventDefault();(event.shiftKey?last:first).focus();
  }
}
