import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { parse as parseAstro } from "@astrojs/compiler";
import postcss from "postcss";

const layoutUrl = new URL("../src/layouts/BaseLayout.astro", import.meta.url);
const globalStylesUrl = new URL("../src/styles/global.css", import.meta.url);
const searchStylesUrl = new URL("../src/styles/unified-search.css", import.meta.url);

test("keeps mobile header actions in normal grid flow with safe-area padding", async () => {
  const [layoutSource, stylesSource] = await Promise.all([
    readFile(layoutUrl, "utf8"),
    readFile(globalStylesUrl, "utf8")
  ]);
  const { ast } = await parseAstro(layoutSource);
  const header = astroNodes(ast).find(
    (node) =>
      node.type === "element" &&
      node.name === "header" &&
      attribute(node, "data-site-header") !== undefined
  );
  const actions = header.children.filter(
    (node) =>
      node.type === "component" ||
      (node.type === "element" &&
        node.name === "button" &&
        attribute(node, "data-nav-toggle") !== undefined)
  );
  const viewport = astroNodes(ast).find(
    (node) =>
      node.type === "element" &&
      node.name === "meta" &&
      attribute(node, "name") === "viewport"
  );
  const styles = postcss.parse(stylesSource);
  const headerRule = declarationsInMedia(
    styles,
    "(max-width: 1100px)",
    ".site-header"
  );
  const contextSwitcherRule = declarationsInMedia(
    styles,
    "(max-width: 1100px)",
    ".context-switcher"
  );

  assert.deepEqual(
    actions.map((node) =>
      node.type === "component" ? node.name : "NavigationToggle"
    ),
    ["UnifiedSearch", "RegionLocaleSwitcher", "NavigationToggle"]
  );
  assert.ok(attribute(viewport, "content").includes("viewport-fit=cover"));
  assert.equal(
    headerRule.get("grid-template-columns"),
    "minmax(0, 1fr) repeat(3, auto)"
  );
  assert.ok(
    headerRule.get("padding-left").includes("env(safe-area-inset-left)")
  );
  assert.ok(
    headerRule.get("padding-right").includes("env(safe-area-inset-right)")
  );
  assert.equal(contextSwitcherRule.get("position"), "static");
});

test("keeps mobile search and locale surfaces inside safe areas", async () => {
  const [globalStylesSource, searchStylesSource] = await Promise.all([
    readFile(globalStylesUrl, "utf8"),
    readFile(searchStylesUrl, "utf8")
  ]);
  const globalStyles = postcss.parse(globalStylesSource);
  const searchStyles = postcss.parse(searchStylesSource);
  const panelRule = declarationsInMedia(
    globalStyles,
    "(max-width: 1100px)",
    ".context-switcher__panel"
  );
  const optionsRule = declarationsInMedia(
    globalStyles,
    "(max-width: 1100px)",
    ".context-switcher__options a"
  );
  const dialogRule = declarationsFor(searchStyles, ".global-search-dialog");
  const searchTypesRule = declarationsInMedia(
    searchStyles,
    "(max-width: 1100px)",
    ".global-search-types button"
  );

  assert.equal(panelRule.get("position"), "fixed");
  assert.ok(panelRule.get("right").includes("env(safe-area-inset-right)"));
  assert.ok(panelRule.get("width").includes("env(safe-area-inset-left)"));
  assert.equal(optionsRule.get("min-height"), "44px");
  assert.ok(dialogRule.get("width").includes("env(safe-area-inset-left)"));
  assert.ok(dialogRule.get("width").includes("env(safe-area-inset-right)"));
  assert.equal(searchTypesRule.get("min-height"), "44px");
});

function astroNodes(node) {
  if (!node || typeof node !== "object") return [];
  return [
    node,
    ...(node.children ?? []).flatMap((child) => astroNodes(child))
  ];
}

function attribute(node, name) {
  return node?.attributes?.find((candidate) => candidate.name === name)?.value;
}

function declarationsFor(root, selector) {
  const declarations = new Map();
  root.walkRules((rule) => {
    if (rule.parent.type !== "atrule" && hasSelector(rule, selector)) {
      rule.walkDecls((declaration) => {
        declarations.set(declaration.prop, declaration.value);
      });
    }
  });
  return declarations;
}

function declarationsInMedia(root, media, selector) {
  const declarations = new Map();
  root.walkAtRules("media", (atRule) => {
    if (atRule.params !== media) return;
    atRule.walkRules((rule) => {
      if (!hasSelector(rule, selector)) return;
      rule.walkDecls((declaration) => {
        declarations.set(declaration.prop, declaration.value);
      });
    });
  });
  return declarations;
}

function hasSelector(rule, selector) {
  return rule.selectors.some((candidate) => candidate.trim() === selector);
}
