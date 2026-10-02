// One batch uses the same reconstruction as the browser calculator. Master
// counts are compared afterwards; they never determine judgement events.
import {readFileSync, writeFileSync} from 'node:fs';
import {reconstructFormalChart, FORMAL_CHART_MODEL_VERSION} from '../packages/scoring/scoring-rules/formal-chart.mjs';

export function projectFormalChart(chart) {
  const diagnostics = {};
  const events = reconstructFormalChart(chart, diagnostics);
  const duration = Math.max(chart.duration, (events.at(-1)?.timeMs ?? 0) / 1000);
  const density = Array.from({length:Math.max(1,Math.ceil(duration))}, (_,i)=>({start:i,end:Math.min(i+1,duration),count:0}));
  const comboEvents = events.map((event,i)=>{
    const time = event.timeMs / 1000;
    density[Math.max(0,Math.min(Math.floor(time),density.length-1))].count++;
    return {time, noteId:event.noteId, nodeIndex:event.nodeIndex ?? null,
      nativeNoteId:event.nativeNoteId, nativeLineId:event.nativeLineId ?? null,
      nativeLineIds:event.nativeLineIds ?? (event.nativeLineId === undefined ? [] : [event.nativeLineId]),
      markerId:event.kind === 'authored' ? event.noteId + (event.nodeIndex === undefined ? '' : `:${event.nodeIndex}`) : null,
      kind:event.kind === 'authored' ? 'explicit-judgement' : 'slide-combo', combo:i+1};
  });
  const times = [...new Set(comboEvents.map(e=>e.time))];
  const intervals = times.slice(1).map((time,i)=>time-times[i]);
  const peak = density.reduce((a,b)=>b.count>a.count?b:a);
  const generated = events.filter(e=>e.kind === 'slide-combo').length;
  return {...chart, duration, meta:{...chart.meta,runtimeAlgorithmVersion:FORMAL_CHART_MODEL_VERSION}, comboEvents,density,
    statistics:{...chart.statistics, ...diagnostics, runtimeDiagnostics:[], judgementCount:events.length,
      runtimeFullCombo:events.length, sourceJudgementCount:diagnostics.explicitJudgementCount,
      generatedJudgementCount:generated, judgementCountDelta:events.length-diagnostics.explicitJudgementCount,
      judgementCountSource:'client-runtime-reconstruction', densitySource:'client-reconstructed-combo-timeline',
      rhythmicCandidateCount:diagnostics.slideComboCandidateCount, averageDensity:Number((events.length/(duration || 1)).toFixed(3)),
      peakDensity:peak.count, peakWindowStart:peak.start, simultaneousCount:events.length-times.length,
      minimumInterval:intervals.length?Number(Math.min(...intervals).toFixed(6)):null}};
}

if (process.argv[1] && import.meta.url === new URL(process.argv[1], 'file:').href) {
  const charts = JSON.parse(readFileSync(process.argv[2]));
  writeFileSync(process.argv[3], JSON.stringify(Object.fromEntries(Object.entries(charts).map(([id,chart])=>[id,projectFormalChart(chart)]))));
}
