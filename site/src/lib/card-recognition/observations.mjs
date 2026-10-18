export const MODES = {
  'member-level': {label:'角色卡 · 等级', kind:'member'},
  'member-training': {label:'角色卡 · 特训', kind:'member'},
  support: {label:'留影卡', kind:'support'},
};

export function validateScreenshot(width,height) {
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)throw Error('图片尺寸无效');
  if(width*height>20_000_000)throw Error('图片超过 2000 万像素，请缩小后重试');
  if(width/height<1.1||width/height>4)throw Error('请使用未裁切的横屏列表截图');
}

export function numericValue(text, mode, confidence=100) {
  const clean=String(text).trim();
  if(!/^\d{1,3}$/.test(clean) || confidence<45)return null;
  const value=Number(clean), max=mode==='member-training'?5:100;
  return Number.isInteger(value)&&value>=1&&value<=max?value:null;
}

export function mergeObservations(rows, catalog) {
  const allowed=new Map(catalog.cards.map(c=>[c.id,c]));
  const cards=new Map(), conflicts=[], excluded=[];
  for(const row of rows){
    if(!row.selected || !row.cardId){excluded.push(row.key);continue;}
    const identity=allowed.get(row.cardId);
    if(!identity || identity.kind!==row.kind)throw Error('卡牌不属于当前识别索引');
    const next=cards.get(row.cardId)??{id:row.cardId,kind:row.kind,observations:{},sources:[]};
    const fields=row.kind==='member'?['level','training','awakeningStars']:['level','supportPetals'];
    for(const field of fields){
      const value=row.observations[field];
      if(value===null || value===undefined || value==='')continue;
      const max=field==='level'?100:5;
      if(!Number.isInteger(value)||value<1||value>max)throw Error(`${identity.name}：养成数值无效`);
      if(next.observations[field]!==undefined&&next.observations[field]!==value){
        conflicts.push({id:row.cardId,field,values:[next.observations[field],value]});
      }else next.observations[field]=value;
    }
    next.sources.push(row.key);cards.set(row.cardId,next);
  }
  return {format:'otonote-image-observations',schemaVersion:1,sourceReleaseId:catalog.sourceReleaseId,
    region:catalog.region,requiresConfirmation:true,cards:[...cards.values()],conflicts,excluded,
    note:'Game observations only. Missing skills stay missing. Not a full inventory backup; never replace an inventory with this draft.'};
}
