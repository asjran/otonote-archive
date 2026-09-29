import assert from "node:assert/strict";
import test from "node:test";

import {
  chooseProjection,
  displayedLocale,
  logicalPath,
  projectionSwitchHref,
  siteHref,
  switchTarget
} from "../src/lib/site-context.ts";

const globalZh = {
  contentReleaseId: "global-release",
  region: "global",
  channel: "production",
  locale: "zh-CN",
  catalogPath: "/data/releases/global-release/zh-CN/catalog.json"
};
const globalEn = { ...globalZh, locale: "en" };
const nextRelease = { ...globalZh, contentReleaseId: "global-next" };
const projections = [globalZh, globalEn];

test("generates Global projection links", () => {
  assert.equal(logicalPath("/global/zh-CN/catalog/", globalZh), "/catalog/");
  assert.equal(logicalPath("/catalog/", globalZh), "/catalog/");
  assert.equal(siteHref("/catalog/", globalZh), "/global/zh-CN/catalog/");
});

test("runtime media and dynamically generated growth art remain pinned", () => {
  const key=Symbol.for('ournotes.content-root.v1');
  globalThis[key]='/content/releases/aaaaaaaaaaaaaaaaaaaaaaaa/';
  try {
    assert.equal(siteHref('/growth/',globalZh),globalThis[key]+'public/growth/');
    assert.equal(siteHref('/mission-rewards/item.webp',globalZh),globalThis[key]+'public/mission-rewards/item.webp');
    assert.equal(siteHref('/immersive/10001/',globalZh),'/global/zh-CN/immersive/10001/');
    assert.equal(siteHref('/content/releases/example/image.webp',globalZh),'/content/releases/example/image.webp');
  } finally {delete globalThis[key];}
});

test("selects only available Global locales", () => {
  assert.equal(chooseProjection(projections, "global", "zh-CN"), globalZh);
  assert.equal(chooseProjection([globalEn], "global", "zh-CN"), globalEn);
  assert.equal(chooseProjection([], "global", "en"), undefined);
});

test("switching Global releases drops a release-specific entity route", () => {
  assert.equal(
    switchTarget("/global/zh-CN/cards/members/member-card-1/", globalZh, nextRelease),
    "/global/zh-CN/cards/members/?unavailable=%2Fcards%2Fmembers%2Fmember-card-1%2F"
  );
});

test("locale switch preserves an entity route within one release", () => {
  assert.equal(
    switchTarget("/global/zh-CN/characters/character-1/", globalZh, globalEn),
    "/global/en/characters/character-1/"
  );
});

test("displayed locale matches the projected language", () => {
  assert.equal(displayedLocale("zh-CN", "en"), "en");
});

test("single-projection mode emits only reachable links", () => {
  assert.equal(projectionSwitchHref("/catalog/", globalZh, globalZh, "single"), "/catalog/");
  assert.equal(projectionSwitchHref("/catalog/", globalZh, globalEn, "single"), null);
  assert.equal(
    projectionSwitchHref("/global/zh-CN/catalog/", globalZh, globalEn, "matrix"),
    "/global/en/catalog/"
  );
});
