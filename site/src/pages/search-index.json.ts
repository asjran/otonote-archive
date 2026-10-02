import base from "@projection-data/unified-search-index.json";
import { activeReleaseContext } from "../lib/release-context";
import { storyLibrary } from "../lib/shared-stories";
import { itemIndex, skillIndex } from "../lib/shared-database";
import {catalog} from '../lib/shared-catalog';
import {presenceLabel} from '../lib/edition-library.mjs';
import { buildPublishedSearchIndex } from "../lib/unified-search-index.mjs";

export const prerender = true;

export function GET() {
  const index = buildPublishedSearchIndex(base, {
    releaseId: activeReleaseContext.contentReleaseId,
    locale: activeReleaseContext.locale,
    library: storyLibrary,
    items: itemIndex,
    skills: skillIndex
  });
  const core = new Set(['music','character','member_card','support_card']);
  index.entries = index.entries.filter(entry=>!core.has(entry.type));
  for(const [kind,type] of [['musicTracks','music'],['characters','character'],['memberCards','member_card'],['supportCards','support_card']] as const) {
    for(const row of catalog[kind]) index.entries.push({id:row.id,type,title:Reflect.get(row,'title') ?? Reflect.get(row,'displayName'),
      href:row.sourceHref!,subtitle:presenceLabel(row.editionPresence,activeReleaseContext.locale==='en'),
      searchableText:[Reflect.get(row,'name'),Reflect.get(row,'subtitle'),Reflect.get(row,'description'),row.masterId].filter(Boolean).join(' ')});
  }
  const sources = new Map([...storyLibrary.entries,...itemIndex,...skillIndex].map(row=>[row.id,row]));
  for(const entry of index.entries) {
    const source=sources.get(entry.id);
    if(source?.sourceHref) entry.href=source.sourceHref;
  }
  return new Response(JSON.stringify(index), {
    headers: { "Content-Type": "application/json; charset=utf-8" }
  });
}
