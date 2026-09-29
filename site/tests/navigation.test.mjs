import assert from "node:assert/strict";
import test from "node:test";
import { NAVIGATION_GROUPS, activeNavigationGroup, navigationRoutes } from "../src/lib/navigation.mjs";

test("V1 includes galleries and the immersive scene while legacy media archives stay closed", () => {
  assert.deepEqual(NAVIGATION_GROUPS.map(g => g.id), ["missions", "recruitment", "events", "catalog", "music", "immersive", "comics", "stamps", "decorations", "stories", "tools"]);
  const routes = navigationRoutes();
  for (const path of ["/events/", "/characters/", "/cards/members/", "/cards/supports/", "/database/skills/", "/music/", "/tools/deck-builder/"]) assert.ok(routes.includes(path));
  assert.ok(routes.includes("/stories/"));
  assert.ok(routes.includes("/immersive/"));
  assert.ok(routes.every(path => !path.includes("high-score-rating") && !path.includes("game-modes")));
  assert.ok(routes.every(path => !/^\/(resources|anontokyo)\//.test(path)));
  assert.equal(routes.length, new Set(routes).size);
});
test("nested data and tool routes retain their correct navigation context", () => {
  for (const path of ["/cards/supports/support-1/", "/database/skills/skill-1/"]) assert.equal(activeNavigationGroup(path), "catalog");
  assert.equal(activeNavigationGroup("/tools/deck-builder/"), "tools");
  assert.equal(activeNavigationGroup("/game-modes/gekisou/"), undefined);
  assert.equal(activeNavigationGroup("/events/"), "events");
  assert.equal(activeNavigationGroup("/missions/"), "missions");
  assert.equal(activeNavigationGroup("/immersive/"), "immersive");
  assert.equal(activeNavigationGroup("/recruitment/1/"), "recruitment");
  assert.equal(activeNavigationGroup("/stories/episodes/story-entry-main-101/"), "stories");
  assert.equal(activeNavigationGroup("/"), "home");
});
