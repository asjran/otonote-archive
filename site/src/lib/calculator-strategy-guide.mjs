class CalculatorStrategyGuide extends HTMLElement {
  connectedCallback() {
    this.events?.abort();
    this.events=new AbortController();
    const {signal}=this.events,dialog=this.querySelector('dialog'),opener=this.querySelector('[data-strategy-open]');
    const panels=[...this.querySelectorAll('[data-strategy-panel]')],buttons=[...this.querySelectorAll('[data-strategy-chapter]')];
    const previous=this.querySelector('[data-strategy-previous]'),next=this.querySelector('[data-strategy-next]');
    let chapter=0;
    const listen=(target,type,fn)=>target.addEventListener(type,fn,{signal});
    const show=(index,focus=false)=>{
      chapter=Math.max(0,Math.min(panels.length-1,index));
      panels.forEach((panel,i)=>{panel.hidden=i!==chapter;});
      buttons.forEach((button,i)=>{if(i===chapter)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});
      previous.disabled=chapter===0;next.disabled=chapter===panels.length-1;
      this.querySelector('[data-strategy-page]').textContent=`${chapter+1} / ${panels.length}`;
      this.querySelector('[data-strategy-reader]').scrollTop=0;
      if(focus)panels[chapter].querySelector('h3').focus({preventScroll:true});
    };
    listen(opener,'click',()=>{if(!dialog.open){dialog.showModal();opener.setAttribute('aria-expanded','true');}});
    listen(this.querySelector('[data-strategy-close]'),'click',()=>dialog.close());
    listen(dialog,'close',()=>{opener.setAttribute('aria-expanded','false');if(this.isConnected)opener.focus({preventScroll:true});});
    let backdropDown=false;
    const outside=event=>{const r=dialog.getBoundingClientRect();return event.target===dialog&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom);};
    listen(dialog,'pointerdown',event=>{backdropDown=outside(event);});
    listen(dialog,'click',event=>{if(backdropDown&&outside(event))dialog.close();backdropDown=false;});
    buttons.forEach((button,i)=>listen(button,'click',()=>show(i,true)));
    listen(previous,'click',()=>show(chapter-1,true));listen(next,'click',()=>show(chapter+1,true));
    show(0);
  }
  disconnectedCallback(){this.events?.abort();this.querySelector('dialog')?.close();}
}
if(!customElements.get('calculator-strategy-guide'))customElements.define('calculator-strategy-guide',CalculatorStrategyGuide);
