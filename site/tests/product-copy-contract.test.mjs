import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createMemberCardDetailModel } from "../src/lib/member-card-detail-model.mjs";
import { createSupportCardDetailModel } from "../src/lib/support-card-detail-model.mjs";

const readSource = (path) =>
  readFile(new URL(path, import.meta.url), "utf8");

const p0Pages = [
  "../src/pages/index.astro",
  "../src/pages/catalog/index.astro",
  "../src/pages/cards/index.astro",
  "../src/pages/music/index.astro",
  "../src/pages/database/index.astro",
  "../src/pages/tools/index.astro",
  "../src/pages/tools/deck-builder/index.astro",
  "../src/pages/tools/song-calculator/index.astro",
  "../src/pages/tools/optimizer/index.astro",
];

test("technical source notes use one native disclosure boundary", async () => {
  const source = await readSource("../src/components/SourceDisclosure.astro");

  assert.match(source, /<details\b/);
  assert.match(source, /data-copy-layer="technical"/);
  assert.match(source, /<summary\b/);
  assert.match(source, /sourceAndLimits/);
});

test("every P0 page separates visitor copy from technical source notes", async () => {
  for (const path of p0Pages) {
    const source = await readSource(path);
    assert.match(source, /data-copy-layer="primary"/, `${path} has no primary copy layer`);
    assert.match(source, /<SourceDisclosure\b/, `${path} has no technical disclosure`);
  }
});

test("tool hero copy does not lead with implementation jargon", async () => {
  const paths = [
    "../src/pages/tools/index.astro",
    "../src/pages/tools/deck-builder/index.astro",
    "../src/pages/tools/song-calculator/index.astro",
    "../src/pages/tools/optimizer/index.astro",
  ];
  for (const path of paths) {
    const source = await readSource(path);
    const primary = source.match(/data-copy-layer="primary"[\s\S]*?<\/section>/)?.[0] ?? "";
    const visibleCopy = primary.replace(/<[^>]*>/g, " ").replace(/\{[^}]*}/g, " ");
    assert.doesNotMatch(visibleCopy, /\b(?:Gate|Release|Master|ScoringEngine|Profile|fixture|Worker|build artifact)\b/i, path);
  }
});

test("score estimates disclose scope", async () => {
  const calculator = await readSource("../src/pages/tools/song-calculator/index.astro");
  const optimizer = await readSource("../src/pages/tools/optimizer/index.astro");
  assert.match(calculator, /逐音符估算歌曲分数/);
  assert.match(calculator, /正式谱面重建/);
  assert.match(optimizer, /普通歌曲期望分/);
  assert.match(optimizer, /已拥有卡库或理论满养成卡库/);
  assert.match(optimizer, /暂不提供激奏总分最优队/);
  assert.match(optimizer, /未知活动规则会明确拒绝计算/);
  assert.match(optimizer, /理想同刻事件情景估算/);
  assert.match(optimizer, /<TeamDraftWorkbench/);
});

test("source disclosures stay compact, keyboard-visible, and mobile-safe", async () => {
  const css = await readSource("../src/styles/global.css");
  assert.match(css, /\.source-disclosure\s*\{/);
  assert.match(css, /\.source-disclosure\s*>\s*summary:focus-visible/);
  assert.match(css, /overflow-wrap:\s*anywhere/);
  assert.match(css, /@media\s*\(max-width:\s*700px\)[\s\S]*\.source-disclosure/);
});

test("home leads with visitor tasks instead of release-process labels", async () => {
  const source = await readSource("../src/pages/index.astro");

  assert.doesNotMatch(source, /VISUAL EVIDENCE|STAGING|PACKAGE|CATALOG NOTE/);
  for (const route of ["/catalog/", "/music/", "/tools/deck-builder/"]) {
    assert.ok(source.includes(`href: "${route}"`));
  }
  assert.match(source, /资料|卡牌/);
});

test("catalog and card entrances explain how visitors can browse and equip", async () => {
  const catalog = await readSource("../src/pages/catalog/index.astro");
  const cards = await readSource("../src/pages/cards/index.astro");

  assert.match(catalog, /按角色、乐队或属性/);
  assert.match(cards, /成员卡用于乐队编成/);
  assert.match(cards, /留影用于装备/);
  assert.match(cards, /登场关系不代表装备限制/);
});

test("member card details make formation the primary action", async () => {
  const detail = createMemberCardDetailModel({
    cardId: "member-card-1",
    skillSummaries: [{ skillId: "skill-1", name: "主技能", summary: "效果" }],
    resolveSkill: () => ({ id: "skill-1", kind: "live" })
  });

  assert.deepEqual(
    detail.primaryAction,
    {
      logicalPath: "/tools/deck-builder/?member=member-card-1",
      label: "加入编成"
    }
  );
});

test("member cards without skill projections can still join a formation", () => {
  const detail = createMemberCardDetailModel({
    cardId: "member-card-without-skills",
    skillSummaries: [],
    resolveSkill: () => undefined
  });

  assert.deepEqual(
    detail.primaryAction,
    {
      logicalPath: "/tools/deck-builder/?member=member-card-without-skills",
      label: "加入编成"
    }
  );
});

test("support details separate both effects and keep deep topics beside the image", () => {
  const detail = createSupportCardDetailModel({
    cardId: "support-card-1",
    skillSummaries: [
      { slot: "support_1", skillId: "support-skill-23", summary: "普通效果" },
      { slot: "gekisou_support_1", skillId: "gekisou-support-skill-22", summary: "激奏效果" }
    ]
  });

  assert.deepEqual(
    {
      aspectRatio: detail.aspectRatio,
      normalEffect: detail.normalEffect?.summary,
      gekisouEffect: detail.gekisouEffect?.summary,
      primaryAction: detail.primaryAction,
      imageSidebarTopics: detail.imageSidebarTopics.map((topic) => topic.id),
      gekisouLogicalPath: detail.imageSidebarTopics.find(
        (topic) => topic.id === "gekisou"
      )?.logicalPath
    },
    {
      aspectRatio: "16:9",
      normalEffect: "普通效果",
      gekisouEffect: "激奏效果",
      primaryAction: {
        logicalPath: "/tools/deck-builder/?support=support-card-1",
        label: "装备到编成"
      },
      imageSidebarTopics: ["growth", "materials", "resources"],
      gekisouLogicalPath: undefined
    }
  );
});

test("card details share growth previews and grouped skills with small artwork actions", async () => {
  const archive = await readSource("../src/components/card-details/CardDetailArchive.astro");
  for (const kind of ["Member", "Support"]) {
    const wrapper = await readSource(`../src/components/card-details/${kind}CardDetail.astro`);
    assert.match(wrapper, /<CardDetailArchive/);
    assert.doesNotMatch(wrapper, /slot="priority"/);
  }
  assert.match(archive, /data-growth-power="total"/);
  assert.match(archive, /class="card-unified-skills"/);
  assert.match(archive, /class="card-info-actions"/);
  assert.match(archive, /class="card-art-download"/);
  assert.match(archive, /data-panel="materials"/);
  assert.doesNotMatch(archive, /data-panel="resources"|gekisou-lab|member-card-primary-skill/);
});

test("music, story, and database entrances describe visitor-visible content", async () => {
  const music = await readSource("../src/pages/music/index.astro");
  const stories = await readSource("../src/pages/stories/index.astro");
  const database = await readSource("../src/pages/database/index.astro");

  for (const term of ["演唱", "BPM", "难度", "谱面结构"]) {
    assert.match(music, new RegExp(term));
  }
  assert.match(music, /无音频模拟播放/);
  assert.match(music, /尚未收录歌曲音频/);
  assert.match(stories, /data-story-library/);
  assert.match(stories, /copy.unavailable/);
  assert.match(database, /查找技能、道具和乐队强化/);
  assert.match(database, /从卡牌反查/);
  assert.match(database, /部分条件[^。]*尚未确认/);
});

test("tools directory exposes score estimates and pairing without an obsolete pending entry", async () => {
  const [page, css] = await Promise.all([
    readSource("../src/pages/tools/index.astro"),
    readSource("../src/styles/tools.css")
  ]);

  assert.deepEqual(
    {
      readyActions: (page.match(/<a[^>]+data-tool-state="available"/g) ?? []).length,
      pendingActions: (page.match(/<a[^>]+data-tool-state="pending"/g) ?? []).length,
      pendingRows: (page.match(/<div[^>]+data-tool-state="pending"/g) ?? []).length,
      routes: ["live2d", "deck-builder", "song-ranking", "song-calculator", "optimizer"]
        .every((route) => page.includes(`/tools/${route}/`)),
      compactHero: page.includes("<ToolPageHeader") && !page.includes("page-stamp"),
      compactReadyCards: /\.tool-module-card--ready\s*\{[^}]*min-height:\s*0/s.test(css),
      pendingLowWeight: css.includes(".tool-pending-row")
    },
    {
      readyActions: 5,
      pendingActions: 0,
      pendingRows: 0,
      routes: true,
      compactHero: true,
      compactReadyCards: true,
      pendingLowWeight: true
    }
  );
});
