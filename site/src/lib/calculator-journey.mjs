const el=(tag,text='',cls='')=>{const node=document.createElement(tag);node.textContent=text;node.className=cls;return node;};
export function setupCalculatorJourney(workbench) {
  if(!workbench.querySelector('[data-optimize-pairing]'))return null;
  const q=s=>workbench.querySelector(s),events=new AbortController(),listen=(node,type,fn)=>node.addEventListener(type,fn,{signal:events.signal});
  const root=el('section','','calculator-journey'),header=el('header','','journey-heading'),title=el('div');
  title.append(el('span','当前选择'));
  const context=el('p','','journey-context');title.append(context);
  const toggle=el('button','高级面板');toggle.type='button';header.append(title,toggle);root.append(header);
  const tasks=el('div','','journey-tasks');tasks.setAttribute('role','group');tasks.setAttribute('aria-label','选择配队任务');
  const automatic=el('button','帮我配一队'),saved=el('button','比较队伍 / 换卡');automatic.type=saved.type='button';tasks.append(automatic,saved);root.append(tasks);
  const savedPanel=el('section','','journey-saved');savedPanel.hidden=true;
  const nav=el('nav','','journey-steps');nav.setAttribute('aria-label','配队步骤');root.append(nav);
  const stepNotes=['歌曲与难度','导入或选择卡牌','模式与计算目标','比较并应用队伍'];
  const names=['选歌曲','选卡库','演出条件','看结果'],panels=names.map((name,i)=>{
    const panel=el('section','','journey-step');panel.dataset.journeyStep=String(i);panel.id=`journey-step-${i}`;
    const button=el('button');button.type='button';button.setAttribute('aria-label',`${i+1} ${name}`);
    const copy=el('span','','journey-step-copy');copy.append(el('strong',name),el('small',stepNotes[i]));button.append(el('span',String(i+1),'journey-step-number'),copy);button.setAttribute('aria-controls',panel.id);listen(button,'click',()=>show(i,true));nav.append(button);root.append(panel);return panel;
  });
  const footer=el('footer','','journey-footer'),previous=el('button','← 上一步'),next=el('button','下一步 →'),hint=el('p');
  previous.type=next.type='button';footer.append(previous,hint,next);root.append(footer);
  root.append(savedPanel);
  workbench.prepend(root);
  let step=0,guided=true,savedMode=false,moves=[],choiceGroups=[],manual,runArea,review,currentState=workbench.optimizerState??{};
  const navButtons=[...nav.children];
  function move(node,parent) {
    if(!node)return;
    const marker=document.createComment('guided-control-origin');node.before(marker);moves.push({node,marker,hidden:node.hidden});parent.append(node);
  }
  function moveSelector(selector,parent){const node=q(selector);move(node,parent);return node;}
  function choices(select,container,descriptions) {
    const field=select.closest('label');move(field,container);field.hidden=true;
    const group=el('div','','journey-choices');group.setAttribute('role','group');group.setAttribute('aria-label',select===q('[data-search-scope]')?'选择卡库':select===q('[data-pairing-mode]')?'选择演出模式':'选择搜索方式');
    const buttons=[];
    for(const [value,name,description] of descriptions) {
      const button=el('button');button.type='button';button.append(el('strong',name),el('span',description));
      listen(button,'click',()=>{select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));if(select===q('[data-search-scope]')&&value==='owned')q('[data-inventory-editor]').open=true;refresh();});group.append(button);buttons.push({button,value});
    }
    container.append(group);choiceGroups.push({select,buttons});
  }
  function subtitle(panel,title,text){panel.append(el('h3',title),el('p',text,'journey-intro'));}
  function mount() {
    panels.forEach(panel=>panel.replaceChildren());savedPanel.replaceChildren();choiceGroups=[];
    moveSelector('#song-settings',panels[0]);
    subtitle(panels[1],'用哪些卡来配？','推荐先导入游戏养成；也可以手动录入，或用全部满养成卡先体验。');
    choices(q('[data-search-scope]'),panels[1],[['owned','我的卡库','登录读取或导入 JSON，按实际持有和养成配队。'],['theoretical','全部卡牌','卡片按满养成比较，结果可能包含你还没有的卡。'],['selected','当前这十张','保留已选成员与留影，重新分配配对和队长。']]);
    moveSelector('[data-inventory-scope-note]',panels[1]);moveSelector('[data-inventory-editor]',panels[1]);
    manual=el('details','','journey-manual');manual.append(el('summary','编辑当前五名成员和五张留影'));panels[1].append(manual);
    moveSelector('.team-workbench-grid',manual);
    const editCards=el('details','','journey-card-picker');editCards.append(el('summary','更换成员或留影'));manual.append(editCards);moveSelector('.team-card-picker',editCards);
    listen(q('[data-team-slots]'),'click',()=>{editCards.open=true;});
    const account=moveSelector('#power-settings',panels[1]);
    const accountInputs=el('div','','journey-account');account.querySelector('summary').after(accountInputs);
    moveSelector('[data-account-tgw]',accountInputs);moveSelector('[data-tgw-bonus-note]',accountInputs);
    subtitle(panels[2],'这次想打普通，还是激奏？','默认 AP，以整首歌的平均分挑队伍。先拿一套推荐，再决定是否继续比较。');
    choices(q('[data-pairing-mode]'),panels[2],[['ordinary','普通自由演出','比较综合力、加分技能和留影延时。'],['gekisou','激奏演出','加上 COMBO / LUCK / JUST 三段任务与奖励。']]);
    moveSelector('[data-gekisou-settings]',panels[2]);
    review=el('dl','','journey-review');review.setAttribute('aria-label','本次配队条件');panels[2].append(review);
    panels[2].append(el('p','默认使用实用推荐：先筛选组合，再精算领先队伍。通常先保持默认即可。','journey-intro'));
    const advanced=el('details','','journey-advanced');advanced.append(el('summary','限定乐队、属性或调整目标（可选）'));panels[2].append(advanced);
    move(q('[data-search-effort]').closest('label'),advanced);
    moveSelector('[data-search-effort-note]',advanced);moveSelector('[data-search-space]',advanced);
    move(q('[data-pairing-objective]').closest('label'),advanced);moveSelector('[data-search-filters]',advanced);moveSelector('.optimizer-advanced',advanced);
    runArea=moveSelector('.calculator-start',panels[2]);
    panels[3].append(el('p','先比较推荐分数和成员／留影搭配，再应用队伍；需要核对时打开计分明细。结果为参考估算，尚未完成当前游戏版本的实战核验。','journey-results-tip'));
    moveSelector('.optimizer-results-panel',panels[3]);
    const presets=moveSelector('.workbench-song-pool',savedPanel);presets.open=true;
    const help=el('details','','journey-help');help.append(el('summary','配队攻略与计算说明'));panels[3].append(help);
    moveSelector('.calculator-strategy',help);moveSelector('.workbench-rules',help);moveSelector('[data-scoring-reference]',help);
    workbench.dataset.experience='guided';root.dataset.guided='true';nav.hidden=footer.hidden=false;toggle.textContent='高级面板';tasks.hidden=false;
    refresh();show(canVisit(step)?step:0);
  }
  function unmount() {
    // Restore children before their parent containers so every original location survives.
    for(const {node,marker,hidden} of moves.reverse()){marker.replaceWith(node);node.hidden=hidden;}
    q('.journey-account')?.remove();moves=[];choiceGroups=[];workbench.dataset.experience='advanced';root.dataset.guided='false';
    panels.forEach(panel=>panel.replaceChildren());savedPanel.replaceChildren();savedPanel.hidden=true;nav.hidden=footer.hidden=tasks.hidden=true;toggle.textContent='返回简洁引导';
    // The mode may have changed while guided; use its current value, not the initial hidden state.
    q('[data-gekisou-settings]').hidden=q('[data-pairing-mode]').value!=='gekisou';
  }
  function canVisit(index) {
    if(index===0)return true;
    if(index===1)return Boolean(currentState.songReady);
    if(index===2)return Boolean(currentState.songReady&&currentState.cardsReady);
    return Boolean(currentState.running||currentState.hasResults||currentState.finished);
  }
  function show(index,focus=false) {
    if(!guided||!canVisit(index))return;
    savedMode=false;step=index;panels.forEach((panel,i)=>panel.hidden=i!==step);
    navButtons.forEach((button,i)=>{if(i===step)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});
    if(step===3&&runArea)panels[3].prepend(runArea);else if(step===2&&runArea)footer.append(runArea);else if(runArea)panels[2].append(runArea);
    if(step===1&&q('[data-search-scope]').value==='owned')q('[data-inventory-editor]').open=true;
    refresh();
    if(focus){const heading=panels[step].querySelector('h2,h3');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}root.scrollIntoView({block:'start',behavior:'auto'});}
  }
  function refresh() {
    currentState=workbench.optimizerState??currentState;
    if(!guided||!manual)return;
    context.textContent=currentState.songReady?`${q('[data-song-selection]').textContent} · ${q(savedMode?'[data-preset-mode]':'[data-pairing-mode]').value==='gekisou'?'激奏演出':'普通自由演出'}`:'先选歌，再用你的卡库找一套配队。';
    const scope=q('[data-search-scope]').value;
    for(const {select,buttons} of choiceGroups)for(const {button,value} of buttons){button.setAttribute('aria-pressed',String(select.value===value));if(value==='custom')button.hidden=select.value!=='custom';}
    q('[data-inventory-editor]').hidden=scope!=='owned';manual.hidden=scope!=='selected';
    if(scope==='selected')manual.open=true;
    nav.hidden=savedMode;footer.hidden=savedMode||step===3;savedPanel.hidden=!savedMode;
    panels.forEach((panel,i)=>panel.hidden=savedMode||i!==step);
    automatic.setAttribute('aria-pressed',String(!savedMode));saved.setAttribute('aria-pressed',String(savedMode));
    navButtons.forEach((button,i)=>{button.disabled=!canVisit(i);button.dataset.complete=String(i<3&&canVisit(i+1));button.title=canVisit(i)?stepNotes[i]:i===1?'请先选择歌曲与难度':i===2?'请先准备好卡库':'开始计算后可查看结果';});
    if(review){
      const inventory=workbench.cardInventory;
      const source=scope==='owned'?`我的卡库 · ${inventory?.memberCardIds.length??0} 成员 / ${inventory?.supportCardIds.length??0} 留影`:scope==='theoretical'?'全部卡牌 · 满养成':'当前 5＋5 张卡';
      review.replaceChildren(...[['歌曲',q('[data-song-selection]').textContent.replace(/^已选：/,'')],['卡牌范围',source],['养成与判定',scope==='theoretical'?'卡片满养成 · AP / 满生命':'使用当前养成 · AP / 满生命']].map(([name,value])=>{const item=el('div');item.append(el('dt',name),el('dd',value));return item;}));
    }
    previous.disabled=step===0;next.hidden=step>=2;next.textContent=step===0?'选好了，准备卡库 →':'卡库准备好了，继续 →';next.disabled=!canVisit(step+1);
    hint.textContent=step===0?(currentState.songReady?'歌和难度选好了，接下来挑卡。':'点歌曲右侧的难度，选好后继续。'):step===1?(currentState.cardsReady?'卡库准备好了，接下来选择演出模式。':currentState.message??'先准备好五名不同角色和五张留影。'):step===2?'点击主按钮开始，结果会出现在下一步。':'结果仅包含已完成计分的队伍，检查明细可按需展开。';
  }
  listen(automatic,'click',()=>show(canVisit(step)?step:0,true));
  listen(saved,'click',()=>{savedMode=true;refresh();root.scrollIntoView({block:'start',behavior:'auto'});});
  listen(previous,'click',()=>show(step-1,true));listen(next,'click',()=>show(step+1,true));
  listen(toggle,'click',()=>{guided=!guided;if(guided)mount();else unmount();});
  listen(workbench,'optimizer-ui-state',event=>{currentState=event.detail;refresh();if(guided&&event.detail.running)show(3);});
  listen(workbench,'calculator-edit-team',()=>{if(!guided)return;q('[data-search-scope]').value='selected';q('[data-search-scope]').dispatchEvent(new Event('change',{bubbles:true}));show(1,true);manual.open=true;});
  listen(workbench,'change',refresh);
  listen(workbench,'calculator-open-inventory',()=>{q('[data-search-scope]').value='owned';q('[data-search-scope]').dispatchEvent(new Event('change',{bubbles:true}));show(1,true);});
  listen(workbench,'calculator-use-inventory',()=>show(2,true));
  // Make the guided defaults explicit in the visible choice cards, without changing the scoring rules.
  q('[data-search-scope]').value=workbench.draft.slots.every(s=>s.memberCardId&&s.supportCardId)?'selected':'owned';
  q('[data-search-scope]').dispatchEvent(new Event('change',{bubbles:true}));
  q('[data-search-effort]').value='practical';q('[data-search-effort]').dispatchEvent(new Event('change',{bubbles:true}));
  mount();
  return {refresh,disconnect:()=>events.abort()};
}
