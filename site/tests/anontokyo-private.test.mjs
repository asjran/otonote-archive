import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  loadPlayerGuide,
  privatePreviewPaths
} from "../src/lib/anontokyo-private.mjs";


const SITE_ROOT = path.dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const REPO_ROOT = path.dirname(SITE_ROOT);


test("AnonTokyo routes require an explicit publication flag", () => {
  assert.deepEqual(privatePreviewPaths({}), []);
  const config = readFileSync(path.join(SITE_ROOT, "astro.config.mjs"), "utf8");
  assert.equal(
    existsSync(path.join(SITE_ROOT, "src/pages/anontokyo/[...view].astro")),
    false
  );
  assert.equal(
    existsSync(path.join(SITE_ROOT, "src/private-pages/anontokyo/[...view].astro")),
    true
  );
  assert.match(config, /anontokyoEnabled[\s\S]*injectRoute/);
  assert.match(config, /src\/private-pages\/anontokyo\/\[\.\.\.view\]\.astro/);
});


test("explicit public build verifies projection and returns guide routes", () => {
  const temporary = mkdtempSync(path.join(tmpdir(), "ournotes-anontokyo-"));
  const projection = path.join(temporary, "projection");
  const playerGuide = path.join(temporary, "player-guide");
  const stagedMediaManifest = path.join(temporary, "staged-media.json");
  try {
    execFileSync(
      "python3",
      [
        "-c",
        [
          "from pathlib import Path",
          "from tools.anontokyo_projection import build_anontokyo_projection",
          "from tools.anontokyo_player_guide import build_anontokyo_player_guide",
          `build_anontokyo_projection(master_root=Path(${JSON.stringify(path.join(REPO_ROOT, "tests/fixtures/anontokyo/minimal/master"))}), catalog_path=Path(${JSON.stringify(path.join(REPO_ROOT, "tests/fixtures/anontokyo/minimal/catalog.json"))}), map_config_path=Path(${JSON.stringify(path.join(REPO_ROOT, "tests/fixtures/anontokyo/minimal/MapConfig_1.json"))}), output_root=Path(${JSON.stringify(projection)}), source_release_id=\"global-staging-fixture\", generated_at=\"2026-08-05T00:00:00Z\")`,
          `build_anontokyo_player_guide(projection_root=Path(${JSON.stringify(projection)}), output_root=Path(${JSON.stringify(playerGuide)}))`
        ].join("; ")
      ],
      { cwd: REPO_ROOT, stdio: "pipe" }
    );
    writeFileSync(
      stagedMediaManifest,
      JSON.stringify([
        {
          id: "3af39c5f82cc16cc",
          logicalKey: "goods_100",
          publicUrl: "/media/anontokyo/3af39c5f82cc16cc.png"
        }
      ])
    );

    const loaded = loadPlayerGuide(playerGuide);
    assert.equal(loaded.goods.records[0].name, "合成连衣裙");
    assert.ok(loaded.furniture.records.some((record) => record.name === "货架"));
    assert.equal(loaded.themes.records[0].name, "测试主题");
    assert.equal(loaded.stages.records[0].band, "测试乐队");
    assert.equal(loaded.chats.records[0].scenes[0].lines[0], "第一句");
    assert.equal(loaded.store.levels[0].level, 1);
    assert.equal(loaded.growth.records[1].expToNext, null);
    assert.equal(loaded.customers.records[0].preferences.length, 2);
    assert.equal(loaded.wardrobe.records.length, 2);
    assert.equal(loaded.inspiration.records[1].minimum, 20);
    assert.equal(loaded.store.deliveryOptions[1].effect, "配送时间 -10%");
    assert.equal(loaded.studio.furniture.length, 2);

    const paths = privatePreviewPaths({
      PUBLIC_ANONTOKYO_ENABLED: "1",
      OURNOTES_ANONTOKYO_PLAYER_GUIDE_ROOT: playerGuide,
      OURNOTES_ANONTOKYO_STAGED_MEDIA_MANIFEST: stagedMediaManifest
    });
    assert.ok(paths.some((entry) => entry.params.view === undefined));
    assert.ok(paths.some((entry) => entry.params.view === "goods"));
    assert.ok(paths.some((entry) => entry.params.view === "growth"));
    assert.ok(paths.some((entry) => entry.params.view === "customers"));
    assert.ok(paths.some((entry) => entry.params.view === "wardrobe"));
    assert.ok(paths.some((entry) => entry.params.view === "inspiration"));
    assert.ok(paths.some((entry) => entry.params.view === "furniture"));
    assert.ok(paths.some((entry) => entry.params.view === "themes"));
    assert.ok(paths.some((entry) => entry.params.view === "stages"));
    assert.ok(paths.some((entry) => entry.params.view === "chats"));
    assert.ok(paths.some((entry) => entry.params.view === "store"));
    assert.ok(paths.some((entry) => entry.params.view === "tasks"));
    assert.ok(paths.some((entry) => entry.params.view === "staff"));
    assert.ok(paths.some((entry) => entry.params.view === "staff-assignment"));
    assert.ok(paths.some((entry) => entry.params.view === "studio"));
    assert.ok(paths.some((entry) => entry.params.view?.startsWith("goods/goods-")));
    assert.ok(paths.some((entry) => entry.params.view?.startsWith("furniture/furniture-")));
    assert.ok(paths.some((entry) => entry.params.view?.startsWith("themes/theme-")));
    assert.ok(paths.some((entry) => entry.params.view?.startsWith("stages/stage-")));
    assert.ok(paths.some((entry) => entry.params.view?.startsWith("chats/chat-")));
    assert.ok(!paths.some((entry) => entry.params.view === "goods/100"));
    assert.equal(paths[0].props.manifest.formulaCapabilities.goodsProfit, "blocked");
    assert.equal(paths[0].props.stagedMedia[0].logicalKey, "goods_100");
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});


test("player pages keep the dense guide contract and exclude evidence UI", () => {
  const routeSource = readFileSync(
    path.join(SITE_ROOT, "src/private-pages/anontokyo/[...view].astro"),
    "utf8"
  );
  const styles = readFileSync(
    path.join(SITE_ROOT, "src/styles/anontokyo-private.css"),
    "utf8"
  );
  assert.ok(!routeSource.includes("AnonTokyoEvidence"));
  assert.ok(!routeSource.includes("JSON.stringify"));
  assert.ok(routeSource.includes("AnonTokyoFurnitureBrowser"));
  assert.ok(routeSource.includes("AnonTokyoThemeBrowser"));
  assert.ok(routeSource.includes("AnonTokyoStageBrowser"));
  assert.ok(routeSource.includes("AnonTokyoChatBrowser"));
  assert.ok(routeSource.includes("AnonTokyoGrowthBrowser"));
  assert.ok(routeSource.includes("AnonTokyoCustomerBrowser"));
  assert.ok(routeSource.includes("AnonTokyoWardrobeBrowser"));
  assert.ok(routeSource.includes("AnonTokyoInspirationBrowser"));
  assert.ok(routeSource.includes("Global 客户端 · 内容保存预览"));
  assert.ok(routeSource.includes("AnonTokyoStaffAssignment"));
  assert.ok(routeSource.includes("GLOBAL / zh-CN"));
  assert.match(styles, /\.at-goods-grid[\s\S]*minmax\(210px, 1fr\)/);
  assert.match(styles, /\.at-goods-card__image[\s\S]*width: 72px/);
  assert.match(styles, /\.at-furniture-grid[\s\S]*minmax\(210px, 1fr\)/);
  assert.match(styles, /\.at-furniture-card__image[\s\S]*width: 72px/);
  assert.match(styles, /\.at-staff-grid[\s\S]*minmax\(260px, 1fr\)/);
  assert.match(styles, /\.at-theme-list/);
  assert.match(styles, /\.at-stage-grid/);
  assert.match(styles, /\.at-chat-grid/);
  assert.match(styles, /\.at-task-row/);
  assert.match(styles, /\.at-growth-row[\s\S]*grid-template-columns/);
  assert.match(styles, /\.at-capacity-grid[\s\S]*minmax\(135px, 1fr\)/);
  assert.match(styles, /\.at-customer-grid[\s\S]*minmax\(280px, 1fr\)/);
  assert.match(styles, /\.at-wardrobe-grid[\s\S]*minmax\(210px, 1fr\)/);
  assert.match(styles, /\.at-inspiration-calculator/);
  assert.match(styles, /\.at-delivery-grid/);
});
