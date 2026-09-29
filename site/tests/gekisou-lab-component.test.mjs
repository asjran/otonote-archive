import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(
  new URL("../src/components/GekisouBattleLab.astro", import.meta.url),
  "utf8"
);
const page = readFileSync(
  new URL("../src/pages/tools/gekisou-lab/index.astro", import.meta.url),
  "utf8"
);
const runtime = readFileSync(
  new URL("../src/lib/gekisou-lab-workbench.mjs", import.meta.url),
  "utf8"
);
const styles = readFileSync(
  new URL("../src/styles/gekisou-lab.css", import.meta.url),
  "utf8"
);

test("keeps the laboratory implementation while its public route is paused", () => {
  assert.doesNotMatch(page, /GekisouBattleLab/);
  assert.match(page, /暂停开放/);
  assert.match(component, /规则模式只展示已确认的三段结构/);
  assert.match(component, /data-gekisou-participant-count/);
  assert.match(component, /data-gekisou-scenario-json/);
});

test("workbench uses the shared scenario engine and TeamDraft contract", () => {
  assert.match(runtime, /runGekisouResearchSimulation/);
  assert.match(runtime, /createTeamDraft/);
  assert.match(runtime, /validateTeamDraft/);
  assert.match(runtime, /counterfactualOverrides/);
  assert.match(component, /data-gekisou-contributions/);
  assert.match(component, /data-gekisou-override-owner-kind/);
  assert.match(runtime, /participant\.contributions/);
});

test("workbench labels its timeline for the full one-to-five participant range", () => {
  assert.match(component, /对战时间线/);
  assert.doesNotMatch(component, /五人时间线/);
});

test("workbench exposes performance, card, luck, skill, and comparison inputs", () => {
  assert.match(component, /data-gekisou-segment-inputs/);
  assert.match(component, /data-gekisou-note-index/);
  assert.match(component, /data-gekisou-team-slots/);
  assert.match(component, /data-gekisou-luck-inputs/);
  assert.match(component, /data-gekisou-skill-source/);
  assert.match(component, /data-gekisou-save-comparison/);
  assert.match(runtime, /performancePlan/);
  assert.match(runtime, /skillBranches/);
  assert.match(runtime, /luckOutcomes/);
  assert.match(runtime, /this\.comparisons/);
});

test("configuration controls cannot expand past the narrow research sidebar", () => {
  assert.match(
    styles,
    /\.gekisou-lab-config\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s
  );
  assert.match(
    styles,
    /\.gekisou-note-input-form\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*\.7fr\)\s+minmax\(0,\s*1fr\)/s
  );
  assert.match(
    styles,
    /\.gekisou-note-input-form\s+\.gekisou-check\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/s
  );
});
