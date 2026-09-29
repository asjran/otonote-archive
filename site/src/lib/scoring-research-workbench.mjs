import {setupCalculatorSongPicker} from './calculator-song-picker.mjs';
import { readGekisouOpponentInputs, writeGekisouOpponentInputs } from './gekisou-opponent-inputs.mjs';
import { readScoringScenarioSearch } from './scoring-rules/scenario-search.mjs';
import { toolRoute } from "./tool-route.mjs";
import {
  createTeamDraft,
  deriveTeamDraftSummary,
  parseTeamDraftSearch,
  serializeTeamDraftSearch
} from "./team-draft.mjs";
import {
  createScoringInputSnapshot,
  evaluateScoringResearch
} from "./scoring-engine.mjs";
import { resolveTgwCardRankBonus } from "./scoring-rules/tgw-card.mjs";
import { createFormationCalculator } from "./scoring-rules/formation-power.mjs";

class ScoringResearchWorkbench extends HTMLElement {
  async connectedCallback() {
    const dataNode = this.querySelector("[data-scoring-research-data]");
    if (!(dataNode instanceof HTMLScriptElement)) return;
    this.data = JSON.parse(dataNode.textContent || "{}");
    this.labels = this.data.labels;
    try {
      const {mode,scenario}=readScoringScenarioSearch(window.location.search);
      this.querySelector('[data-scoring-mode]').value=mode;
      if(scenario) {
        writeGekisouOpponentInputs(this,scenario.opponents);
        for(const [field,selector] of [['timingOffsetMs','offset'],['batches','batches'],['seed','seed'],['frameRate','fps']]) this.querySelector(`[data-gekisou-${selector}]`).value=String(scenario[field]);
        [...this.querySelectorAll('[data-gekisou-rank]')].forEach((node,i)=>node.value=String(scenario.ranks[i]));
      }
    } catch(error) { this.scenarioError=error.message; }
    this.memberById = new Map(this.data.memberCards.map((card) => [card.id, card]));
    this.supportById = new Map(this.data.supportCards.map((card) => [card.id, card]));
    this.trackById = new Map(this.data.tracks.map((track) => [track.id, track]));
    const known = {
      memberCardIds: new Set(this.memberById.keys()),
      supportCardIds: new Set(this.supportById.keys()),
      musicTrackIds: new Set(this.trackById.keys())
    };
    if (this.data.vipRanks?.length) {
      known.tgwCardRanks = new Set(this.data.vipRanks.map((entry) => entry.rank));
    }
    const parsed = parseTeamDraftSearch(window.location.search, known);
    this.draft = createTeamDraft(parsed.draft);
    this.inputIssues=parsed.issues;this.inputRequest=0;this.scoreRequest=0;
    this.querySelector('[data-calculator-song]').value=this.draft.selectedSongId??'';
    this.querySelector('[data-calculator-difficulty]').value=this.draft.selectedDifficulty??'';
    for(const [selector,field] of [['[data-calculator-song]','selectedSongId'],['[data-calculator-difficulty]','selectedDifficulty']]) {
      this.querySelector(selector).addEventListener('change',event=>{this.draft[field]=event.target.value||null;this.refreshInput();});
    }
    this.songPicker=setupCalculatorSongPicker(this,{getSelection:()=>this.draft,onSelect:selection=>{
      Object.assign(this.draft,selection);
      this.querySelector('[data-calculator-song]').value=selection.selectedSongId;
      this.querySelector('[data-calculator-difficulty]').value=selection.selectedDifficulty;
      this.refreshInput();
    }});
    const recalculate=()=>{this.scenarioError=null;if(this.loadedSnapshot)this.renderSongScore(this.loadedChart,this.loadedSnapshot,this.inputIssues);};
    this.querySelector('[data-scoring-mode]').addEventListener('change',recalculate);
    this.querySelector('[data-gekisou-scenario]').addEventListener('change',recalculate);
    await this.refreshInput();
  }

  async refreshInput() {
    this.scoreRequest++;this.rejectScore?.(new Error('Cancelled'));this.scoreWorker?.terminate();
    this.loadedSnapshot=null;this.loadedChart=null;
    const summary = deriveTeamDraftSummary(this.draft, {
      memberCards: this.data.memberCards,
      supportCards: this.data.supportCards,
      projections: this.data.projections
    });
    const chartSummary = this.data.charts.find((chart) =>
      chart.trackId === this.draft.selectedSongId
      && chart.difficulty === this.draft.selectedDifficulty
    ) ?? null;
    let chart = chartSummary;
    const request=++this.inputRequest;
    this.querySelector('[data-song-score]').textContent='读取谱面…';
    if (chartSummary?.analysisDataUrl) {
      try {
        const response = await fetch(chartSummary.analysisDataUrl);
        if (response.ok) chart = { ...chartSummary, ...(await response.json()) };
      } catch {
        chart = chartSummary;
      }
    }
    if(request!==this.inputRequest)return;
    let tgwCardBonus;
    if (this.draft.modifiers.tgwCardRank && this.data.vipRanks?.length) {
      try {
        tgwCardBonus = resolveTgwCardRankBonus(
          this.data.vipRanks, this.draft.modifiers.tgwCardRank
        );
      } catch {
        // The draft validation issues are rendered below; keep the page usable.
      }
    }
    let formationPower;
    try {
      formationPower = createFormationCalculator(this.data.formalRules).calculate(this.draft,
        { sourceReleaseId: this.data.sourceReleaseId });
    } catch (error) {
      formationPower = { status: "invalid_input", error: error.message };
    }
    const snapshot = createScoringInputSnapshot({
      sourceReleaseId: this.data.sourceReleaseId,
      draft: this.draft,
      chart,
      teamSummary: summary,
      tgwCardBonus,
      formationPower
    });
    const result = evaluateScoringResearch(snapshot, this.data.evidence);
    this.render(snapshot, result, summary, this.inputIssues);
    this.loadedChart=chart;this.loadedSnapshot=snapshot;
    this.renderSongScore(chart, snapshot, this.inputIssues);
  }

  disconnectedCallback(){this.inputRequest++;this.scoreRequest++;this.rejectScore?.(new Error('Cancelled'));this.scoreWorker?.terminate();}

  calculateInWorker(payload) {
    return new Promise((resolve,reject)=>{
      const worker=new Worker(new URL('./song-calculation-worker.mjs',import.meta.url),{type:'module'});
      this.scoreWorker=worker;this.rejectScore=reject;
      worker.onmessage=({data})=>{worker.terminate();if(this.scoreWorker===worker){this.scoreWorker=null;this.rejectScore=null;}data.error?reject(new Error(data.error)):resolve(data.result);};
      worker.onerror=()=>{worker.terminate();reject(new Error('后台计算失败，请重新选择模式再试。'));};
      worker.postMessage(payload);
    });
  }

  async renderSongScore(chart, snapshot, issues) {
    const request=++this.scoreRequest;
    this.rejectScore?.(new Error('Cancelled'));this.scoreWorker?.terminate();
    const output = this.querySelector("[data-song-score]");
    const details = this.querySelector("[data-song-score-details]");
    const trace = this.querySelector("[data-scoring-trace]");
    trace?.replaceChildren();
    const labels = this.labels.song;
    const format = (n) => n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    const interpolate = (template, values) => template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));
    this.querySelector('[data-gekisou-scenario]').hidden = this.querySelector('[data-scoring-mode]')?.value !== 'gekisou';
    try {
      if (this.scenarioError) throw new Error(this.scenarioError);
      if (issues.length) throw new Error(labels.invalidShare);
      if (!chart?.notes?.length) throw new Error('请选择歌曲和难度。');
      if (this.draft.slots.some(s=>!s.memberCardId||!s.supportCardId)) throw new Error('还没有完整队伍。先自动配队，或在编队页选满 5 张成员和 5 张留影。');
      output.textContent='计算中…';details.textContent='正在后台逐音符计算，你可以继续调整条件。';
      if (this.querySelector('[data-scoring-mode]')?.value === 'gekisou') {
        const scenario = { timingOffsetMs:Number(this.querySelector('[data-gekisou-offset]').value),
          frameRate:Number(this.querySelector('[data-gekisou-fps]').value),opponents:readGekisouOpponentInputs(this),
          ranks:[...this.querySelectorAll('[data-gekisou-rank]')].map(n=>Number(n.value)),
          batches:Number(this.querySelector('[data-gekisou-batches]').value),seed:Number(this.querySelector('[data-gekisou-seed]').value) };
        const result = await this.calculateInWorker({mode:'gekisou',rules:this.data.formalRules,chart:{...chart,sourceReleaseId:this.data.sourceReleaseId},scenario,draft:this.draft});
        if(request!==this.scoreRequest)return;
        output.textContent = format(result.expectedScore);
        details.textContent = interpolate(labels.gekisouEstimate, {power:format(result.power),samples:result.sampleCount,min:format(result.minimumScore),max:format(result.maximumScore),error:format(result.standardError),share:format(result.rankingBonusShare*100)});
        const names = {1:'COMBO',2:'LUCK',3:'JUST'};
        for (const section of result.sections) {
          const item = document.createElement('li');
          item.textContent = interpolate(labels.gekisouSectionScore, {index:section.index,mission:names[section.missionType],notes:format(section.noteScore),rank:format(section.rank),bonus:format(section.rankingBonus),share:format(section.share*100),just:format(section.rawJust),combo:format(section.combo),luck:format(section.luckPoints)});
          trace?.append(item);
        }
        for (const warning of result.warnings) { const item=document.createElement('li');item.textContent=warning;trace?.append(item); }
        this.querySelector('[data-scoring-input-hash]').textContent = result.inputHash;
        this.querySelector('[data-scoring-snapshot-json]').textContent = JSON.stringify({input:snapshot,result},null,2);
        return;
      }
      const result = await this.calculateInWorker({mode:'ordinary',rules:this.data.formalRules,chart:{...chart,sourceReleaseId:this.data.sourceReleaseId},draft:this.draft});
      if(request!==this.scoreRequest)return;
      output.textContent = format(result.expectedScore);
      const comboSummary = this.querySelector("[data-scoring-event-count]");
      if (comboSummary) comboSummary.textContent = String(result.chart.eventCount);
      details.textContent = interpolate(labels.breakdown, { base: format(result.baseScore), gain: format(result.skillScoreGain), min: format(result.minimumScore), max: format(result.maximumScore) });
      const messages = [
        labels.scenario,
        interpolate(labels.topology, { events: result.chart.eventCount, master: result.chart.masterFullCombo }),
        interpolate(labels.factors, { power: format(result.power), factor: result.chart.difficultyFactor.toFixed(3), notes: result.chart.convertedNoteCount }),
        ...result.skills.map((skill) => interpolate(labels.skill, { slot: skill.slotIndex + 1, member: skill.memberLevel, support: skill.supportLevels.join(" / "), duration: skill.extensionMs })),
        ...result.warnings
      ];
      for (const message of messages) {
        const item = document.createElement("li"); item.textContent = message; trace?.append(item);
      }
      this.querySelector("[data-scoring-input-hash]").textContent = result.inputHash;
      this.querySelector("[data-scoring-snapshot-json]").textContent = JSON.stringify({ input: snapshot, result }, null, 2);
    } catch (error) {
      if(request!==this.scoreRequest)return;
      output.textContent = labels.unavailable;
      details.textContent = error.message;
      const item = document.createElement("li"); item.textContent = error.message; trace?.append(item);
    }
  }

  render(snapshot, result, summary, issues) {
    const status = this.querySelector("[data-scoring-input-status]");
    const hasContext = Boolean(this.draft.selectedSongId || summary.selectedCards.length);
    if (status) {
      status.textContent = hasContext
        ? this.labels.fixed
        : this.labels.blankDraft;
    }
    const hash = this.querySelector("[data-scoring-input-hash]");
    if (hash) hash.textContent = snapshot.inputHash;
    const json = this.querySelector("[data-scoring-snapshot-json]");
    if (json) json.textContent = JSON.stringify(snapshot, null, 2);
    const optimizeLink=this.querySelector('[data-score-optimize-link]');
    if(optimizeLink)optimizeLink.href=toolRoute(`/tools/optimizer/${serializeTeamDraftSearch(this.draft)}`,window.location.pathname);
    const editLink = this.querySelector("[data-edit-scoring-draft]");
    let rankingLink = this.querySelector('[data-song-ranking-link]');
    if (!rankingLink) { rankingLink = document.createElement('a'); rankingLink.dataset.songRankingLink = ''; rankingLink.textContent = '查看歌曲排行榜 →'; this.querySelector('.calculator-links').append(rankingLink); }
    rankingLink.href = toolRoute('/tools/song-ranking/', window.location.pathname);
    if (editLink instanceof HTMLAnchorElement) {
      editLink.href = toolRoute(`/tools/deck-builder/${serializeTeamDraftSearch(this.draft)}`, window.location.pathname);
    }

    const summaryNode = this.querySelector("[data-scoring-input-summary]");
    if (summaryNode) {
      const track = this.trackById.get(this.draft.selectedSongId);
      const values = [
        [this.labels.power, snapshot.formationPower?.total?.total?.toLocaleString() ?? this.labels.invalidInput, false],
        [
          this.labels.fields.track,
          track?.title ?? this.labels.notSelected,
          Boolean(track)
        ],
        [
          this.labels.fields.difficulty,
          this.draft.selectedDifficulty?.toUpperCase() ??
            this.labels.notSelected,
          false
        ],
        [this.labels.fields.cards, String(summary.selectedCards.length), false],
        [
          this.labels.fields.tgwCard,
          snapshot.tgwCardBonus
            ? `R${snapshot.tgwCardBonus.rank} · ${snapshot.tgwCardBonus.rawValue / 100}%`
            : this.labels.notSelected,
          false
        ],
        [
          this.labels.fields.noteObjects,
          snapshot.chart?.noteObjectCount === null ? this.labels.chartUnavailable : String(snapshot.chart?.noteObjectCount ?? 0),
          false
        ],
        [
          this.labels.fields.fullCombo,
          String(snapshot.chart?.fullComboCount ?? 0),
          false
        ]
      ];
      summaryNode.replaceChildren(...values.map(([label, value, entity]) => {
        const row = document.createElement("div");
        const term = document.createElement("dt");
        const definition = document.createElement("dd");
        term.textContent = label;
        definition.textContent = value;
        if (label === this.labels.fields.fullCombo) definition.dataset.scoringEventCount = "";
        if (entity) definition.dataset.uiEntity = "";
        row.append(term, definition);
        return row;
      }));
    }

    const trace = this.querySelector("[data-scoring-trace]");
    if (trace) {
      trace.replaceChildren();
      if (issues.length > 0) {
        issues.forEach((entry) => {
          const item = document.createElement("li");
          item.dataset.status = "rejected";
          item.textContent =
            this.labels.issues[entry.code] ?? entry.code;
          trace.append(item);
        });
      }
      result.trace.forEach((entry) => {
        const item = document.createElement("li");
        item.dataset.status = entry.status;
        const label = document.createElement("strong");
        label.textContent = entry.stage.toUpperCase();
        const copy = document.createElement("span");
        copy.textContent = this.labels.trace[entry.code] ?? entry.code;
        item.append(label, copy);
        trace.append(item);
      });
    }
  }
}

if (!customElements.get("scoring-research-workbench")) {
  customElements.define("scoring-research-workbench", ScoringResearchWorkbench);
}
