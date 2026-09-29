import assert from "node:assert/strict";
import test from "node:test";

import {
  createFormationOptimizerWorkerController
} from "../src/lib/formation-optimizer-worker.mjs";

test("worker returns the same evidence gate result for an unverified profile", async () => {
  const messages = [];
  const worker = createFormationOptimizerWorkerController({
    postMessage: (message) => messages.push(message)
  });

  await worker.handle({
    type: "optimize",
    requestId: "blocked-1",
    payload: {
      members: [],
      supports: [],
      ruleProfile: { verificationStatus: "research", slotCount: 5 },
      exactScores: {}
    }
  });

  assert.deepEqual(messages, [{
    type: "result",
    requestId: "blocked-1",
    result: {
      status: "blocked",
      reason: "formation_rules_not_reconciled",
      results: []
    }
  }]);
});

test("worker executes deterministic fixture scores and reports progress", async () => {
  const messages = [];
  const worker = createFormationOptimizerWorkerController({
    postMessage: (message) => messages.push(message)
  });

  await worker.handle({
    type: "optimize",
    requestId: "fixture-1",
    payload: {
      members: [{ id: "m1", cheapScore: 10 }],
      supports: [{ id: "s1", cheapScore: 2 }],
      ruleProfile: {
        id: "fixture-formation-v1",
        verificationStatus: "reconciled",
        slotCount: 1,
        allowMemberDuplicates: false,
        allowSupportDuplicates: false
      },
      exactScores: { "m1+s1": 123 }
    }
  });

  assert.equal(messages[0].type, "progress");
  assert.equal(messages[1].type, "result");
  assert.equal(messages[1].result.results[0].score, 123);
});

test("worker cancellation is idempotent for unknown and completed requests", async () => {
  const messages = [];
  const worker = createFormationOptimizerWorkerController({
    postMessage: (message) => messages.push(message)
  });

  await worker.handle({ type: "cancel", requestId: "missing" });

  assert.deepEqual(messages, [{
    type: "cancelled",
    requestId: "missing",
    active: false
  }]);
});
