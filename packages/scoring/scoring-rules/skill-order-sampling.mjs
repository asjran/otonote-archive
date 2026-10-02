const permutations = xs => xs.length ? xs.flatMap((x, i) => permutations(xs.filter((_, j) => i !== j)).map(p => [x, ...p])) : [[]];
const full = permutations([0, 1, 2, 3, 4]);
// Ten deterministic orders: each slot appears twice at each activation position.
// This is a screening estimate, never a replacement for the final 120 orders.
const screen = [1, -1].flatMap(direction => Array.from({ length: 5 }, (_, start) =>
  Array.from({ length: 5 }, (_, i) => (start + direction * i + 5) % 5)));
export function skillOrdersFor(precision = 'full') {
  if (!['full', 'screen'].includes(precision)) throw new Error('Invalid score precision');
  return (precision === 'full' ? full : screen).map(order => [...order]);
}
