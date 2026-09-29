import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { localizeHtml } from "../src/lib/html-localizer.ts";
import { localizeDirectory } from "../../tools/localize_site_output.mjs";

test("localizes HTML text and accessible attributes without touching raw content", () => {
  const source = `<!doctype html>
<html lang="zh-CN">
  <head>
    <title>角色档案 · Our Notes Archive</title>
    <style>.label::after { content: "角色档案"; }</style>
  </head>
  <body>
    <h1> 角色档案 </h1>
    <p>第 12 集</p>
    <p>BIRTHDAY · 6月7日</p>
    <p>5 个角色</p>
    <button aria-label="关闭图片预览" title='资源详情'>打开资源中心</button>
    <input placeholder="搜索曲目" alt=角色档案>
    <code>角色档案</code>
    <pre>第 3 集</pre>
    <script>const label = "角色档案";</script>
  </body>
</html>`;

  const localized = localizeHtml(source, "en");

  assert.match(
    localized,
    /<title>Character Archive · Our Notes Archive<\/title>/
  );
  assert.match(localized, /<h1> Character Archive <\/h1>/);
  assert.match(localized, /<p>Episode 12<\/p>/);
  assert.match(localized, /<p>BIRTHDAY · 6\/7<\/p>/);
  assert.match(localized, /<p>5 characters<\/p>/);
  assert.match(localized, /aria-label="Close image preview"/);
  assert.match(localized, /title='Resource details'/);
  assert.match(localized, /placeholder="Search tracks"/);
  assert.match(localized, /alt="Character Archive"/);
  assert.match(localized, /<code>角色档案<\/code>/);
  assert.match(localized, /<pre>第 3 集<\/pre>/);
  assert.match(localized, /const label = "角色档案"/);
  assert.match(localized, /content: "角色档案"/);
  assert.equal(localizeHtml(source, "zh-CN"), source);
});

test("localizes a directory with atomic file replacement and reports changes", async () => {
  const root = await mkdtemp(join(tmpdir(), "ournotes-localizer-"));
  await writeFile(
    join(root, "index.html"),
    "<main><h1>角色档案</h1></main>",
    "utf8"
  );
  await writeFile(
    join(root, "about.html"),
    '<p aria-label="图片预览">角色与卡牌</p>',
    "utf8"
  );
  await writeFile(join(root, "keep.txt"), "角色档案", "utf8");

  const stats = await localizeDirectory(root, "en");

  assert.deepEqual(stats, {
    fileCount: 2,
    changedFileCount: 2,
    translatedTextCount: 2,
    translatedAttributeCount: 1
  });
  assert.equal(
    await readFile(join(root, "index.html"), "utf8"),
    "<main><h1>Character Archive</h1></main>"
  );
  assert.equal(await readFile(join(root, "keep.txt"), "utf8"), "角色档案");
  assert.deepEqual(
    (await readdir(root)).filter((name) => name.includes(".localize-")),
    []
  );
});
