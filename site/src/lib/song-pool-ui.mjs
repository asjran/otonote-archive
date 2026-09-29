import { calculateSongPool } from './song-pool.mjs';
const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
const format=n=>n.toLocaleString(undefined,{maximumFractionDigits:2});
export function setupSongPool(workbench) {
  const q=s=>workbench.querySelector(s),button=q('[data-song-pool-run]');if(!button)return null;
  let version=0;
  const invalidate=()=>{version++;button.disabled=false;q('[data-song-pool-results]').replaceChildren();q('[data-song-pool-status]').textContent='输入已更新，可重新比较曲池。';};
  for(const s of ['[data-song-pool-input]','[data-song-pool-mode]'])q(s).addEventListener('change',invalidate);
  button.addEventListener('click',async()=>{
    invalidate();const request=version;button.disabled=true;const status=q('[data-song-pool-status]');
    try {
      const input=q('[data-song-pool-input]').value.trim(),mode=q('[data-song-pool-mode]').value,draft=structuredClone(workbench.draft);
      const songs=input?input.split(/[,，\s]+/).map(token=>{
        const match=/^(?:music-)?(\d+)(?::(\d+(?:\.\d+)?))?$/.exec(token);if(!match)throw new Error(`无效曲池条目：${token}`);
        return {trackId:`music-${Number(match[1])}`,weight:match[2]===undefined?1:Number(match[2])};
      }):workbench.data.tracks.map(t=>({trackId:t.id,weight:1}));
      for(const [i,song] of songs.entries()) {
        if(mode==='power')break;
        status.textContent=`载入谱面 ${i+1}/${songs.length}…`;
        const c=workbench.data.charts.find(c=>c.trackId===song.trackId&&c.difficulty===draft.selectedDifficulty);
        if(!c?.analysisDataUrl)throw new Error(`歌曲 ${song.trackId} 缺少当前难度谱面`);
        const response=await fetch(c.analysisDataUrl);if(!response.ok)throw new Error('谱面加载失败');
        song.chart={...await response.json(),sourceReleaseId:workbench.data.sourceReleaseId};if(request!==version)return;
      }
      const result=calculateSongPool({rules:workbench.data.formalRules,draft,songs,mode});
      if(request!==version)return;
      status.textContent=`${result.rows.length} 首歌曲；综合力加权平均 ${format(result.expectedPower)}，范围 ${format(result.minimumPower)}–${format(result.maximumPower)}。${mode==='ordinary'?`歌曲加权期望分 ${format(result.expectedScore)}，最差歌曲/技能顺序分 ${format(result.worstScore)}。`:mode==='gekisou'?'激奏完整计分尚不可用，以下只展示综合力与任务。':''}${result.warnings.join(' ')}`;
      const table=node('table',''),head=node('tr','');for(const label of ['歌曲','属性','权重','综合力',mode==='ordinary'?'期望分数':'任务（COMBO / LUCK / JUST）'])head.append(node('th',label));table.append(head);
      for(const r of result.rows){const tr=node('tr','');for(const text of [workbench.data.tracks.find(t=>t.id===r.trackId)?.title??r.trackId,r.attribute,r.weight,format(r.power),mode==='ordinary'?format(r.expectedScore):r.missions.map(m=>({1:'COMBO',2:'LUCK',3:'JUST'})[m]??'?').join(' / ')])tr.append(node('td',String(text)));table.append(tr);}
      q('[data-song-pool-results]').append(table);
    }catch(error){if(request===version)status.textContent=error.message;}finally{if(request===version)button.disabled=false;}
  });
  return {invalidate};
}
