import {serializeTeamDraftSearch} from './team-draft.mjs';

/** Keep tool links in the current server/language without changing draft data. */
export function toolRoute(path, pathname) {
  const prefix = pathname.match(/^\/(jp|global)\/(zh-CN|zh-TW|ja|en)(?=\/|$)/)?.[0] ?? "";
  return `${prefix}${path}`;
}
/** Fragments remain in the browser, so large drafts cannot exceed gateway request limits. */
export function toolNavigationHref(path, draft, current = globalThis.location) {
  const url = new URL(toolRoute(path, current.pathname), current.href);
  const server = new URLSearchParams(current.search).get('server');
  if (server) url.searchParams.set('server', server);
  url.hash = new URLSearchParams({'team-draft':serializeTeamDraftSearch(draft)}).toString();
  return url.pathname + url.search + url.hash;
}
