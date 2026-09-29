import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  assertBaselineWritePolicy,
  createBrowserBaseline,
  digestPerformanceContract,
  evaluateBrowserMeasurement,
  expandBrowserCases,
  isDangerousMediaUrl,
  validateBrowserBaseline,
  writeBrowserBaseline,
} = require("../../tools/performance_browser_gate.cjs");


test("a browser measurement within the absolute contract passes", () => {
  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 200,
      bytes: 999,
      requestCount: 10,
      badResponses: [],
      requestFailures: [],
      dangerousMedia: [],
    },
  );

  assert.deepEqual(verdict, { pass: true, reasonCodes: [] });
});


test("a child resource HTTP error fails with a stable reason code", () => {
  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 200,
      bytes: 500,
      requestCount: 5,
      badResponses: [{ url: "/broken.css", status: 404 }],
      requestFailures: [],
      dangerousMedia: [],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["subresource_http_error"],
  });
});


test("a failed browser request fails with a stable reason code", () => {
  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 200,
      bytes: 500,
      requestCount: 5,
      badResponses: [],
      requestFailures: [{ url: "/app.js", error: "net::ERR_FAILED" }],
      dangerousMedia: [],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["request_failed"],
  });
});


test("automatic audio video and Live2D requests fail as dangerous media", () => {
  const dangerousUrls = [
    "/media/song.m4a",
    "/media/movie.webm",
    "/media/model.moc3",
    "/media/model.model3.json",
    "/media/live2d/texture.png",
  ];
  assert.equal(dangerousUrls.every(isDangerousMediaUrl), true);
  assert.equal(isDangerousMediaUrl("/media/poster.webp"), false);

  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 200,
      bytes: 500,
      requestCount: 5,
      badResponses: [],
      requestFailures: [],
      dangerousMedia: dangerousUrls,
    },
  );
  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["automatic_dangerous_media"],
  });
});


test("an absolute byte budget overrun fails with a stable reason code", () => {
  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 200,
      bytes: 1001,
      requestCount: 5,
      badResponses: [],
      requestFailures: [],
      dangerousMedia: [],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["byte_budget_exceeded"],
  });
});


test("an absolute request budget overrun fails with a stable reason code", () => {
  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 200,
      bytes: 500,
      requestCount: 11,
      badResponses: [],
      requestFailures: [],
      dangerousMedia: [],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["request_budget_exceeded"],
  });
});


test("a non-200 main response fails with a stable reason code", () => {
  const verdict = evaluateBrowserMeasurement(
    { maxBytes: 1000, maxRequests: 10 },
    {
      status: 500,
      bytes: 500,
      requestCount: 5,
      badResponses: [],
      requestFailures: [],
      dangerousMedia: [],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["main_response_not_ok"],
  });
});


test("the versioned browser contract expands into 36 stable cases", () => {
  const payload = JSON.parse(fs.readFileSync(
    new URL("../../config/performance/gates.product-v1.json", import.meta.url),
    "utf8",
  ));

  const cases = expandBrowserCases(payload);

  assert.equal(cases.length, 36);
  assert.equal(new Set(cases.map((item) => item.id)).size, 36);
  assert.deepEqual(cases[0], {
    id: "home.zh-CN.desktop",
    routeId: "home",
    locale: "zh-CN",
    path: "/global/zh-CN/",
    viewport: { name: "desktop", width: 1440, height: 900 },
    maxBytes: 716800,
    maxRequests: 30,
    maxByteGrowthRatio: 0.05,
    maxRequestGrowth: 1,
  });
  assert.equal(cases.at(-1).id, "events.en.mobile");
});


test("a candidate stays within the fixed baseline growth allowance", () => {
  const caseDefinition = {
    maxBytes: 2000,
    maxRequests: 20,
    maxByteGrowthRatio: 0.05,
    maxRequestGrowth: 1,
  };
  const measurement = {
    status: 200,
    bytes: 1050,
    requestCount: 11,
    badResponses: [],
    requestFailures: [],
    dangerousMedia: [],
  };

  assert.deepEqual(
    evaluateBrowserMeasurement(caseDefinition, measurement, { bytes: 1000, requestCount: 10 }),
    { pass: true, reasonCodes: [] },
  );
  assert.deepEqual(
    evaluateBrowserMeasurement(caseDefinition, { ...measurement, bytes: 1051 }, { bytes: 1000, requestCount: 10 }),
    { pass: false, reasonCodes: ["baseline_byte_growth_exceeded"] },
  );
  assert.deepEqual(
    evaluateBrowserMeasurement(caseDefinition, { ...measurement, requestCount: 12 }, { bytes: 1000, requestCount: 10 }),
    { pass: false, reasonCodes: ["baseline_request_growth_exceeded"] },
  );
});


test("absolute budgets take precedence over baseline growth", () => {
  const verdict = evaluateBrowserMeasurement(
    {
      maxBytes: 1100,
      maxRequests: 20,
      maxByteGrowthRatio: 0.05,
      maxRequestGrowth: 1,
    },
    {
      status: 200,
      bytes: 1101,
      requestCount: 10,
      badResponses: [],
      requestFailures: [],
      dangerousMedia: [],
    },
    { bytes: 1000, requestCount: 10 },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["byte_budget_exceeded"],
  });
});


test("a baseline missing an expected case fails closed", () => {
  const verdict = validateBrowserBaseline(
    {
      schemaVersion: 1,
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      cases: [{ id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 }],
    },
    {
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      caseIds: ["home.zh-CN.desktop", "tools.zh-CN.desktop"],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["baseline_missing_case"],
  });
});


test("a baseline with a duplicate case fails closed", () => {
  const baselineCase = { id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 };
  const verdict = validateBrowserBaseline(
    {
      schemaVersion: 1,
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      cases: [baselineCase, { ...baselineCase }],
    },
    {
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      caseIds: ["home.zh-CN.desktop"],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["baseline_duplicate_case"],
  });
});


test("a baseline for a different contract digest fails closed", () => {
  const verdict = validateBrowserBaseline(
    {
      schemaVersion: 1,
      contractDigest: "sha256:old-contract",
      runner: "fixture-runner",
      cases: [{ id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 }],
    },
    {
      contractDigest: "sha256:current-contract",
      runner: "fixture-runner",
      caseIds: ["home.zh-CN.desktop"],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["baseline_contract_digest_mismatch"],
  });
});


test("a baseline from a different runner fails closed", () => {
  const verdict = validateBrowserBaseline(
    {
      schemaVersion: 1,
      contractDigest: "sha256:contract",
      runner: "other-runner",
      cases: [{ id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 }],
    },
    {
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      caseIds: ["home.zh-CN.desktop"],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["baseline_runner_mismatch"],
  });
});


test("an incompatible baseline schema fails closed", () => {
  const verdict = validateBrowserBaseline(
    {
      schemaVersion: 2,
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      cases: [{ id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 }],
    },
    {
      contractDigest: "sha256:contract",
      runner: "fixture-runner",
      caseIds: ["home.zh-CN.desktop"],
    },
  );

  assert.deepEqual(verdict, {
    pass: false,
    reasonCodes: ["baseline_schema_mismatch"],
  });
});


test("an ordinary run cannot overwrite an existing baseline", (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ournotes-browser-baseline-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const baselinePath = path.join(directory, "baseline.json");
  fs.writeFileSync(baselinePath, "preserve-me", "utf8");

  assert.throws(
    () => writeBrowserBaseline(baselinePath, { schemaVersion: 1 }, { allowWrite: false }),
    /baseline_write_requires_explicit_flag/,
  );
  assert.equal(fs.readFileSync(baselinePath, "utf8"), "preserve-me");
});


test("the contract digest is stable across JSON key order", () => {
  const expected = "sha256:43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777";

  assert.equal(digestPerformanceContract({ b: 2, a: 1 }), expected);
  assert.equal(digestPerformanceContract({ a: 1, b: 2 }), expected);
});


test("an explicit baseline write persists a versioned fixture payload", (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ournotes-browser-baseline-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const baselinePath = path.join(directory, "baseline.json");
  const payload = createBrowserBaseline({
    generatedAt: "2026-08-12T00:00:00.000Z",
    gitHead: "fixture-head",
    contractDigest: "sha256:contract",
    runner: "fixture-runner",
    results: [
      { id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 },
      { id: "tools.zh-CN.desktop", bytes: 500, requestCount: 5 },
    ],
  });

  writeBrowserBaseline(baselinePath, payload, { allowWrite: true });

  assert.deepEqual(JSON.parse(fs.readFileSync(baselinePath, "utf8")), {
    schemaVersion: 1,
    generatedAt: "2026-08-12T00:00:00.000Z",
    gitHead: "fixture-head",
    contractDigest: "sha256:contract",
    runner: "fixture-runner",
    cases: [
      { id: "home.zh-CN.desktop", bytes: 1000, requestCount: 10 },
      { id: "tools.zh-CN.desktop", bytes: 500, requestCount: 5 },
    ],
  });
});


test("a report cannot target the baseline path without explicit baseline write mode", () => {
  assert.throws(
    () => assertBaselineWritePolicy({
      baselinePath: "/tmp/browser-baseline.json",
      outputPath: "/tmp/browser-baseline.json",
      writeBaseline: false,
    }),
    /baseline_write_requires_explicit_flag/,
  );
  assert.doesNotThrow(() => assertBaselineWritePolicy({
    baselinePath: "/tmp/browser-baseline.json",
    outputPath: "/tmp/browser-report.json",
    writeBaseline: false,
  }));
  assert.doesNotThrow(() => assertBaselineWritePolicy({
    baselinePath: "/tmp/browser-baseline.json",
    outputPath: "/tmp/browser-baseline.json",
    writeBaseline: true,
  }));
});


test("product v1 requires all 36 core and event cases", () => {
  const payload = JSON.parse(fs.readFileSync(new URL("../../config/performance/gates.product-v1.json", import.meta.url), "utf8"));
  assert.equal(expandBrowserCases(payload).length, 36);
  payload.browser.routes.at(-1).id = "stories";
  assert.throws(() => expandBrowserCases(payload), /noncanonical/);
});
