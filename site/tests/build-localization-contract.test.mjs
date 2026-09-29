import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { localizeDirectory } from "../../tools/localize_site_output.mjs";

const layoutPath = new URL(
  "../src/layouts/BaseLayout.astro",
  import.meta.url
);

test("build output localizes English HTML and leaves Chinese HTML unchanged", async () => {
  const root = await mkdtemp(join(tmpdir(), "ournotes-build-i18n-"));
  const englishRoot = join(root, "global", "en");
  const chineseRoot = join(root, "jp", "zh-CN");
  await import("node:fs/promises").then(({ mkdir }) =>
    Promise.all([
      mkdir(englishRoot, { recursive: true }),
      mkdir(chineseRoot, { recursive: true })
    ])
  );
  const builtHtml =
    '<!doctype html><html><body><h1>角色档案</h1>' +
    '<button aria-label="关闭图片预览">打开资源中心</button></body></html>';
  await Promise.all([
    writeFile(join(englishRoot, "index.html"), builtHtml, "utf8"),
    writeFile(join(chineseRoot, "index.html"), builtHtml, "utf8")
  ]);

  await localizeDirectory(englishRoot, "en");

  const englishHtml = await readFile(join(englishRoot, "index.html"), "utf8");
  const chineseHtml = await readFile(join(chineseRoot, "index.html"), "utf8");
  assert.match(englishHtml, /Character Archive/);
  assert.match(englishHtml, /aria-label="Close image preview"/);
  assert.doesNotMatch(englishHtml, /角色档案|关闭图片预览/);
  assert.equal(chineseHtml, builtHtml);
});

test("page localization has no runtime observer or inline translation tables", async () => {
  const layout = await readFile(layoutPath, "utf8");

  assert.doesNotMatch(layout, /UiLocalizer|dynamic-ui-localizer/);
  assert.doesNotMatch(
    layout,
    /englishExactTranslations|englishFragmentTranslations/
  );
  assert.doesNotMatch(layout, /MutationObserver/);
});
