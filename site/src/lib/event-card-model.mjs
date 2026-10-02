/** A card may be both a bonus target and obtainable from several event rewards. */
export function collectEventCards(event, resolveCard) {
  const cards = new Map();
  const add = (reward, source, bonus = false) => {
    if (![2, 3].includes(reward.resourceType) || !reward.resourceId) return;
    const key = `${reward.resourceType}:${reward.resourceId}`;
    if (!cards.has(key)) cards.set(key, { ...reward, bonus: false, sources: [] });
    const card = cards.get(key);
    card.bonus ||= bonus;
    if (source) card.sources.push(source);
  };
  event.pickupCards.forEach(card => add(card));
  event.achievements.forEach(row => row.rewards.forEach(reward => add(reward, { kind: 'points', points: row.points, count: reward.count })));
  event.exchanges.forEach(shop => shop.products.forEach(product => add(product.reward, { kind: 'exchange', cost: product.cost, count: product.reward.count, limit: product.limit })));
  [...event.ranking.rewards, ...event.challengeSongs.flatMap(song => song.rankingRewards)].forEach(row => row.rewards.forEach(reward => add(reward, { kind: 'ranking' })));
  for (const effect of event.effects) {
    for (const [type, id] of [[2, effect.constraints.memberCardId], [3, effect.constraints.supportCardId]]) {
      if (!id) continue;
      const reward = resolveCard(type, id) ?? { resourceType: type, resourceId: id, name: `#${id}`, resolved: false, rarity: null, count: null };
      add(reward, null, true);
    }
  }
  return [...cards.values()].sort((a, b) => a.resourceType - b.resourceType || a.resourceId - b.resourceId);
}
