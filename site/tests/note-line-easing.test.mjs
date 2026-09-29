import assert from "node:assert/strict";
import test from "node:test";

import {
  applyNoteLineEasing,
  interpolateLongPathNode,
  sampleLongPathNodes
} from "../src/lib/note-line-easing.mjs";

test("matches the game client's linear, ease-out and ease-in note-line curves", () => {
  assert.equal(applyNoteLineEasing("linear", 0.5), 0.5);
  assert.equal(applyNoteLineEasing("out", 0.5), 0.75);
  assert.equal(applyNoteLineEasing("in", 0.5), 0.25);
});

test("uses the left control node easing for each long-note segment", () => {
  const nodes = [
    { time: 0, position: 0, size: 4, easing: "out", visible: true },
    { time: 1, position: 12, size: 8, easing: "in", visible: false },
    { time: 2, position: 24, size: 4, easing: "linear", visible: true }
  ];

  assert.deepEqual(interpolateLongPathNode(nodes, 0.5), {
    time: 0.5,
    position: 9,
    size: 7,
    visible: false,
    easing: "out",
    easingRight: "out"
  });
  assert.deepEqual(interpolateLongPathNode(nodes, 1.5), {
    time: 1.5,
    position: 15,
    size: 7,
    visible: false,
    easing: "in",
    easingRight: "in"
  });
  assert.equal(sampleLongPathNodes(nodes).length, 25);
});

test("uses independent left and right easing for asymmetric slide edges", () => {
  const point = interpolateLongPathNode(
    [
      {
        time: 0,
        position: 0,
        size: 4,
        easing: "out",
        easingRight: "linear",
        visible: true
      },
      { time: 1, position: 12, size: 8, visible: true }
    ],
    0.5
  );

  assert.equal(point.position, 9);
  assert.equal(point.size, 3);
  assert.equal(point.easingRight, "linear");
});
