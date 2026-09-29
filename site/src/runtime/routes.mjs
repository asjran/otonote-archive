export function routeParams(pattern, route) {
  const names = [];
  const expression = pattern.split('/').map(part => {
    const dynamic = part.match(/^\[(\.\.\.)?([^\]]+)\]$/);
    if (dynamic) { names.push(dynamic[2]); return dynamic[1] ? '(.+)' : '([^/]+)'; }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('/');
  const match = route.replace(/\/$/, '').match(new RegExp('^' + expression.replace(/\/$/, '') + '$'));
  return match ? Object.fromEntries(names.map((name, i) => [name, decodeURIComponent(match[i + 1])])) : null;
}
