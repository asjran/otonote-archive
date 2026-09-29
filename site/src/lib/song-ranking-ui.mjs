import { rankSongRows, RANKING_METRICS } from './song-ranking-view.mjs';
const node = (tag, text = '', cls = '') => { const e = document.createElement(tag); e.textContent = text; e.className = cls; return e; };
const number = (n, digits = 0) => Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '—';
const metricValue = (key, n) => !Number.isFinite(n) ? '—' : key === 'rankingBonusShare' ? `${number(n * 100, 2)}%`
  : key.endsWith('Factor') || key.endsWith('Multiplier') ? `${number(n, 4)}×` : number(n, 2);
class SongRanking extends HTMLElement {
  connectedCallback() {
    if (this.events) return;
    this.data = JSON.parse(this.querySelector('[data-ranking-data]').textContent);
    this.mode = 'ordinary'; this.metric = 'expectedScore'; this.page = 0; this.events = new AbortController(); this.expanded = new Set();
    const listen = (el, type, fn) => el.addEventListener(type, fn, { signal: this.events.signal });
    for (const button of this.querySelectorAll('[data-mode]')) listen(button, 'click', () => {
      this.mode = button.dataset.mode; this.page = 0; this.expanded.clear();
      if (this.mode === 'ordinary' && ['gekisouMultiplier','rankingBonusShare'].includes(this.metric)) this.metric = 'expectedScore';
      this.render();
    });
    for (const input of this.querySelectorAll('[data-filter], [data-duration]')) listen(input, 'input', () => { this.page = 0; this.render(); });
    for (const button of this.querySelectorAll('[data-board], [data-sort]')) listen(button, 'click', () => { this.metric = button.dataset.board ?? button.dataset.sort; this.page = 0; this.render(); });
    listen(this.querySelector('[data-metric]'), 'change', event => { this.metric = event.target.value || 'expectedScore'; this.page = 0; this.render(); });
    listen(this.querySelector('[data-prev]'), 'click', () => { this.page--; this.render(); });
    listen(this.querySelector('[data-next]'), 'click', () => { this.page++; this.render(); });
    listen(this.querySelector('[data-reset]'), 'click', () => { for (const input of this.querySelectorAll('[data-filter]')) input.value = input.dataset.filter === 'query' ? '' : 'all'; this.page = 0; this.render(); });
    this.render();
  }
  disconnectedCallback() { this.events?.abort(); this.events = null; }
  render() {
    const filters = Object.fromEntries([...this.querySelectorAll('[data-filter]')].map(e => [e.dataset.filter, e.value]));
    const timing = { durationBasis: this.querySelector('[data-duration]').value };
    const rows = this.data.rankings[this.mode];
    const options = { ...filters, ...timing, metric: this.metric };
    const ranked = rankSongRows(rows, options);
    const byScore = rankSongRows(rows, { ...options, metric: 'expectedScore' });
    const byEfficiency = rankSongRows(rows, { ...options, metric: 'efficiency' }).filter(row => row.rank !== null);
    const maxScore = byScore[0]?.expectedScore || 1, maxEfficiency = byEfficiency[0]?.efficiency || 1;
    const size = 25, pages = Math.max(1, Math.ceil(ranked.length / size));
    this.page = Math.max(0, Math.min(this.page, pages - 1));
    for (const button of this.querySelectorAll('[data-mode]')) button.setAttribute('aria-pressed', String(button.dataset.mode === this.mode));
    for (const button of this.querySelectorAll('[data-board]')) button.setAttribute('aria-pressed', String(button.dataset.board === this.metric));
    const metricSelect = this.querySelector('[data-metric]');
    for (const option of metricSelect.options) option.disabled = this.mode === 'ordinary' && ['gekisouMultiplier','rankingBonusShare'].includes(option.value);
    metricSelect.value = ['expectedScore','efficiency'].includes(this.metric) ? '' : this.metric;
    for (const button of this.querySelectorAll('[data-sort]')) {
      const active = button.dataset.sort === this.metric;
      button.textContent = `${button.dataset.sort === 'expectedScore' ? '基准得分' : '每秒得分'}${active ? ' ↓' : ''}`;
      button.closest('th').setAttribute('aria-sort', active ? 'descending' : 'none');
    }
    this.querySelector('[data-count]').textContent = `${ranked.length} 张谱面`;
    this.querySelector('[data-context]').textContent = `${this.mode === 'ordinary' ? '普通演出' : '激奏演出'} · ${timing.durationBasis === 'chart' ? '谱面时长' : '音频时长'} · ${RANKING_METRICS[this.metric]}排序`;
    this.querySelector('[data-page]').textContent = `${this.page + 1} / ${pages}`;
    this.querySelector('[data-range]').textContent = ranked.length ? `第 ${this.page * size + 1}–${Math.min(ranked.length, (this.page + 1) * size)} 项，共 ${ranked.length} 项` : '没有匹配结果';
    this.querySelector('[data-prev]').disabled = this.page === 0;
    this.querySelector('[data-next]').disabled = this.page === pages - 1;
    this.querySelector('[data-empty]').hidden = ranked.length > 0;
    const picks = this.querySelector('[data-picks]'); picks.replaceChildren();
    if (ranked.length) {
      picks.append(this.pick(byScore[0], 'score', '单局高分', `${number(maxScore)} 分`, `相同基准下，一局出分最高${byScore[1]?.expectedScore === maxScore ? '（并列）' : ''}`));
      if (byEfficiency.length) picks.append(this.pick(byEfficiency[0], 'efficiency', '单位时间更快', `${number(maxEfficiency)} 分 / 秒`, byEfficiency[0].id === byScore[0].id ? '这张谱面同时领跑出分与效率' : `按${timing.durationBasis === 'chart' ? '谱面' : '音频'}时长，得分更紧凑${byEfficiency[1]?.efficiency === maxEfficiency ? '（并列）' : ''}`));
      else picks.append(node('div', '当前筛选缺少有效时长，无法比较效率。', 'ranking-pick ranking-pick--empty'));
    }
    const factorKey = ['expectedScore','efficiency'].includes(this.metric) ? 'scoreMultiplier' : this.metric;
    this.querySelector('[data-factor-heading]').textContent = RANKING_METRICS[factorKey];
    const body = this.querySelector('[data-rows]'); body.replaceChildren();
    for (const row of ranked.slice(this.page * size, (this.page + 1) * size)) {
      const tr = node('tr'); if (row.rank > 0 && row.rank <= 3) tr.dataset.podium = String(row.rank);
      tr.append(node('td', row.rank === null ? '—' : String(row.rank).padStart(2, '0'), 'ranking-position'));
      const song = node('td', '', 'ranking-song'), face = node('div', '', 'ranking-track');
      const jacket = this.data.artwork[row.trackId];
      if (jacket) { const img = node('img'); img.src = jacket; img.alt = ''; img.width = img.height = 48; img.loading = 'lazy'; face.append(img); }
      const title = node('div'); title.append(node('strong', row.title));
      const subtitle = node('div', '', 'ranking-subtitle'), badge = node('span', row.difficulty.toUpperCase(), 'ranking-difficulty'); badge.dataset.difficulty = row.difficulty;
      subtitle.append(badge, node('span', `Lv.${row.level}`), node('small', row.bandLabels.join(' / '))); title.append(subtitle); face.append(title); song.append(face); tr.append(song);
      tr.append(this.meter(row.expectedScore, maxScore, 'score', '基准得分', this.metric === 'expectedScore'));
      tr.append(this.meter(row.efficiency, maxEfficiency, 'efficiency', '每秒得分', this.metric === 'efficiency'));
      const factor = node('td', '', 'ranking-factor'); factor.append(node('small', RANKING_METRICS[factorKey]), node('strong', metricValue(factorKey, row[factorKey]))); tr.append(factor);
      const action = node('td', '', 'ranking-action'), button = node('button', this.expanded.has(row.id) ? '−' : '+'); button.type = 'button';
      button.setAttribute('aria-label', `查看 ${row.title} ${row.difficulty} 的倍率明细`); button.setAttribute('aria-expanded', String(this.expanded.has(row.id)));
      const detail = node('tr', '', 'ranking-detail'); detail.hidden = !this.expanded.has(row.id); detail.id = `detail-${row.id}`; button.setAttribute('aria-controls', detail.id);
      const content = node('td'); content.colSpan = 6; this.detail(content, row); detail.append(content);
      button.addEventListener('click', () => { detail.hidden = !detail.hidden; detail.hidden ? this.expanded.delete(row.id) : this.expanded.add(row.id); button.textContent = detail.hidden ? '+' : '−'; button.setAttribute('aria-expanded', String(!detail.hidden)); });
      action.append(button); tr.append(action); body.append(tr, detail);
    }
  }
  meter(value, max, type, label, active) {
    const td = node('td', '', `ranking-meter ranking-meter--${type}`); if (active) td.dataset.active = '';
    td.append(node('small', label), node('strong', number(value, 2)));
    const track = node('div', '', 'ranking-meter-track'), bar = node('span'); bar.style.width = `${Number.isFinite(value) ? Math.max(0, Math.min(100, value / max * 100)) : 0}%`; track.setAttribute('aria-hidden', 'true'); track.append(bar); td.append(track); return td;
  }
  pick(row, type, label, value, note) {
    const card = node('article', '', `ranking-pick ranking-pick--${type}`), art = node('div', '', 'ranking-pick-art');
    if (this.data.artwork[row.trackId]) { const img = node('img'); img.src = this.data.artwork[row.trackId]; img.alt = ''; art.append(img); }
    art.append(node('span', type === 'score' ? 'SCORE' : 'TEMPO')); card.append(art);
    const text = node('div', '', 'ranking-pick-copy'); text.append(node('span', label, 'ranking-pick-label'), node('h3', row.title), node('small', `${row.difficulty.toUpperCase()} · Lv.${row.level}`), node('strong', value), node('p', note)); card.append(text); return card;
  }
  detail(root, row) {
    root.append(node('p', `${row.title} · ${row.difficulty.toUpperCase()} / 得分拆解`, 'ranking-detail-title'));
    const values = [['难度倍率', metricValue('difficultyFactor', row.difficultyFactor)], ['加权连击倍率', metricValue('comboFactor', row.comboFactor)],
      ['普通技能增益', metricValue('skillMultiplier', row.skillMultiplier)], ['换算音符数', number(row.convertedNoteCount)],
      ['谱面 / 音频时长', `${number(row.chartSeconds, 2)} / ${number(row.audioSeconds, 2)} 秒`], ['无技能普通基础分', number(row.baseScore)], ['普通技能净增分', number(row.skillScoreGain, 2)], ['判定数量', number(row.eventCount)]];
    if (row.sections) values.push(['激奏 / 普通倍率', metricValue('gekisouMultiplier', row.gekisouMultiplier)], ['名次奖励占比', metricValue('rankingBonusShare', row.rankingBonusShare)], ['样本范围', `${number(row.minimumScore)} – ${number(row.maximumScore)}`], ['样本数 / 标准误', `${row.sampleCount} / ${number(row.standardError, 2)}`]);
    const dl = node('dl'); for (const [label, value] of values) { const pair = node('div'); pair.append(node('dt', label), node('dd', value)); dl.append(pair); } root.append(dl);
    if (row.sections) {
      const stages = node('div', '', 'ranking-stages');
      for (const s of row.sections) { const stage = node('div'); stage.append(node('span', `${['','COMBO','LUCK','JUST'][s.missionType]} / 第 ${s.index} 段`), node('strong', `+${number(s.rankingPercent)}%`), node('small', `名次奖励 ${number(s.rankingBonus)} 分 · 含奖励占全曲 ${number(s.share * 100, 1)}%`)); stages.append(stage); }
      root.append(stages, node('p', '分段百分比是该段额外奖励率，不是全曲倍率。LUCK 使用固定样本；样本范围及标准误不包含模型误差。'));
    }
  }
}
if (!customElements.get('song-ranking')) customElements.define('song-ranking', SongRanking);
