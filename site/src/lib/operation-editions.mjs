import {mergeEditionRows,stableContent} from './edition-library.mjs';
export function operationKey(kind,row) {
  if(kind==='events')return row.story?.episodes?.length ? stableContent([row.mode,row.story.chapterId,row.story.episodes.map(e=>[e.id,e.number,e.isAnotherEpisode,e.isExtraEpisode])]) : null;
  if(kind==='recruitment')return row.bannerAssetName ? stableContent([row.bannerAssetName,row.pickupMemberCardIds,row.pickupSupportCardIds,row.products?.map(p=>[p.drawCount,p.ensuredCount,p.ensuredRarity])]) : null;
  return null;
}
export function annotateOperations(rows,other,kind,region,locale) {
  return mergeEditionRows(rows,other,{region,locale,key:row=>operationKey(kind,row),path:row=>`/${kind}/${row.id}/`,
    difference:row=>stableContent(kind==='events'?row.schedule:[row.startAt,row.endAt,row.probabilityGroups,row.products])}).filter(row=>row.sourceEdition===region);
}
