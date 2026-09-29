// Monotonic silent playback clock. Pausing and seeking preserve chart time.
export function createDemoClock(now = () => performance.now()) {
  let position = 0, duration = 0, anchor = now(), rate = 1, playing = false;
  const time = () => {
    const value = Math.min(duration, position + (playing ? (now() - anchor) / 1000 * rate : 0));
    if (value >= duration) { position = duration; playing = false; }
    return value;
  };
  const pause = () => { position = time(); playing = false; };
  return {
    time,
    get playing() { time(); return playing; },
    load(value) { pause(); duration = Math.max(0, Number(value) || 0); position = 0; },
    play() { if (!duration) return; if (time() >= duration) position = 0; anchor = now(); playing = true; },
    pause,
    seek(value) { position = Math.max(0, Math.min(duration, Number(value) || 0)); anchor = now(); },
    setRate(value) { position = time(); rate = Math.max(0.25, Math.min(2, Number(value) || 1)); anchor = now(); }
  };
}
