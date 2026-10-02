/** Exact cardinality matching with character capacities and mandatory vertices.
 * Every edge has an already-rounded integer weight. No skill proxy is used. */
export function maximumPairing({ edges, count = 5, required = [], forbidden = [], requiredMembers = [], requiredSupports = [] }) {
  const byKey = new Map(edges.map((e) => [e.key, e]));
  const banned = new Set(forbidden), forced = required.map((key) => byKey.get(key));
  if (forced.some((e) => !e || banned.has(e.key)) || forced.length > count) return null;
  for (const field of ["member", "support", "character"]) if (new Set(forced.map((e) => e[field])).size !== forced.length) return null;
  const used = (field, value) => forced.some((e) => e[field] === value);
  const candidates = edges.filter((e) => !banned.has(e.key) && !used("member", e.member)
    && !used("support", e.support) && !used("character", e.character));
  const needM = new Set(requiredMembers.filter((id) => !used("member", id)));
  const needS = new Set(requiredSupports.filter((id) => !used("support", id)));
  const remaining = count - forced.length;
  if (needM.size > remaining || needS.size > remaining) return null;
  const max = edges.reduce((n, e) => Math.max(n, Math.abs(e.weight)), 0);
  const reward = 2 * count * max + 1;
  if (!Number.isSafeInteger(reward * (2 * count + 1))) throw new Error("Matching weights exceed safe integer range");
  const graph = [], ids = new Map();
  const node = (key) => { if (!ids.has(key)) { ids.set(key, graph.length); graph.push([]); } return ids.get(key); };
  const source = node("source"), sink = node("sink");
  function add(a, b, cost, pair) {
    const edge = { to: b, cost, capacity: 1, reverse: graph[b].length, pair };
    graph[a].push(edge); graph[b].push({ to: a, cost: -cost, capacity: 0, reverse: graph[a].length - 1 });
    return edge;
  }
  const characterNodes = new Map(), memberNodes = new Map(), supportNodes = new Map(), arcs = [];
  for (const e of candidates) {
    if (!Number.isSafeInteger(e.weight)) throw new Error("Pairing weight must be an integer");
    // Allocate each vertex once; card-pair matrices otherwise recreate/hash
    // the same prefixed strings thousands of times in every leader search.
    let c=characterNodes.get(e.character),m=memberNodes.get(e.member),s=supportNodes.get(e.support);
    const newC=c===undefined,newM=m===undefined,newS=s===undefined;
    if(newC){c=node(`c:${e.character}`);characterNodes.set(e.character,c);}
    if(newM){m=node(`m:${e.member}`);memberNodes.set(e.member,m);}
    if(newS){s=node(`s:${e.support}`);supportNodes.set(e.support,s);}
    if(newC)add(source,c,0);
    if(newM)add(c,m,needM.has(e.member)?-reward:0);
    if(newS)add(s,sink,needS.has(e.support)?-reward:0);
    arcs.push(add(m, s, -e.weight, e));
  }
  for (let flow = 0; flow < remaining; flow++) {
    // Shortest augmenting paths on the residual graph. Reverse edges permit
    // replacing an earlier pairing, which is essential for a global optimum.
    const distance = Array(graph.length).fill(Infinity), previous = Array(graph.length), queue = [source];
    const queued = new Set(queue); distance[source] = 0;
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const u = queue[cursor]; queued.delete(u);
      for (const [i, edge] of graph[u].entries()) {
        if (edge.capacity && distance[edge.to] > distance[u] + edge.cost) {
          distance[edge.to] = distance[u] + edge.cost; previous[edge.to] = [u, i];
          if (!queued.has(edge.to)) { queue.push(edge.to); queued.add(edge.to); }
        }
      }
    }
    if (!Number.isFinite(distance[sink])) return null;
    for (let v = sink; v !== source;) {
      const [u, i] = previous[v], edge = graph[u][i];
      edge.capacity--; graph[v][edge.reverse].capacity++; v = u;
    }
  }
  const selected = [...forced, ...arcs.filter((e) => !e.capacity).map((e) => e.pair)];
  if ([...needM].some((id) => !selected.some((e) => e.member === id))
    || [...needS].some((id) => !selected.some((e) => e.support === id))) return null;
  return { edges: selected.sort((a, b) => a.key.localeCompare(b.key)), weight: selected.reduce((s, e) => s + e.weight, 0) };
}

/** Lawler partition: disjoint subspaces cover every solution except this one. */
export function partitionPairing(state, solution) {
  const fixed = new Set(state.required);
  const free = solution.edges.map((e) => e.key).filter((key) => !fixed.has(key));
  return free.map((key, i) => ({ ...state, required: [...state.required, ...free.slice(0, i)],
    forbidden: [...state.forbidden, key] }));
}
