import assert from "node:assert/strict";
import test from "node:test";

import {
  cardDialogHref,
  parseCardDialogState
} from "../src/lib/card-dialog-state.mjs";

test("parses known topic panels and rejects unknown panels", () => {
  assert.deepEqual(parseCardDialogState("?panel=growth"), {
    panel: "growth",
    skillId: null
  });
  assert.deepEqual(parseCardDialogState("?panel=materials"), {
    panel: "materials",
    skillId: null
  });
  assert.deepEqual(parseCardDialogState("?panel=resources"), {
    panel: null,
    skillId: null
  });
  assert.deepEqual(parseCardDialogState("?panel=unknown"), {
    panel: null,
    skillId: null
  });
});

test("skill panel requires a skill that belongs to the current card", () => {
  const availableSkills = ["leader-skill-106", "live-skill-28"];

  assert.deepEqual(
    parseCardDialogState(
      "?panel=skill&skill=live-skill-28",
      availableSkills
    ),
    { panel: "skill", skillId: "live-skill-28" }
  );
  assert.deepEqual(
    parseCardDialogState("?panel=skill&skill=live-skill-99", availableSkills),
    { panel: null, skillId: null }
  );
  assert.deepEqual(parseCardDialogState("?panel=skill", availableSkills), {
    panel: null,
    skillId: null
  });
});

test("serializes dialogs without retaining stale query state", () => {
  assert.equal(cardDialogHref("/cards/members/member-card-1/", "growth"), "/cards/members/member-card-1/?panel=growth");
  assert.equal(
    cardDialogHref(
      "/cards/members/member-card-1/?panel=growth#stats",
      "skill",
      "leader-skill-106"
    ),
    "/cards/members/member-card-1/?panel=skill&skill=leader-skill-106"
  );
  assert.equal(
    cardDialogHref("/cards/members/member-card-1/?panel=growth", null),
    "/cards/members/member-card-1/"
  );
});
