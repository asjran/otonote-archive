/** Validate the repaired record before preserving its exact original and replacing it. */
export function readBandItemRecord({storage,key,repair,validate}) {
  const raw=storage.getItem(key);
  if(raw===null)return {value:null,notice:''};
  const repaired=repair(JSON.parse(raw));
  const value=validate(repaired.value);
  if(!repaired.changes.length)return {value,notice:''};
  try {
    let index=1,backupKey;
    do {backupKey=`${key}:band-item-caps:v1:backup:${index++}`;} while(storage.getItem(backupKey)!==null&&storage.getItem(backupKey)!==raw);
    if(storage.getItem(key)!==raw)throw Error('记录已在其他窗口修改');
    if(storage.getItem(backupKey)===null)storage.setItem(backupKey,raw);
    if(storage.getItem(key)!==raw)throw Error('记录已在其他窗口修改');
    storage.setItem(key,JSON.stringify(value));
    return {value,notice:'已将旧乐器记录调整到当前升级上限，原始备份已保留。'};
  } catch(error) {
    // A full or unavailable store must not make the entire inventory unreadable.
    // The untouched primary record still preserves every original value.
    if(storage.getItem(key)!==raw)throw error;
    return {value,notice:'旧乐器记录已按当前升级上限用于本次计算；保存修正失败，原记录仍保留。'};
  }
}
