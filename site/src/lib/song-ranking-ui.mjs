import {renderRankingTable} from './song-ranking-table-ui.mjs';
import {skillActivation} from './skill-activation-view.mjs';
import {setupQuickOptions,selectedOptionText} from './tool-quick-options.mjs';
import {selectedControlValues,restoreFilterControl} from './filter-controls.mjs';
import {SCORE_GRADES} from './song-grade-ranking.mjs';
import {RANKING_OPTIONS, GRADE_RANKING_METRICS, defaultRankingDirection, rankRefinedSongRows, scopeRankingRows, rankingRowState, validateRankingOptions, editionName, rankingSongLinks} from './song-ranking-options.mjs';
import {currentServerContext, gameServer} from './game-servers.mjs';
import {withSongSkillProfile, validateSongSkillProfile} from './song-skill-profile.mjs';
import {setupSongRankingReplay} from './song-ranking-replay-ui.mjs';
const say = (zh, en) => document.documentElement.lang.startsWith('en') ? en : zh;
const metricLabel = key => RANKING_OPTIONS[key]?.[document.documentElement.lang.startsWith('en') ? 1 : 0] ?? key;
const node = (tag, text = '', cls = '') => { const e = document.createElement(tag); e.textContent = text; e.className = cls; return e; };
const number = (n, digits = 0) => Number.isFinite(n) ? n.toLocaleString(document.documentElement.lang, {maximumFractionDigits:digits}) : '—';
const metricValue = (key, n) => {
  if (!Number.isFinite(n)) return '—';
  const type = RANKING_OPTIONS[key]?.[2];
  return type === 'percent' ? `${number(n * 100, 2)}%` : type === 'ratio' ? `${number(n, 4)}×` : type === 'seconds' ? `${number(n, 2)} s` : type === 'density' ? `${number(n, 2)} / s` : number(n, 2);
};
const specialMetrics = ['gekisouMultiplier', 'rankingBonusShare', 'rankingBonus', 'sampleCount', 'standardError'];
class SongRanking extends HTMLElement {
  connectedCallback() {
    if (this.events) return;
    this.events = new AbortController(); this.expanded = new Set(); this.page = 0;
    const listen = (el, type, fn) => el.addEventListener(type, fn, {signal:this.events.signal});
    listen(this.querySelector('[data-reload]'), 'click', () => location.reload());
    try {
      this.data = JSON.parse(this.querySelector('[data-ranking-data]').textContent);
      if (!Array.isArray(this.data.rankings.ordinary) || !Array.isArray(this.data.rankings.gekisou)) throw Error('Invalid ranking data');
      this.mode = 'ordinary'; this.metric = new URLSearchParams(location.search).get('view') === 'grade' ? 'requiredPower' : 'expectedScore';
      this.querySelector('[data-direction]').value = defaultRankingDirection(this.metric);
      this.defaultGradeEdition = this.querySelector('[data-grade-edition]').value;
      try { this.server = currentServerContext().serverId; } catch (error) { this.serverError = error.message; }
      for (const button of this.querySelectorAll('[data-mode]')) listen(button, 'click', () => {
        this.mode = button.dataset.mode; this.expanded.clear();
        if (this.mode === 'gekisou' && GRADE_RANKING_METRICS.includes(this.metric) || this.mode === 'ordinary' && specialMetrics.includes(this.metric)) this.setMetric('expectedScore');
        this.page = 0; this.render();
      });
      for (const input of this.querySelectorAll('[data-filter], [data-duration], [data-overhead], [data-direction], [data-grouping], [data-grade-target], [data-grade-edition], [data-grade-profile], [data-grade-score], [data-skill-percent], [data-skill-seconds]')) listen(input, 'input', () => { this.page = 0; this.render(); });
      const sortBy = (metric, header = false) => {
        if (header && metric === this.metric) this.querySelector('[data-direction]').value = this.querySelector('[data-direction]').value === 'asc' ? 'desc' : 'asc';
        else this.setMetric(metric);
        this.revealMetric = !header; this.page = 0; this.render();
      };
      for (const button of this.querySelectorAll('[data-board]')) listen(button,'click',()=>sortBy(button.dataset.board));
      listen(this.querySelector('[data-ranking-head]'),'click',event=>{const button=event.target.closest('[data-sort]');if(button)sortBy(button.dataset.sort,true);});
      listen(this.querySelector('[data-metric]'),'change',event=>sortBy(event.target.value));
      const closePanel = panel => { panel.open=false; panel.querySelector('summary').focus(); };
      for (const panel of this.querySelectorAll('[data-toolbar-panel]')) {
        listen(panel,'toggle',()=>{if(panel.open)for(const other of this.querySelectorAll('[data-toolbar-panel]'))if(other!==panel)other.open=false;});
        for(const close of panel.querySelectorAll('[data-close-panel]'))listen(close,'click',()=>closePanel(panel));
      }
      listen(this,'keydown',event=>{if(event.key==='Escape'){const panel=this.querySelector('[data-toolbar-panel][open],.ranking-provenance[open]');if(panel){closePanel(panel);event.preventDefault();}}});
      listen(document,'pointerdown',event=>{for(const panel of this.querySelectorAll('[data-toolbar-panel][open],.ranking-provenance[open]'))if(!panel.contains(event.target))panel.open=false;});
      listen(this.querySelector('[data-copy-skills]'), 'click', () => {
        const slots = [...this.querySelectorAll('[data-skill-slot]')];
        for (const slot of slots.slice(1)) for (const key of ['percent','seconds']) slot.querySelector(`[data-skill-${key}]`).value = slots[0].querySelector(`[data-skill-${key}]`).value;
        this.page = 0; this.render();
      });
      listen(this.querySelector('[data-prev]'), 'click', () => { this.page--; this.render(); });
      listen(this.querySelector('[data-next]'), 'click', () => { this.page++; this.render(); });
      const clearFilters = () => {
        for (const input of this.querySelectorAll('[data-filter]')) restoreFilterControl(input, input.tagName === 'SELECT' ? 'all' : '');
        this.page = 0; this.render();
      };
      for (const button of this.querySelectorAll('[data-reset], [data-empty-reset]')) listen(button, 'click', clearFilters);
      listen(this.querySelector('[data-show-all]'), 'click', () => { this.querySelector('[data-replay-method]').value = 'linear'; this.page = 0; this.render(); });
      listen(this.querySelector('[data-reset-all]'), 'click', () => {
        this.replays.reset(); this.mode = 'ordinary'; this.setMetric('expectedScore');
        for (const field of this.querySelectorAll('[data-filter]')) restoreFilterControl(field, field.tagName === 'SELECT' ? 'all' : '');
        this.querySelector('[data-grade-profile]').value = 'benchmark'; this.querySelector('[data-grade-score]').value = '';
        this.querySelector('[data-grade-target]').value = '5'; this.querySelector('[data-grade-edition]').value = this.defaultGradeEdition;
        this.querySelector('[data-overhead]').value = '0'; this.querySelector('[data-duration]').value = 'chart';
        this.querySelector('[data-grouping]').value = 'charts'; this.querySelector('[data-replay-fps]').value = '60';
        for (const field of this.querySelectorAll('[data-skill-percent]')) field.value = '100';
        for (const field of this.querySelectorAll('[data-skill-seconds]')) field.value = '5';
        this.page = 0; this.render(); this.querySelector('[data-metric]').focus();
      });
      this.shortcuts = setupQuickOptions(this);
      this.replays = setupSongRankingReplay(this, () => { this.page = 0; this.render(); });
      this.querySelector('[data-startup]').hidden = true;
      this.render();
    } catch (error) {
      this.showError(say('排行榜数据未能初始化，请重新加载页面。', 'Ranking data could not initialize. Reload the page.'));
      this.querySelector('[data-startup]').hidden = true;
      this.querySelector('[data-reload]').hidden = false;
      this.querySelector('[data-reset-all]').hidden = true;
    }
  }
  disconnectedCallback() { this.shortcuts?.destroy(); this.replays?.destroy(); this.events?.abort(); this.events = null; }
  setMetric(metric) {
    this.metric = metric;
    if (GRADE_RANKING_METRICS.includes(metric)) this.mode = 'ordinary';
    this.querySelector('[data-direction]').value = defaultRankingDirection(metric);
    // A value interval belongs to its metric; keep level/time/other filters.
    for (const key of ['minValue','maxValue']) this.querySelector(`[data-filter="${key}"]`).value = '';
  }
  showError(message) {
    this.replays?.invalidate();
    this.querySelector('[data-error]').hidden = false; this.querySelector('[data-error-message]').textContent = message;
    for (const error of this.querySelectorAll('[data-panel-error]')) { error.hidden=false; error.textContent=message; }
    this.querySelector('[data-results]').hidden = true; this.querySelector('[data-empty]').hidden = true;
    this.querySelector('[data-count]').textContent = '—';
    this.querySelector('[data-context]').textContent = say('请修正条件后继续比较', 'Correct the inputs to continue');
    this.querySelector('[data-result-status]').textContent = ''; this.querySelector('[data-range]').textContent = '—';
    this.querySelector('[data-page]').textContent = '—';
    this.querySelector('[data-prev]').disabled = this.querySelector('[data-next]').disabled = true;
  }
  render() {
    try { this.renderResults(); }
    catch (error) { this.showError(say('结果未能更新。请恢复默认条件后重试。', 'Results could not update. Restore the defaults and try again.')); }
  }
  renderResults() {
    const q = selector => this.querySelector(selector), en = document.documentElement.lang.startsWith('en');
    this.shortcuts?.sync();
    const gradeView = GRADE_RANKING_METRICS.includes(this.metric);
    const profile = this.mode === 'gekisou' ? 'benchmark' : q('[data-grade-profile]').value, custom = profile === 'custom';
    q('[data-profile-controls]').hidden = this.mode === 'gekisou'; q('[data-custom-skills]').hidden = !custom; q('[data-grade-controls]').hidden = !gradeView;
    q('[data-value-range]').hidden = RANKING_OPTIONS[this.metric][2] === 'text';
    for (const button of this.querySelectorAll('[data-mode]')) button.setAttribute('aria-pressed', String(button.dataset.mode === this.mode));
    for (const button of this.querySelectorAll('[data-board]')) button.setAttribute('aria-pressed', String(button.dataset.board === this.metric));
    for (const option of q('[data-metric]').options) option.disabled = this.mode === 'ordinary' && specialMetrics.includes(option.value);
    q('[data-metric]').value = this.metric;
    const filters = Object.fromEntries([...this.querySelectorAll('[data-filter]')].map(e => [e.dataset.filter, e.multiple ? selectedControlValues(e) : e.value]));
    const skills = [...this.querySelectorAll('[data-skill-slot]')].map(slot => ({percent:slot.querySelector('[data-skill-percent]').value === '' ? NaN : Number(slot.querySelector('[data-skill-percent]').value), seconds:Number(slot.querySelector('[data-skill-seconds]').value)}));
    const rawScore = q('[data-grade-score]').value, score = rawScore === '' ? null : Number(rawScore);
    const activeInputs = [...this.querySelectorAll('[data-filter][type=number], [data-overhead]'), ...(custom ? this.querySelectorAll('[data-skill-percent]') : []), ...(gradeView ? [q('[data-grade-score]')] : [])];
    for (const field of activeInputs) field.setAttribute('aria-invalid', String(!field.validity.valid));
    const invalid = activeInputs.find(field => !field.validity.valid);
    let options;
    try {
      if (invalid) throw Error(say(`${invalid.getAttribute('aria-label') ?? '数值'}超出允许范围，请填写有效数值。`, `${invalid.getAttribute('aria-label') ?? 'Value'} is outside the allowed range. Enter a valid number.`));
      if (custom) validateSongSkillProfile(skills);
      if (gradeView && score !== null && (!Number.isSafeInteger(score) || score < 0)) throw Error(say('分数需为非负安全整数。', 'Score must be a non-negative safe integer.'));
      options = validateRankingOptions({...filters, metric:this.metric, direction:q('[data-direction]').value, grouping:q('[data-grouping]').value,
        locale:document.documentElement.lang, durationBasis:q('[data-duration]').value, overhead:q('[data-overhead]').value, gradeEdition:q('[data-grade-edition]').value,
        targetRank:Number(q('[data-grade-target]').value), profile, score, skills}, en);
    } catch (error) { this.showError(error.message); return; }
    this.options = options;
    q('[data-error]').hidden = true; q('[data-results]').hidden = false;
    for (const error of this.querySelectorAll('[data-panel-error]')) error.hidden=true;
    const tags = q('[data-ranking-filter-tags]'); tags.replaceChildren();
    for (const field of this.querySelectorAll('[data-filter]')) {
      if (field.multiple ? !selectedControlValues(field).length : field.value === '' || field.value === 'all') continue;
      const label = field.tagName === 'SELECT' ? selectedOptionText(field) : `${field.getAttribute('aria-label')} ${field.value}`;
      const button = node('button', `${label} ×`); button.type = 'button'; button.setAttribute('aria-label', say(`取消筛选：${label}`, `Remove filter: ${label}`));
      button.addEventListener('click', () => { restoreFilterControl(field, field.tagName === 'SELECT' ? 'all' : ''); this.page = 0; this.render(); (tags.querySelector('button') ?? q('.ranking-clear')).focus(); }); tags.append(button);
    }
    tags.hidden = !tags.children.length;
    q('[data-filter-count]').textContent = String(tags.children.length); q('[data-filter-count]').hidden = !tags.children.length;
    const profileLabel = this.mode === 'gekisou' ? say('激奏固定基准', 'Fixed Gekisou benchmark') : custom ? say('手填五技能', 'Five entered skills') : profile === 'none' ? say('无加分技能', 'No score skills') : say('基准五技能', 'Five benchmark skills');
    q('[data-calculation-profile]').textContent = profileLabel;
    q('[data-skill-summary]').textContent = custom ? say('先按技能窗口快速估算；逐谱精算遍历 120 种发动顺序并逐音符计算。', 'Skill windows provide quick estimates; replay computes every note across all 120 skill orders.') : profile === 'none' ? say('无技能基础分已逐音符计算。', 'No-skill baseline scores were calculated note by note.') : say('五次 +100% / 5 秒技能，60 FPS 基准已预先逐音符计算。', 'Five +100% / 5-second skills; the 60 FPS benchmark was computed note by note.');
    const activeSkills = custom ? skills : Array.from({length:5}, () => ({percent:profile === 'none' ? 0 : 100, seconds:profile === 'none' ? 0 : 5}));
    let rows = scopeRankingRows(this.data.rankings[this.mode], filters.edition).map(row => ({...row, p10Score:row.p10Score ?? (row.minimumScore === row.maximumScore ? row.minimumScore : null)}));
    if (profile !== 'benchmark') rows = rows.map(row => withSongSkillProfile(row, activeSkills));
    const quickRanked = rankRefinedSongRows(rows, options);
    const replayView = this.replays.sync({skills:activeSkills, rows:quickRanked, mode:this.mode, profile});
    if (replayView) rows = this.replays.rows(rows);
    this.replayView = replayView;
    const ranked = rankRefinedSongRows(rows, options);
    const valid = ranked.filter(row => row.rank !== null);
    const scoreLabel = replayView ? say('逐谱平均分','Replay mean') : custom ? say('快速平均参考分','Quick estimated mean') : profile === 'none' ? say('无技能参考分','No-skill score') : this.mode === 'gekisou' ? say('样本平均分','Sample mean') : say('基准平均分','Benchmark mean');
    const size = 25, pages = Math.max(1, Math.ceil(ranked.length / size));
    this.page = Math.max(0, Math.min(this.page, pages - 1));
    q('[data-count]').textContent = say(`${ranked.length} 张谱面`, `${ranked.length} charts`);
    q('[data-context]').textContent = [this.mode === 'ordinary' ? say('普通','Ordinary') : say('激奏样本 · 非实战保底','Gekisou samples · not guaranteed'), profileLabel,
      `${metricLabel(this.metric)} ${options.direction === 'asc' ? '↑' : '↓'}`,
      gradeView ? `${SCORE_GRADES[options.targetRank-2]} / ${editionName(options.gradeEdition,en)}` : '',
      replayView ? say('仅已完成精算内排名','Completed replays only') : ''].filter(Boolean).join(' · ');
    const calculated = ranked.filter(row => rankingRowState(row) === 'calculated').length, pending = ranked.filter(row => row.pending).length;
    q('[data-result-status]').textContent = say(`可排名 ${valid.length} · 有分 ${calculated} · 待算 ${pending} · 缺条件 ${ranked.length-calculated-pending}`, `${valid.length} ranked · ${calculated} scored · ${pending} pending · ${ranked.length-calculated-pending} unavailable`);
    const releases = Object.entries(this.data.rankings.releases ?? {}).map(([edition, release]) => `${editionName(edition,en)} ${release}`).join(' / ');
    q('[data-identity]').textContent = [say('结果范围：', 'Result scope: ') + (filters.edition === 'all' ? say('全部版本', 'All editions') : editionName(filters.edition,en)),
      this.server ? say('当前区服：', 'Selected server: ') + gameServer(this.server)?.[en ? 'englishLabel' : 'label'] : say('当前区服未选择', 'No server selected'), releases,
      gradeView ? say('达档分数线：', 'Grade thresholds: ') + editionName(options.gradeEdition,en) : '', this.serverError ?? ''].filter(Boolean).join(' · ');
    q('[data-metric-help]').textContent = this.mode === 'gekisou' && ['minimumScore','maximumScore','p10Score','scoreSpread','p10Efficiency'].includes(this.metric)
      ? say('激奏数值来自固定 LUCK 样本，最低／最高为样本范围，不是理论极值或实战保底。', 'Gekisou uses fixed LUCK samples. Minimum and maximum are sample extrema, not theoretical bounds or live guarantees.')
      : ['minimumScore','maximumScore','p10Score','scoreSpread','p10Efficiency'].includes(this.metric)
        ? say('普通演出参考值按当前技能条件比较；自定义技能遍历 120 种等可能顺序。P10 为由低到高第 12 项，不是实战保底。基准相同技能的范围可能相等。', 'Ordinary reference values follow the chosen skills; custom skills compare 120 equally likely orders. P10 is the 12th lowest, not a live guarantee. Identical benchmark skills can have equal extrema.')
        : ['averageDensity','peakDensity','eventCount','bpmMax','level'].includes(this.metric)
          ? say('结构指标描述计分判定（包含滑条自动计数），不等于游玩难度；无分数也可按已有结构数值比较。', 'Structure metrics describe scoring events, including generated slide ticks. They do not measure playing difficulty; known structure values can rank without scores.')
          : gradeView ? say('按未舍入的参考综合力排名；展示向上取到千位，数值不是实战保底。分数线版本未验证时不反推综合力。', 'Power ranks use unrounded estimates; displayed values round up to 1,000 and are not guarantees. Unverified edition scores cannot supply power estimates.')
            : say(`效率分母：${options.durationBasis === 'chart' ? '谱面' : '音频'}时长 + ${number(options.overhead,2)} 秒；缺少所选时长时不计算效率。`, `Efficiency denominator: ${options.durationBasis} duration + ${number(options.overhead,2)} seconds. Missing duration has no efficiency.`);
    q('[data-value-unit]').textContent = RANKING_OPTIONS[this.metric][2] === 'percent' ? say('（比例原值，0.2 = 20%）', '(raw ratio: 0.2 = 20%)') : `(${metricLabel(this.metric)})`;
    q('[data-page]').textContent = `${this.page+1} / ${pages}`;
    q('[data-range]').textContent = ranked.length ? say(`第 ${this.page*size+1}–${Math.min(ranked.length,(this.page+1)*size)} 项，共 ${ranked.length} 项`, `${this.page*size+1}–${Math.min(ranked.length,(this.page+1)*size)} of ${ranked.length}`) : say('没有匹配结果', 'No matching results');
    q('[data-prev]').disabled = this.page === 0; q('[data-next]').disabled = this.page === pages-1;
    q('[data-empty]').hidden = ranked.length > 0;
    q('[data-empty] strong').textContent = replayView ? say('当前筛选没有完成精算的谱面', 'No completed replay matches these filters') : say('没有符合这些条件的谱面', 'No charts match these filters');
    q('[data-empty] p').textContent = replayView ? say('开始逐谱精算，或切回全部筛选结果。若刚按每首歌选谱或数值范围比较，可放宽条件查看其他已算结果。', 'Run chart replay or return to all filtered results. Relax grouping or value filters to see other completed results.') : say('清空筛选，或放宽版本、计算状态、难度与数值区间。', 'Clear filters or relax edition, calculation state, difficulty and numeric ranges.');
    q('[data-show-all]').hidden = !replayView;
    renderRankingTable(this,{rows:ranked,page:this.page,size,mode:this.mode,metric:this.metric,direction:options.direction,locale:document.documentElement.lang,
      artwork:this.data.artwork,expanded:this.expanded,detail:(root,row)=>this.detail(root,row),reveal:this.revealMetric,scoreLabel,targetRank:options.targetRank,durationBasis:options.durationBasis});
    this.revealMetric=false;
    this.shortcuts?.sync();
  }
  rowIdentity(row) {
    const en = document.documentElement.lang.startsWith('en');
    return [row.applicableEditions?.length ? say('分数适用：','Scores valid for: ') + row.applicableEditions.map(edition => editionName(edition,en)).join(' / ') : '',
      row.pendingEditions?.length ? say('待计算：','Pending: ') + row.pendingEditions.map(edition => editionName(edition,en)).join(' / ') : ''].filter(Boolean).join(' · ');
  }
  detail(root, row) {
    this.songLinks(root,row);
    if(GRADE_RANKING_METRICS.includes(this.metric)){
      root.append(node('p',`${row.title} · ${row.difficulty.toUpperCase()} / 分档明细`,'ranking-detail-title'));
      const dl=node('dl');for(const r of row.thresholds??[]){const pair=node('div');pair.append(node('dt',`${SCORE_GRADES[r.rank-2]} 档`),node('dd',`${number(r.score)} 分`));dl.append(pair);}root.append(dl);
      if(row.targetGap!=null)root.append(node('p',row.targetGap?`输入分数距离目标还差 ${number(row.targetGap)} 分`:'输入分数已达到目标档位'));
      if(row.requiredPower==null)root.append(node('p','缺少已验证的基准得分、技能窗口或完整分档线，暂不估算综合力。'));
      const skillDl=node('dl');
      for(const [label,value] of [['基准综合力',number(row.benchmark?.power)],['无技能基准分',number(row.baseScore)],['当前技能基准分',number(row.benchmarkScore)],['全曲技能增分',row.benchmarkScore==null?'—':`${number(row.benchmarkScore-row.baseScore)}（+${number((row.benchmarkScore/row.baseScore-1)*100,2)}%）`]]){const pair=node('div');pair.append(node('dt',label),node('dd',value));skillDl.append(pair);}
      root.append(node('p','当前技能条件如何影响本曲','ranking-detail-title'),skillDl);
      if(row.skillReference)root.append(node('p',`五次发动位置：${row.skillReference.startsSeconds.map(t=>number(t,2)+' 秒').join(' / ')}。按理想发动时机估算。`));
      this.distributionDetail(root,row);
    this.activationDetail(root,row);
      return;
    }
    root.append(node('p', `${row.title} · ${row.difficulty.toUpperCase()} / 得分拆解`, 'ranking-detail-title'));
    const values = [['难度倍率', metricValue('difficultyFactor', row.difficultyFactor)], ['加权连击倍率', metricValue('comboFactor', row.comboFactor)],
      ['普通技能增益', metricValue('skillMultiplier', row.skillMultiplier)], ['换算音符数', number(row.convertedNoteCount)],
      ['谱面 / 音频时长', `${number(row.chartSeconds, 2)} / ${number(row.audioSeconds, 2)} 秒`], ['无技能普通基础分', number(row.baseScore)], ['普通技能净增分', number(row.skillScoreGain, 2)], ['判定数量', number(row.eventCount)]];
    if (row.sections) values.push(['激奏 / 普通倍率', metricValue('gekisouMultiplier', row.gekisouMultiplier)], ['名次奖励占比', metricValue('rankingBonusShare', row.rankingBonusShare)], ['样本范围', `${number(row.minimumScore)} – ${number(row.maximumScore)}`], ['样本数 / 标准误', `${row.sampleCount} / ${number(row.standardError, 2)}`]);
    const dl = node('dl'); for (const [label, value] of values) { const pair = node('div'); pair.append(node('dt', label), node('dd', value)); dl.append(pair); } root.append(dl);
    if(row.meta){
      const m=row.meta,meta=node('dl','','ranking-meta');
      for(const [label,value] of [['BPM',m.bpmMin===m.bpmMax?number(m.bpmMin,2):`${number(m.bpmMin,2)}–${number(m.bpmMax,2)}`],['平均判定密度',`${number(m.averageDensity,2)} 次 / 秒`],['最密一秒',`${number(m.peakDensity)} 次（${number(m.peakStart)}–${number(m.peakStart+1)} 秒）`],['同毫秒内判定',`${number(m.simultaneousEvents)} 次`],['滑条自动计数',`${number(m.generatedEvents)} 次`]]){const pair=node('div');pair.append(node('dt',label),node('dd',value));meta.append(pair);}
      root.append(node('p','谱面结构','ranking-detail-title'),meta,node('p','密度按计分判定统计，包含滑条自动计数；同毫秒判定按正式计分时间分组。这些数值描述谱面结构，不等于手指数或游玩难度。'));
      root.append(node('p',`五次技能发动：${m.startsSeconds.map(time=>number(time,3)+' 秒').join(' / ')}。`));
    }
    this.distributionDetail(root,row);
    this.activationDetail(root,row);
    if (row.sections) {
      const stages = node('div', '', 'ranking-stages');
      for (const s of row.sections) { const stage = node('div'); stage.append(node('span', `${['','COMBO','LUCK','JUST'][s.missionType]} / 第 ${s.index} 段`), node('strong', `+${number(s.rankingPercent)}%`), node('small', `名次奖励 ${number(s.rankingBonus)} 分 · 含奖励占全曲 ${number(s.share * 100, 1)}%`)); stages.append(stage); }
      root.append(stages, node('p', '分段百分比是该段额外奖励率，不是全曲倍率。LUCK 使用固定样本；样本范围及标准误不包含模型误差。'));
    }
  }
  activationDetail(root,row){
    if(row.replaySource){
      const profile=this.querySelector('[data-grade-profile]').value;
      const skills=this.mode==='ordinary'&&profile==='custom'?[...this.querySelectorAll('[data-skill-slot]')].map(slot=>({percent:Number(slot.querySelector('[data-skill-percent]').value),seconds:Number(slot.querySelector('[data-skill-seconds]').value)})):
        Array.from({length:5},()=>({percent:profile==='none'&&this.mode==='ordinary'?0:row.benchmark.skillPercent,seconds:row.benchmark.skillSeconds}));
      root.append(skillActivation(this,null,{mode:this.mode,ranking:{replaySource:row.replaySource,sourceId:row.sourceId,trackId:row.trackId,difficulty:row.difficulty,benchmark:row.benchmark,skills,frameRate:Number(this.querySelector('[data-replay-fps]').value)}}));
    }
  }
  distributionDetail(root,row){
    if(row.skillProfile&&!row.scoreDistribution){root.append(node('p','此谱面缺少五技能窗口数据，暂不能计算当前条件。'));return;}
    if(!row.scoreDistribution)return;
    const d=row.scoreDistribution;
    root.append(node('p',say(`${row.skillReplay?'逐谱精算':'技能顺序参考'} · P10 ${number(d.p10)} 分 · 范围 ${number(d.minimum)}–${number(d.maximum)} 分 · ${d.count} 种顺序`, `${row.skillReplay?'Chart replay':'Skill-order reference'} · P10 ${number(d.p10)} · Range ${number(d.minimum)}–${number(d.maximum)} · ${d.count} orders`)));
    if(row.skillReplay){
      const replay=row.skillReplay;
      root.append(node('p',`最高顺序：${replay.bestOrder.map(slot=>slot+1).join(' → ')}；最低顺序：${replay.worstOrder.map(slot=>slot+1).join(' → ')}（数字对应上方技能编号）。`));
      if(Number.isFinite(row.linearScore))root.append(node('p',say(`${row.comparisonLabel ?? '原列表'} ${number(row.linearScore,2)} 分；逐谱精算 ${number(d.mean,2)} 分，相差 ${number(d.mean-row.linearScore,2)} 分。`, `${row.comparisonLabel ?? 'Original list'}: ${number(row.linearScore,2)}; chart replay: ${number(d.mean,2)}; difference: ${number(d.mean-row.linearScore,2)} points.`)));
      root.append(node('p',`${replay.frameRate} FPS 理想帧时钟 · AP · 满生命 · 综合力 ${number(replay.power)}。已计算倍率浮点历史、逐音符取整和记分桶回滚；真实卡牌条件、活动与激奏加成需使用队伍计算器。精算是模型内的完整计算，范围不是实战保底。`));
    }
    if(row.positionContributions){
      const dl=node('dl');for(const [i,gain] of row.positionContributions.entries()){
        const pair=node('div');pair.append(node('dt',`第 ${i+1} 次发动 · ${number(row.skillReference?.startsSeconds[i],2)} 秒`),node('dd',`平均 +${number(gain)} 分`));dl.append(pair);
      }root.append(dl);
      root.append(node('p','贡献按五个技能轮流落在各发动位求平均；线性参考不含真实卡牌条件与逐音符重新取整。'));
    }
  }
  songLinks(root,row) {
    const edition = GRADE_RANKING_METRICS.includes(this.metric) ? this.options.gradeEdition : this.options.edition === 'all' ? row.sourceEdition : this.options.edition;
    const urls = rankingSongLinks(row, {edition, locale:document.documentElement.lang, server:this.server, mode:this.mode});
    const links = node('nav','','ranking-song-links'); links.setAttribute('aria-label',say(`${row.title} 相关工具`, `Tools for ${row.title}`));
    const actions = [[urls.calculator,say('用我的队伍计算','Calculate with my team')],[urls.chart,say('查看这张谱面','View this chart')]];
    if (this.metric === 'requiredPower') actions.push([urls.grade,say('用我的队伍估分','Estimate my team score')],[urls.event,say('带歌曲到活动收益','Compare event rewards')]);
    for (const [href,label] of actions) { const link=node('a',label); link.href=href; links.append(link); }
    root.append(links,node('p',say('跳转保留歌曲、难度和兼容区服；手填五技能不替代目标工具中的账号编成与养成。','Links preserve the song, difficulty and compatible server. Entered skills do not replace the destination tool’s account team or growth settings.')));
    root.append(node('p',this.rowIdentity(row)));
    const versions = Object.entries(row.editionChartReferences ?? row.gradeReferences ?? {}).map(([edition,ref]) => `${editionName(edition,document.documentElement.lang.startsWith('en'))}: ${ref.sourceReleaseId}`);
    root.append(node('p',versions.join(' / '),'ranking-source-release'));
  }
}
if (!customElements.get('song-ranking')) customElements.define('song-ranking', SongRanking);
