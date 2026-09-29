// Media time is authoritative: buffering never lets the chart run ahead.
export function createMediaClock(audio) {
  let duration = 0;
  const time = () => Math.min(duration, Math.max(0, audio.currentTime || 0));
  return {
    time,
    get playing() { return !audio.paused && !audio.ended; },
    load(value) { audio.pause(); duration = Math.max(0, Number(value) || 0); audio.currentTime = 0; },
    async play() {
      if (!duration) return;
      if (audio.ended || time() >= duration) audio.currentTime = 0;
      await audio.play();
    },
    pause() { audio.pause(); },
    seek(value) { audio.currentTime = Math.max(0, Math.min(duration, Number(value) || 0)); },
    setRate(value) { audio.playbackRate = Math.max(0.25, Math.min(2, Number(value) || 1)); }
  };
}
