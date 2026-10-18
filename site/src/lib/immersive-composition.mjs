// Compose independently sampled people in the original slot order. Each slot
// retains its own skeleton's bones, constraints, attachments and deform state.
export function composeSpineDrawOrder(environment, members, ownership) {
  return environment.drawOrder.map(slot => {
    const owner = ownership[slot.data.index];
    if (owner === null) return slot;
    const replacement = members.get(owner)?.slots[slot.data.index];
    if (!replacement) throw Error('shared-member-slot-unavailable');
    return replacement;
  });
}

export function pointInTriangle(x, y, ax, ay, bx, by, cx, cy) {
  if (Math.abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) < 1e-8) return false;
  const a = (x - bx) * (ay - by) - (ax - bx) * (y - by);
  const b = (x - cx) * (by - cy) - (bx - cx) * (y - cy);
  const c = (x - ax) * (cy - ay) - (cx - ax) * (y - ay);
  return !([a, b, c].some(v => v < -1e-6) && [a, b, c].some(v => v > 1e-6));
}
