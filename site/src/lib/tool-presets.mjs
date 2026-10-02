import {scopedStorageKey,assertAccountServer} from './game-servers.mjs';
import {preparePresetDraft} from './preset-portfolio.mjs';

export function readToolPresets(rules,storage=localStorage) {
  const raw=storage.getItem(scopedStorageKey('presets',rules.sourceReleaseId));
  if(!raw)return [];
  const saved=JSON.parse(raw);assertAccountServer(saved.serverId);
  if(saved.schemaVersion!==1||saved.sourceReleaseId!==rules.sourceReleaseId||!Array.isArray(saved.candidates)||saved.candidates.length>100)throw Error('队伍版本不一致，请在配队工具重新保存');
  return saved.candidates.filter(c=>{
    if(typeof c.name!=='string'||c.sourceReleaseId!==rules.sourceReleaseId)return false;
    preparePresetDraft(rules,c.draft,{maximizeTrainable:false});return true;
  });
}
