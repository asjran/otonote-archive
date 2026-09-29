const PAN_THRESHOLD = 6;


export function startCanvasGesture(pointer, viewport) {
  const immediatePan = pointer.button === 1 || (pointer.button === 0 && pointer.altKey);
  if (!pointer.isPrimary || (pointer.button !== 0 && !immediatePan)) return null;
  return {
    pointerId: pointer.pointerId,
    phase: immediatePan ? "panning" : "pending",
    startX: pointer.clientX,
    startY: pointer.clientY,
    viewportX: viewport.x,
    viewportY: viewport.y,
  };
}


export function moveCanvasGesture(gesture, pointer) {
  if (!gesture || pointer.pointerId !== gesture.pointerId) {
    return { gesture, panTo: null };
  }
  const deltaX = pointer.clientX - gesture.startX;
  const deltaY = pointer.clientY - gesture.startY;
  const crossedThreshold = Math.hypot(deltaX, deltaY) > PAN_THRESHOLD;
  const nextGesture = crossedThreshold
    ? { ...gesture, phase: "panning" }
    : gesture;
  return {
    gesture: nextGesture,
    panTo: nextGesture.phase === "panning"
      ? { x: gesture.viewportX + deltaX, y: gesture.viewportY + deltaY }
      : null,
  };
}


export function finishCanvasGesture(gesture, pointer) {
  if (!gesture || pointer.pointerId !== gesture.pointerId) {
    return { handled: false, shouldActivateCanvas: false, didPan: false };
  }
  const didPan = gesture.phase === "panning";
  return {
    handled: true,
    shouldActivateCanvas: !didPan,
    didPan,
  };
}
