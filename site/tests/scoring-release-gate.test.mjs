import test from "node:test";
import assert from "node:assert/strict";
import { scoringRulesAvailable } from "../src/lib/scoring-release-gate.mjs";

test("a remote content release cannot inherit the previous release's code audit", () => {
  const rules = { sourceReleaseId: "audited-release", verificationStatus: "code_audited" };
  assert.equal(scoringRulesAvailable(rules, "remote-hotfix-release"), false);
  assert.equal(scoringRulesAvailable(rules, "audited-release"), true);
});

test("matching labels without an audit do not enable calculation", () => {
  assert.equal(scoringRulesAvailable({ sourceReleaseId: "new", verificationStatus: "pending" }, "new"), false);
  assert.equal(scoringRulesAvailable(null, "new"), false);
});

test('reference estimates require both current content and the original native identity', () => {
  const rules = {sourceReleaseId:'current', verificationStatus:'reference_compatible', nativeSha256:'hash',
    native:{sourceReleaseId:'baseline',nativeSha256:'hash'},
    referenceProfile:{sourceReleaseId:'baseline',nativeSha256:'hash',dataCompatibility:'scoring_tables_matched',currentGameplayVerified:false}};
  assert.equal(scoringRulesAvailable(rules,'current'),true);
  assert.equal(scoringRulesAvailable(rules,'other'),false);
  assert.equal(scoringRulesAvailable({...rules,referenceProfile:undefined},'current'),false);
  assert.equal(scoringRulesAvailable({...rules,native:{...rules.native,sourceReleaseId:'current'}},'current'),false);
  assert.equal(scoringRulesAvailable({...rules,nativeSha256:'changed'},'current'),false);
});
