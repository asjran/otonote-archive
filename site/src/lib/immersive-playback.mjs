// One clock per character, shared by every front/back layer belonging to her.
// Environment layers follow the scene clock. All clips stop at their last frame.
export function createImmersivePlayback(layers, characters = []) {
  const duration = Math.max(0, ...layers.map(layer => layer.duration));
  const clocks = new Map([['scene', { time: 0, duration, playing: true }]]);
  const owners = new Map();
  for (const character of characters) {
    const members = layers.filter(layer => character.nodes.includes(layer.id));
    if (!members.length || members.length !== character.nodes.length) throw Error('character-layers-unavailable');
    const key = String(character.id);
    clocks.set(key, { time: 0, duration: Math.max(...members.map(layer => layer.duration)), playing: true });
    for (const member of members) {
      if (owners.has(member.id)) throw Error('character-layer-overlap');
      owners.set(member.id, key);
    }
  }
  function apply() {
    for (const layer of layers) layer.apply(Math.min(layer.duration, clocks.get(owners.get(layer.id) ?? 'scene').time));
  }
  const clamp = (time, end) => Math.max(0, Math.min(Number.isFinite(time) ? time : 0, end));
  return {
    duration,
    get time() { return clocks.get('scene').time; },
    get playing() { return [...clocks.values()].some(clock => clock.playing); },
    get characters() { return characters.map(character => ({ id: character.id, ...clocks.get(String(character.id)) })); },
    advance(delta) {
      for (const clock of clocks.values()) if (clock.playing) {
        clock.time = clamp(clock.time + Math.max(0, delta), clock.duration);
        clock.playing = clock.time < clock.duration;
      }
      apply();
    },
    seek(time) {
      for (const clock of clocks.values()) {
        clock.time = clamp(time, clock.duration); clock.playing = clock.time < clock.duration;
      }
      apply();
    },
    replay(id) {
      const clock = clocks.get(String(id));
      if (!clock || String(id) === 'scene') return false;
      clock.time = 0; clock.playing = clock.duration > 0; apply(); return true;
    },
    snapshot() { return [...clocks].map(([id, clock]) => [id, { ...clock }]); },
    restore(snapshot) {
      for (const [id, clock] of snapshot) if (clocks.has(id)) clocks.set(id, { ...clock });
      apply();
    }
  };
}

export function isImmersiveTap(start, end) {
  return Math.hypot(end.x - start.x, end.y - start.y) <= 6;
}
