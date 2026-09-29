import assert from "node:assert/strict";
import test from "node:test";

import {
  getUi,
  uiDictionaries
} from "../src/lib/ui-i18n.ts";

test("published UI dictionaries expose exactly the same keys", () => {
  assert.deepEqual(
    Object.keys(uiDictionaries.en).sort(),
    Object.keys(uiDictionaries["zh-CN"]).sort()
  );
});

test("unknown and unpublished locales fall back to Simplified Chinese", () => {
  assert.equal(getUi("en").navHome, "Home");
  assert.equal(getUi("ja").navHome, "首页");
  assert.equal(getUi(undefined).navHome, "首页");
});

test("product copy exposes localized capability and evidence labels", () => {
  assert.deepEqual(
    {
      sourceAndLimits: getUi("zh-CN").sourceAndLimits,
      availableNow: getUi("zh-CN").availableNow,
      unavailableNow: getUi("zh-CN").unavailableNow,
      requiredEvidence: getUi("zh-CN").requiredEvidence
    },
    {
      sourceAndLimits: "来源与限制",
      availableNow: "现在可以",
      unavailableNow: "目前不能",
      requiredEvidence: "仍需验证"
    }
  );
  assert.deepEqual(
    {
      sourceAndLimits: getUi("en").sourceAndLimits,
      availableNow: getUi("en").availableNow,
      unavailableNow: getUi("en").unavailableNow,
      requiredEvidence: getUi("en").requiredEvidence
    },
    {
      sourceAndLimits: "Sources & limitations",
      availableNow: "Available now",
      unavailableNow: "Not available yet",
      requiredEvidence: "Evidence still needed"
    }
  );
});
