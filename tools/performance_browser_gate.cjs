"use strict";

const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");


function canonicalizeJson(value) {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalizeJson(value[key])]),
    );
  }
  return value;
}


function digestPerformanceContract(payload) {
  const canonical = JSON.stringify(canonicalizeJson(payload));
  return `sha256:${crypto.createHash("sha256").update(canonical).digest("hex")}`;
}


function createBrowserBaseline({ generatedAt, gitHead, contractDigest, runner, results }) {
  return {
    schemaVersion: 1,
    generatedAt,
    gitHead,
    contractDigest,
    runner,
    cases: results.map((result) => ({
      id: result.id,
      bytes: result.bytes,
      requestCount: result.requestCount,
    })),
  };
}


function assertBaselineWritePolicy({ baselinePath, outputPath, writeBaseline }) {
  if (
    baselinePath && outputPath &&
    path.resolve(baselinePath) === path.resolve(outputPath) &&
    !writeBaseline
  ) {
    throw new Error("baseline_write_requires_explicit_flag");
  }
}


function expandBrowserCases(payload) {
  if (Number(payload?.schemaVersion) !== 1) {
    throw new Error(`unsupported browser contract schemaVersion: ${payload?.schemaVersion}`);
  }
  const profile = payload.productProfile ?? "v1";
  if (profile !== "v1") throw new Error("unsupported product profile");
  const expectedCount = 36;
  if (profile === "v1") {
    const expectedRoutes = ["home", "tools", "music", "characters", "character-detail", "member-detail", "support-detail", "music-detail", "events"].sort();
    if (JSON.stringify(payload.browser.routes.map(route => route.id).sort()) !== JSON.stringify(expectedRoutes)) {
      throw new Error("noncanonical product v1 browser routes");
    }
  }
  const cases = [];
  for (const route of payload.browser.routes) {
    for (const locale of payload.locales) {
      for (const viewport of payload.viewports) {
        cases.push({
          id: `${route.id}.${locale}.${viewport.name}`,
          routeId: route.id,
          locale,
          path: route.path.replace("{locale}", locale),
          viewport: {
            name: viewport.name,
            width: viewport.width,
            height: viewport.height,
          },
          maxBytes: route.maxBytes,
          maxRequests: route.maxRequests,
          maxByteGrowthRatio: payload.browser.maxByteGrowthRatio,
          maxRequestGrowth: payload.browser.maxRequestGrowth,
        });
      }
    }
  }
  if (cases.length !== expectedCount || new Set(cases.map((item) => item.id)).size !== expectedCount) {
    throw new Error(`noncanonical browser case matrix: ${cases.length}`);
  }
  return cases;
}


function loadBrowserCases(contractPath) {
  return expandBrowserCases(JSON.parse(fs.readFileSync(contractPath, "utf8")));
}


function validateBrowserBaseline(baseline, expected) {
  if (Number(baseline.schemaVersion) !== 1) {
    return { pass: false, reasonCodes: ["baseline_schema_mismatch"] };
  }
  if (baseline.contractDigest !== expected.contractDigest) {
    return { pass: false, reasonCodes: ["baseline_contract_digest_mismatch"] };
  }
  if (baseline.runner !== expected.runner) {
    return { pass: false, reasonCodes: ["baseline_runner_mismatch"] };
  }
  const baselineCaseIds = (baseline.cases || []).map((item) => item.id);
  const actualIds = new Set(baselineCaseIds);
  if (actualIds.size !== baselineCaseIds.length) {
    return { pass: false, reasonCodes: ["baseline_duplicate_case"] };
  }
  const missingCase = expected.caseIds.some((id) => !actualIds.has(id));
  const reasonCodes = missingCase ? ["baseline_missing_case"] : [];
  return { pass: reasonCodes.length === 0, reasonCodes };
}


function writeBrowserBaseline(baselinePath, payload, { allowWrite = false } = {}) {
  if (!allowWrite) {
    throw new Error("baseline_write_requires_explicit_flag");
  }
  fs.mkdirSync(path.dirname(baselinePath), { recursive: true });
  fs.writeFileSync(baselinePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}


function isDangerousMediaUrl(value) {
  let pathname;
  try {
    pathname = new URL(String(value), "http://ournotes.invalid").pathname.toLowerCase();
  } catch {
    pathname = String(value).toLowerCase().split(/[?#]/, 1)[0];
  }
  return pathname.includes("/live2d/") ||
    /\.(?:moc3|model3\.json|mp3|m4a|aac|flac|wav|ogg|mp4|webm|mov)$/.test(pathname);
}


function evaluateBrowserMeasurement(caseDefinition, measurement, baselineCase) {
  const reasonCodes = [];
  if (Number(measurement.status) !== 200) {
    reasonCodes.push("main_response_not_ok");
  }
  if ((measurement.badResponses || []).length > 0) {
    reasonCodes.push("subresource_http_error");
  }
  if ((measurement.requestFailures || []).length > 0) {
    reasonCodes.push("request_failed");
  }
  if ((measurement.dangerousMedia || []).length > 0) {
    reasonCodes.push("automatic_dangerous_media");
  }
  const absoluteBytesExceeded = Number(measurement.bytes) > Number(caseDefinition.maxBytes);
  const absoluteRequestsExceeded = Number(measurement.requestCount) > Number(caseDefinition.maxRequests);
  if (absoluteBytesExceeded) {
    reasonCodes.push("byte_budget_exceeded");
  }
  if (absoluteRequestsExceeded) {
    reasonCodes.push("request_budget_exceeded");
  }
  if (baselineCase && !absoluteBytesExceeded && !absoluteRequestsExceeded) {
    const maxBaselineBytes = Math.ceil(
      Number(baselineCase.bytes) * (1 + Number(caseDefinition.maxByteGrowthRatio)),
    );
    const maxBaselineRequests = Number(baselineCase.requestCount) +
      Number(caseDefinition.maxRequestGrowth);
    if (Number(measurement.bytes) > maxBaselineBytes) {
      reasonCodes.push("baseline_byte_growth_exceeded");
    }
    if (Number(measurement.requestCount) > maxBaselineRequests) {
      reasonCodes.push("baseline_request_growth_exceeded");
    }
  }
  return { pass: reasonCodes.length === 0, reasonCodes };
}


module.exports = {
  assertBaselineWritePolicy,
  createBrowserBaseline,
  digestPerformanceContract,
  evaluateBrowserMeasurement,
  expandBrowserCases,
  isDangerousMediaUrl,
  loadBrowserCases,
  validateBrowserBaseline,
  writeBrowserBaseline,
};
