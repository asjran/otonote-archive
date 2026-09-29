import assert from "node:assert/strict";
import test from "node:test";

import {
  finishCanvasGesture,
  moveCanvasGesture,
  startCanvasGesture,
} from "../src/lib/anontokyo-studio-pointer-gesture.mjs";


test("ordinary primary-button drag pans from the original viewport after crossing six pixels", () => {
  const started = startCanvasGesture({
    pointerId: 4,
    pointerType: "mouse",
    isPrimary: true,
    button: 0,
    altKey: false,
    clientX: 120,
    clientY: 80,
  }, { x: 300, y: 140 });

  const moved = moveCanvasGesture(started, {
    pointerId: 4,
    clientX: 127,
    clientY: 80,
  });

  assert.equal(moved.gesture.phase, "panning");
  assert.deepEqual(moved.panTo, { x: 307, y: 140 });
});


test("movement at the six-pixel threshold remains a canvas click", () => {
  const started = startCanvasGesture({
    pointerId: 9,
    pointerType: "mouse",
    isPrimary: true,
    button: 0,
    altKey: false,
    clientX: 30,
    clientY: 40,
  }, { x: 200, y: 100 });
  const moved = moveCanvasGesture(started, {
    pointerId: 9,
    clientX: 36,
    clientY: 40,
  });

  assert.equal(moved.gesture.phase, "pending");
  assert.equal(moved.panTo, null);
  assert.deepEqual(
    finishCanvasGesture(moved.gesture, { pointerId: 9 }),
    { handled: true, shouldActivateCanvas: true, didPan: false },
  );
});


test("middle mouse and Alt plus primary button start immediate panning", () => {
  for (const pointer of [
    { button: 1, altKey: false },
    { button: 0, altKey: true },
  ]) {
    const started = startCanvasGesture({
      pointerId: 2,
      pointerType: "mouse",
      isPrimary: true,
      clientX: 50,
      clientY: 60,
      ...pointer,
    }, { x: 10, y: 20 });

    assert.equal(started.phase, "panning");
    assert.deepEqual(
      finishCanvasGesture(started, { pointerId: 2 }),
      { handled: true, shouldActivateCanvas: false, didPan: true },
    );
  }
});


test("primary touch uses the same drag threshold", () => {
  const started = startCanvasGesture({
    pointerId: 13,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    altKey: false,
    clientX: 80,
    clientY: 100,
  }, { x: 0, y: 0 });
  const moved = moveCanvasGesture(started, {
    pointerId: 13,
    clientX: 85,
    clientY: 105,
  });

  assert.equal(moved.gesture.phase, "panning");
  assert.deepEqual(moved.panTo, { x: 5, y: 5 });
});


test("unrelated and unsupported pointers cannot change or finish the active gesture", () => {
  const started = startCanvasGesture({
    pointerId: 7,
    pointerType: "mouse",
    isPrimary: true,
    button: 0,
    altKey: false,
    clientX: 10,
    clientY: 10,
  }, { x: 90, y: 40 });

  assert.deepEqual(
    moveCanvasGesture(started, { pointerId: 8, clientX: 30, clientY: 30 }),
    { gesture: started, panTo: null },
  );
  assert.deepEqual(
    finishCanvasGesture(started, { pointerId: 8 }),
    { handled: false, shouldActivateCanvas: false, didPan: false },
  );
  assert.equal(startCanvasGesture({
    pointerId: 10,
    pointerType: "mouse",
    isPrimary: true,
    button: 2,
    altKey: false,
    clientX: 0,
    clientY: 0,
  }, { x: 0, y: 0 }), null);
});
