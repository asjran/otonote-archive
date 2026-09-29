// Run from any cwd: node tools/verify_formal_charts.mjs [report.json]
// Master is used ONLY for comparison; it is never passed to reconstruction.
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { reconstructFormalChart } from "../site/src/lib/scoring-rules/formal-chart.mjs";

const root = new URL("../site/", import.meta.url);
const rules = JSON.parse(readFileSync(new URL("src/data/formal-scoring-rules.json", root)));
const dir = new URL("public/data/music-charts/", root);
const weights = new Map(rules.tables.LiveNoteParameter.map((r) => [r._noteOperateType, r._scorePercent]));
const charts = readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((file) => {
  const raw = readFileSync(new URL(file, dir));
  const chart = JSON.parse(raw);
  const events = reconstructFormalChart(chart);
  const master = rules.tables.LiveMusicScore.find((m) => m._id === Number(chart.id.split("-").at(-1)));
  if (!master || events.some((e) => !weights.has(e.type))) throw new Error(`Unsupported chart ${file}`);
  return { chartId: chart.id, sourceSha256: createHash("sha256").update(raw).digest("hex"),
    legacyCount: chart.comboEvents.length, reconstructedCount: events.length, masterCount: master._fullComboCount,
    convertedNoteCount: Math.ceil(Math.fround(events.reduce((sum, e) => Math.fround(sum + weights.get(e.type)), 0) / 100)),
    eventSha256: createHash("sha256").update(JSON.stringify(events)).digest("hex") };
});
const report = { sourceReleaseId: rules.sourceReleaseId, nativeSha256: rules.nativeSha256,
  ruleSetVersion: rules.ruleSetVersion, total: charts.length,
  legacyMatched: charts.filter((c) => c.legacyCount === c.masterCount).length,
  reconstructedMatched: charts.filter((c) => c.reconstructedCount === c.masterCount).length,
  scope: "Master FC cross-check, not a proof of frame-level judgement ordering", charts };
if (process.argv[2]) writeFileSync(process.argv[2], JSON.stringify(report, null, 2) + "\n");
const { charts: _, ...summary } = report;
console.log(JSON.stringify(summary, null, 2));
if (!charts.length || report.reconstructedMatched !== charts.length) process.exitCode = 1;
