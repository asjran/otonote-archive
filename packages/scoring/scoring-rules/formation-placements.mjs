const permutations = xs => xs.length ? xs.flatMap((x,i) => permutations(xs.filter((_,j) => i!==j)).map(p => [x,...p])) : [[]];
const orders = permutations([0,1,3,4]);
export function gekisouPlacements(draft) {
  return orders.map(order => {
    const slots = draft.slots.slice();
    [0,1,3,4].forEach((slot,i) => { slots[slot] = draft.slots[order[i]]; });
    return {...draft,slots};
  });
}
