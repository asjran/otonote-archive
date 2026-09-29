const formatTime = value => {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
};

class SongAudioPlayer extends HTMLElement {
  connectedCallback() {
    this.events?.abort();
    this.events = new AbortController();
    const { signal } = this.events;
    const listen = (target, event, callback, options = {}) => target.addEventListener(event, callback, { ...options, signal });
    const audio = this.querySelector('[data-song-audio]');
    const play = this.querySelector('[data-audio-play]');
    const seek = this.querySelector('[data-audio-seek]');
    const time = this.querySelector('[data-audio-time]');
    const status = this.querySelector('[data-audio-status]');
    const download = this.querySelector('[data-audio-download]');
    const versions = [...this.querySelectorAll('[data-audio-version]')];
    let selected = versions.find(button => button.getAttribute('aria-pressed') === 'true');
    download.title = download.getAttribute('aria-label');
    let attempt = 0;
    const message = text => { status.textContent = text; status.hidden = !text; };
    const sync = () => {
      const duration = Number.isFinite(audio.duration) ? audio.duration : Number(selected.dataset.duration);
      seek.max = String(duration);
      seek.disabled = audio.readyState === 0;
      seek.value = String(audio.currentTime || 0);
      seek.style.setProperty('--audio-progress', `${duration > 0 ? Math.min(100, audio.currentTime / duration * 100) : 0}%`);
      seek.setAttribute('aria-valuetext', `${formatTime(audio.currentTime)} / ${formatTime(duration)}`);
      time.textContent = `${formatTime(audio.currentTime)} / ${formatTime(duration)}`;
      const playing = !audio.paused && !audio.ended;
      play.setAttribute('aria-label', playing ? '暂停音频' : '播放音频');
      this.querySelector('[data-audio-play-icon]').hidden = playing;
      this.querySelector('[data-audio-pause-icon]').hidden = !playing;
    };
    const pause = () => { attempt++; audio.pause(); sync(); };
    listen(play, 'click', async () => {
      if (!audio.paused) { pause(); return; }
      const current = ++attempt;
      message('');
      try {
        if (audio.error) audio.load();
        await audio.play();
        if (signal.aborted || current !== attempt) audio.pause();
      } catch (error) {
        if (!signal.aborted && current === attempt && error.name !== 'AbortError') message('音频暂时无法播放，请重试。');
      }
      sync();
    });
    versions.forEach(button => listen(button, 'click', () => {
      if (selected === button) return;
      pause();
      selected = button;
      versions.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      audio.src = button.dataset.url;
      audio.load();
      download.href = button.dataset.url;
      download.download = button.dataset.filename;
      download.hidden = button.dataset.download !== 'true';
      download.setAttribute('aria-label', `下载${button.textContent.trim()}音频`);
      download.title = download.getAttribute('aria-label');
      message('');
      sync();
    }));
    listen(seek, 'input', () => {
      if (audio.readyState > 0) audio.currentTime = Number(seek.value);
      sync();
    });
    for (const event of ['play', 'pause', 'ended', 'loadedmetadata', 'durationchange', 'timeupdate']) listen(audio, event, sync);
    listen(audio, 'error', () => { message('音频加载失败，请重试。'); sync(); });
    listen(audio, 'playing', () => message(''));
    listen(audio, 'waiting', () => message('缓冲中…'));
    listen(document, 'play', event => { if (event.target !== audio) pause(); }, { capture: true });
    listen(window, 'song-detail-view-change', event => { if (event.detail?.view) pause(); });
    listen(window, 'pagehide', pause);
    sync();
  }
  disconnectedCallback() {
    this.events?.abort();
    this.querySelector('audio')?.pause();
  }
}
if (!customElements.get('song-audio-player')) customElements.define('song-audio-player', SongAudioPlayer);
