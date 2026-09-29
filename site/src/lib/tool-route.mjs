/** Keep tool links in the current server/language without changing draft data. */
export function toolRoute(path, pathname) {
  const prefix = pathname.match(/^\/(jp|global)\/(zh-CN|zh-TW|ja|en)(?=\/|$)/)?.[0] ?? "";
  return `${prefix}${path}`;
}
