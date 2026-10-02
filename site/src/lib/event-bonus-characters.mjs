/**
 * Resolve the cast from bonus constraints, not the event's story cast.
 * @template {{id:string, masterId:number, bandId:string}} T
 * @param {{constraints:Record<string,number|null>}[]} effects
 * @param {{characters:T[], bands:{id:string,masterId:number}[], memberCards:{masterId:number,characterId:string}[], supportCards:{masterId:number,featuredCharacterIds:string[]}[]}} catalog
 * @returns {T[]}
 */
export function eventBonusCharacters(effects, catalog) {
  const selected = new Set();
  for (const {constraints: c} of effects) {
    // Attribute-only bonuses do not identify a particular cast.
    if (!c.characterId && !c.bandId && !c.memberCardId && !c.supportCardId) continue;
    const band = c.bandId ? catalog.bands.find(band => band.masterId === c.bandId) : null;
    const member = c.memberCardId ? catalog.memberCards.find(card => card.masterId === c.memberCardId) : null;
    const support = c.supportCardId ? catalog.supportCards.find(card => card.masterId === c.supportCardId) : null;
    for (const character of catalog.characters) {
      // Conditions in one rule intersect; separate rules contribute their union.
      if (c.characterId && character.masterId !== c.characterId) continue;
      if (c.bandId && character.bandId !== band?.id) continue;
      if (c.memberCardId && character.id !== member?.characterId) continue;
      if (c.supportCardId && !support?.featuredCharacterIds.includes(character.id)) continue;
      selected.add(character.id);
    }
  }
  return catalog.characters.filter(character => selected.has(character.id));
}
