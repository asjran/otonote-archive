const normalize = value => String(value ?? '').normalize('NFKC').replace(/\s+/g,'').toLocaleLowerCase();
/** Exact names and explicit aliases only; ambiguous or group speakers stay textual. */
export function createSpeakerResolver(characters) {
  const byName = new Map();
  for (const character of characters) {
    const names = [character.displayName,character.shortName,...(character.aliases??[]),...Object.values(character.localizedText??{})];
    for (const name of names.flatMap(name=>[name,...String(name).split(/\s*\/\s*/)])) {
      const key = normalize(name); if (!key) continue;
      if (byName.has(key) && byName.get(key)?.id !== character.id) byName.set(key,null);
      else if (!byName.has(key)) byName.set(key,character);
    }
  }
  return speaker => byName.get(normalize(speaker)) ?? null;
}
