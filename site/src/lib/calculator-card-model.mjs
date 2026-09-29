// Shared by the manual picker, inventory and final lineup. Descriptions are
// resolved at the configured level; browsing an unowned card is marked maximum.
export function cardSkillRows(card, rules, growth, { maximum = false } = {}) {
  if (!card) return [];
  const member = card.kind === 'member', table = member ? 'Member' : 'Support';
  const native = rules.tables[`${table}Card`].find(r => r._id === card.masterId);
  const rank = rules.tables[`${table}CardRank`].find(r => r._group === native?.[`_${member ? 'member' : 'support'}CardRankGroup`] && r._rank === (growth?.rank ?? 1));
  return (card.skills ?? []).map(skill => {
    let level;
    if (maximum) level = Math.max(...skill.levels.map(l => l.level));
    else if (skill.slot === 'live') level = growth?.skillLevel ?? 1;
    else if (skill.slot === 'gekisou') level = growth?.gekisouSkillLevel ?? 1;
    else if (skill.slot === 'leader') level = rank?._leaderSkillLevel;
    else {
      const match = /^(gekisou_)?support_(\d)$/.exec(skill.slot);
      if (match) level = rank?.[`_${match[1] ? 'gekisouSupport' : 'support'}Skill0${match[2]}Level`];
    }
    const record = skill.levels.find(l => l.level === level);
    return { ...skill, level, summary: record?.summary ?? '当前等级的技能说明暂缺', available: Boolean(record), maximum };
  });
}

export function filterCalculatorCards(cards, filters = {}, inventory = {}) {
  const query = (filters.query ?? '').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const owned = c => (inventory[`${c.kind}CardIds`] ?? []).includes(c.id);
  const result = cards.filter(c => (!filters.kind || c.kind === filters.kind)
    && query.every(q => `${c.shortLabel} ${c.displayName} ${c.relationLabel} ${c.id} ${(c.skills ?? []).map(s => s.name).join(' ')}`.toLocaleLowerCase().includes(q))
    && (!filters.rarity || String(c.rarity) === filters.rarity)
    && (!filters.attributes?.length || filters.attributes.includes(String(c.attributeCode)))
    && (!filters.band || c.bandIds?.includes(filters.band))
    && (!filters.character || c.characterIds?.includes(filters.character))
    && (!filters.mission || c.skillFacets?.['gekisou-type']?.includes(filters.mission))
    && (!filters.effect || c.skillFacets?.['gekisou-effect']?.includes(filters.effect))
    && (!filters.normal || [...(c.skillFacets?.['live-type'] ?? []), ...(c.skillFacets?.['skill-role'] ?? [])].includes(filters.normal))
    && (!filters.owned || owned(c) === (filters.owned === 'owned')));
  return result.sort((a, b) => filters.sort === 'name' ? a.shortLabel.localeCompare(b.shortLabel, 'zh-CN')
    : filters.sort === 'newest' ? b.masterId - a.masterId
    : b.rarity - a.rarity || a.masterId - b.masterId);
}

export function cardPlacementConflict(card, draft, slotIndex, cardFor) {
  for (const [index, slot] of draft.slots.entries()) {
    if (index === slotIndex) continue;
    if (card.kind === 'support' && slot.supportCardId === card.id) return index;
    if (card.kind === 'member' && cardFor('member', slot.memberCardId)?.characterId === card.characterId) return index;
  }
  return -1;
}
