import {SCORE_DIFFICULTY_REQUEST_EVENT,registerScoreWorkbenchElement} from './score-workbench-element.ts';
import {editionName} from './song-ranking-options.mjs';

export function rankingChartSelection(row,edition,sources) {
  const source=sources[edition],reference=row.editionChartReferences?.[edition];
  if(!['global','jp'].includes(edition)||!source||reference?.sourceReleaseId&&reference.sourceReleaseId!==source.releaseId)throw Error('当前版本的谱面资料尚未绑定，请稍后重试。');
  const trackId=reference?.trackId??(row.sourceEdition===edition?row.trackId.replace(/^(global|jp)--/,''):null);
  const charts=source.charts.filter(chart=>chart.trackId===trackId&&chart.url);
  if(!charts.some(chart=>chart.difficulty===row.difficulty))throw Error('当前版本尚未收录这张谱面的可视化数据，不使用其他版本替代。');
  return {releaseId:source.releaseId,charts,difficulty:row.difficulty};
}

export function setupRankingChartDialog(host,sources) {
  const document=host.ownerDocument,dialog=document.querySelector('[data-ranking-chart-dialog]'),template=document.querySelector('[data-ranking-chart-template]');
  const q=name=>dialog.querySelector(`[data-ranking-chart-${name}]`),mount=q('mount'),difficulty=q('difficulty'),status=q('status'),retry=q('retry');
  const events=new AbortController(),listen=(node,event,callback)=>node.addEventListener(event,callback,{signal:events.signal});
  let context,selection,view,observer,origin,pressedOutside=false;
  const stop=()=>{observer?.disconnect();observer=null;mount.replaceChildren();view=null;};
  const outside=event=>{const r=dialog.getBoundingClientRect();return event.target===dialog&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom);};
  const load=()=>{
    stop();retry.hidden=true;status.textContent='正在加载谱面…';status.hidden=false;dialog.dataset.loadState='loading';
    difficulty.replaceChildren();difficulty.disabled=true;
    try {
      selection=rankingChartSelection(context.row,context.edition,sources);
      difficulty.replaceChildren();difficulty.disabled=false;
      for(const chart of selection.charts){const option=document.createElement('option');option.value=chart.difficulty;option.textContent=`${chart.difficulty.toUpperCase()} · Lv.${chart.level??'—'}`;difficulty.append(option);}
      const selected=selection.charts.some(chart=>chart.difficulty===context.difficulty)?context.difficulty:selection.difficulty;
      difficulty.value=selected;context.difficulty=selected;
      view=template.content.querySelector('score-workbench').cloneNode(true);
      view.dataset.trackTitle=context.row.title;view.dataset.embedded='true';view.dataset.initialDifficulty=selected;
      const records=view.querySelector('[data-score-chart-records]');records.replaceChildren();
      for(const chart of selection.charts){const record=document.createElement('span');record.dataset.chartId=`${context.edition}:${selection.releaseId}:${chart.id}`;record.dataset.difficulty=chart.difficulty;record.dataset.url=chart.url;records.append(record);}
      const error=view.querySelector('[data-score-error]');error.textContent='谱面数据读取失败，请重试。不会使用其他版本的谱面替代。';
      const sync=()=>{const failed=!error.hidden,ready=view?.hasAttribute('data-ready');retry.hidden=!failed;status.hidden=Boolean(ready);status.textContent=failed?'谱面加载失败，可重新加载。':'正在加载谱面…';dialog.dataset.loadState=failed?'error':ready?'ready':'loading';};
      observer=new MutationObserver(sync);observer.observe(view,{attributes:true,subtree:true,attributeFilter:['hidden','data-ready']});mount.append(view);sync();
    } catch(error) {difficulty.disabled=true;status.textContent=error.message;retry.hidden=false;dialog.dataset.loadState='error';}
  };
  listen(difficulty,'change',()=>{if(!view)return;context.difficulty=difficulty.value;view.dataset.initialDifficulty=difficulty.value;window.dispatchEvent(new CustomEvent(SCORE_DIFFICULTY_REQUEST_EVENT,{detail:{difficulty:difficulty.value}}));});
  listen(retry,'click',load);listen(q('close'),'click',()=>dialog.close());
  listen(dialog,'pointerdown',event=>pressedOutside=outside(event));
  listen(dialog,'click',event=>{if(pressedOutside&&outside(event))dialog.close();pressedOutside=false;});
  listen(dialog,'close',()=>{stop();const target=origin?.isConnected?origin:[...(host.querySelectorAll?.('[data-ranking-chart-open]')??[])].find(button=>button.dataset.rankingChartOpen===context?.row.id)??host.querySelector?.('[data-metric]');target?.focus({preventScroll:true});});
  return {
    open(row,edition){registerScoreWorkbenchElement();origin=document.activeElement;context={row,edition,difficulty:row.difficulty};q('song').textContent=`${row.title} · ${editionName(edition,document.documentElement.lang.startsWith('en'))}`;if(!dialog.open)dialog.showModal();load();dialog.querySelector('.song-dialog-body').scrollTop=0;},
    destroy(){stop();dialog.close();events.abort();}
  };
}
