// Media time is authoritative: buffering never lets the chart run ahead.
export function createMediaClock(audio) {
  let duration = 0;
  let requestedTime = null;
  const clamp = value => Math.max(0, Math.min(duration, Number(value) || 0));
  const time = () => clamp(requestedTime ?? audio.currentTime);
  const applySeek = () => {
    // With preload=none, a pre-metadata currentTime assignment may be ignored
    // or reset during resource selection. Retain the latest user intent until
    // the element has a timeline, then return authority to decoded media time.
    if (requestedTime == null || audio.readyState === 0) return;
    audio.currentTime = requestedTime;
    requestedTime = null;
  };
  const seek = value => { requestedTime = clamp(value); applySeek(); };
  audio.addEventListener?.('loadedmetadata', applySeek);
  return {
    time,
    get playing() { return !audio.paused && !audio.ended; },
    load(value) { audio.pause(); duration = Math.max(0, Number(value) || 0); seek(0); },
    async play() {
      if (!duration) return;
      if (audio.ended || time() >= duration) seek(0);
      applySeek();
      await audio.play();
      applySeek();
    },
    pause() { audio.pause(); },
    seek,
    setRate(value) { audio.playbackRate = Math.max(0.25, Math.min(2, Number(value) || 1)); },
    destroy() { audio.pause(); audio.removeEventListener?.('loadedmetadata', applySeek); requestedTime = null; }
  };
}
