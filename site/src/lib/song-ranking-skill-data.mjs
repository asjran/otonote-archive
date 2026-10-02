import {editionSnapshot,checkedJson} from '../runtime/content.mjs';
import {prepareFormalChart} from './scoring-rules/formal-song-score.mjs';
import {scoringRulesAvailable} from './scoring-release-gate.mjs';
import {buildSkillWindowReference} from './song-skill-windows.mjs';
import {songRankingReplaySource} from './song-ranking-replay-input.mjs';
import {songRankingMeta} from './song-ranking-meta.mjs';

export async function attachSkillReferences(rankings,sources,locale){
  // Static page generation owns chart processing. A client-side fallback keeps
  // existing benchmarks usable without downloading or parsing every chart.
  const snapshots=new Map();
  for(const source of sources){
    if(!source?.catalog||!scoringRulesAvailable(source.rules,source.catalog.release.id))continue;
    try{snapshots.set(source.edition,await editionSnapshot(source.edition));}catch{}
  }
  for(const row of rankings.ordinary){
    if(row.pending||!row.benchmark?.power)continue;
    const source=sources.find(s=>s.edition===row.sourceEdition),manifest=snapshots.get(row.sourceEdition);
    row.replaySource=songRankingReplaySource(manifest,row,locale,source?.catalog.release.id);
    // New content carries the small reference table. Older server-rendered
    // snapshots may fill it here; browser navigation never loads every chart.
    if(typeof document!=='undefined'||row.skillReference&&row.meta)continue;
    const record=manifest?.locales?.[locale]?.files?.[`projection/music-charts/${row.sourceId}.json`];
    if(!record)continue;
    try{
      if(typeof record.path!=='string'||record.path.startsWith('/')||record.path.split('/').some(p=>!p||p==='..')||/[%?#\\]/.test(record.path))continue;
      // Read sequentially without the document cache so all full charts are not retained in memory.
      const chart=await checkedJson(manifest.root+record.path,record.sha256);
      if(chart.id!==row.sourceId||chart.trackId!==row.gradeReferences?.[row.sourceEdition]?.trackId)continue;
      const timeline=prepareFormalChart(source.rules,{...chart,sourceReleaseId:source.catalog.release.id});
      row.skillReference=buildSkillWindowReference(source.rules,timeline,row.benchmark.power);
      row.meta=songRankingMeta(chart,timeline);
    }catch{/* A missing chart must not fabricate custom-duration estimates. */}
  }
}
