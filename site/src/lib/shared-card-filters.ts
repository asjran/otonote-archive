import {catalog} from './shared-catalog';
import {activeReleaseContext} from './release-context';
import {otherEditionGroup} from '../runtime/content.mjs';
import {buildCardSkillFilters} from './card-skill-filtering.mjs';
import type {CardDetailProjection, SkillDefinition} from './game-database';

export async function sharedCardFilters(mode:'member'|'support', projections:CardDetailProjection[], skills:SkillDefinition[]) {
  const {region,locale}=activeReleaseContext, other=region==='jp'?'global':'jp';
  const cards=mode==='member'?catalog.memberCards:catalog.supportCards;
  const native=buildCardSkillFilters(projections.filter(p=>cards.some(c=>c.id===p.cardId)),skills,locale,mode);
  const [secondary,definitions]=await Promise.all([
    otherEditionGroup(region,`@projection-data/database-shards/${mode}-cards/*.json`),
    otherEditionGroup(region,'@projection-data/database-shards/skills/*.json')
  ]);
  if(!secondary||!definitions)return native;
  const records=(group:Record<string,{record:unknown}>)=>Object.values(group).map(value=>value.record);
  const foreign=buildCardSkillFilters(records(secondary) as CardDetailProjection[],records(definitions) as SkillDefinition[],locale,mode);
  for(const card of cards)if(card.sourceEdition===other) {
    const value=foreign.records.get(card.sourceId);
    if(value)native.records.set(card.id,value);
  }
  for(const facet of native.facets) {
    const additions=foreign.facets.find(f=>f.name===facet.name)?.options??[];
    for(const option of additions)if(!facet.options.some(o=>o.value===option.value))facet.options.push(option);
  }
  return native;
}
