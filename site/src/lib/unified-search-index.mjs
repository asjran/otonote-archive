const coreTypes = new Set(["music", "character", "member_card", "support_card"]);
const text = (...values) => values.flat(Infinity).filter(value => value !== undefined && value !== null && value !== "").join(" ");

/**
 * @param {{ sourceReleaseId: string, entries: Array<{ id: string, type: string, title: string, href: string, subtitle?: string, searchableText?: string }> }} base
 * @param {{ releaseId: string, locale: string, library: { sourceReleaseId: string, locale: string, characters: Array<{id: number, name: string}>, bands: Array<{id: number, name: string}>, entries: Array<{id: string, title: string, description?: string, chapterName: string, characterIds: number[], bandIds: number[]}> }, items?: import('./game-database').ItemIndexRecord[], skills?: import('./game-database').SkillIndexRecord[] }} sources
 */
export function buildPublishedSearchIndex(base, { releaseId, locale, library, items = [], skills = [] }) {
  if (base.sourceReleaseId !== releaseId || library.sourceReleaseId !== releaseId || library.locale !== locale) {
    throw new Error("Search sources must belong to the active release and locale");
  }
  // The old story index contains unpublished episodes; use the reader's library.
  const entries = base.entries.filter(entry => coreTypes.has(entry.type));
  const characters = new Map(library.characters.map(entry => [entry.id, entry.name]));
  const bands = new Map(library.bands.map(entry => [entry.id, entry.name]));
  for (const story of library.entries) {
    const cast = story.characterIds.map(id => characters.get(id));
    const bandNames = story.bandIds.map(id => bands.get(id));
    entries.push({ id: story.id, type: "story", title: story.title,
      subtitle: text(story.chapterName, cast),
      href: `/stories/episodes/${encodeURIComponent(story.id)}/`,
      searchableText: text(story.title, story.description, story.chapterName, cast, bandNames, story.id) });
  }
  for (const item of items) entries.push({ id: item.id, type: "item", title: item.name,
    subtitle: item.description, href: `/database/items/#detail=${encodeURIComponent(item.id)}`,
    searchableText: text(item.name, item.phoneticName, item.description, item.masterId, item.id) });
  for (const skill of skills) entries.push({ id: skill.id, type: "skill", title: skill.name,
    subtitle: skill.highestSummary, href: `/database/skills/#detail=${encodeURIComponent(skill.id)}`,
    searchableText: text(skill.name, skill.highestSummary, skill.effects.map(effect => effect.name), skill.masterId, skill.id) });
  return { schemaVersion: 1, sourceReleaseId: releaseId, entries,
    suggestions: [...new Set(library.bands.map(band => band.name))].slice(0, 4) };
}
