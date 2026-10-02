import {activeReleaseContext} from './release-context';
import {otherEditionArtifact} from '../runtime/content.mjs';
import {mergeEditionRows, stableContent} from './edition-library.mjs';
const {region,locale} = activeReleaseContext;
export async function sharedRows<T extends {id: string | number}>(rows:T[], artifact:string, field:string,
  key:(row:T)=>string | null, path?: (row:T)=>string): Promise<T[]> {
  const other = await otherEditionArtifact(region,artifact);
  return mergeEditionRows(rows,other?.[field] ?? null,{region,locale,key,path}) as T[];
}
export const storyIdentity = (r: {contentIdentity?:string}) => r.contentIdentity ?? null;
export const galleryIdentity = (r: {sourceSha256?:string; mediaType:string; characterIds:number[]}) => r.sourceSha256
  ? stableContent([r.mediaType,r.sourceSha256,r.characterIds]) : null;
