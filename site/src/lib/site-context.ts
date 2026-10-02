import { currentServerContext, withServer } from './game-servers.mjs';

export interface SiteProjection {
  contentReleaseId: string;
  region: "global" | "jp";
  channel: "staging" | "production";
  locale: "zh-CN" | "zh-TW" | "ja" | "en";
  catalogPath: string;
}

const REGION_LOCALE_PRIORITY = {
  jp: ["zh-CN", "en", "ja", "zh-TW"],
  global: ["en", "zh-CN", "zh-TW", "ja"]
} as const;

const ENTITY_DIRECTORY_PATTERNS = [
  [/^\/events\/[^/]+\/$/, "/events/"],
  [/^\/stories\/events\/[^/]+\/$/, "/stories/events/"],
  [/^\/characters\/[^/]+\/$/, "/characters/"],
  [/^\/cards\/members\/[^/]+\/$/, "/cards/members/"],
  [/^\/cards\/supports\/[^/]+\/$/, "/cards/supports/"],
  [/^\/cards\/(?!members\/|supports\/)[^/]+\/$/, "/cards/"],
  [/^\/recruitment\/[^/]+\/$/, "/recruitment/"],
  [/^\/immersive\/[^/]+\/$/, "/immersive/"],
  [/^\/database\/details\/.+\/$/, "/database/"],
  [/^\/music\/music-[^/]+\/$/, "/music/"],
  [/^\/database\/items\/[^/]+\/$/, "/database/items/"],
  [/^\/database\/skills\/[^/]+\/$/, "/database/skills/"],
  [/^\/stories\/chapters\/[^/]+\/$/, "/stories/"],
  [/^\/stories\/episodes\/[^/]+\/$/, "/stories/"],
  [/^\/resources\/[^/]+\/$/, "/resources/"]
] as const;

function normalizedRoute(pathname: string): string {
  const path = pathname.split(/[?#]/, 1)[0] || "/";
  const leading = path.startsWith("/") ? path : `/${path}`;
  return leading.endsWith("/") ? leading : `${leading}/`;
}

export function logicalPath(
  pathname: string,
  projection: SiteProjection
): string {
  const path = normalizedRoute(pathname);
  const prefix = `/${projection.region}/${projection.locale}/`;
  if (!path.startsWith(prefix)) return path;
  const relative = path.slice(prefix.length);
  return relative ? `/${relative}` : "/";
}

export function siteHref(
  path: string,
  projection: SiteProjection
): string {
  if (path.startsWith('/content/') || path.startsWith('/app/')) return path;
  const contentRoot = Reflect.get(globalThis, Symbol.for('ournotes.content-root.v1'));
  if (typeof contentRoot === 'string' && (/^\/(media|gallery|live2d|auto-stage|growth|system-banners|mission-rewards)\//.test(path)
      || /^\/immersive\/.*\.[a-z0-9]+$/i.test(path))) return `${contentRoot}public${path}`;
  const logical = path.startsWith("/") ? path : `/${path}`;
  const href = `/${projection.region}/${projection.locale}${logical}`;
  return withServer(href, currentServerContext().serverId);
}

export function chooseProjection(
  projections: SiteProjection[],
  region: SiteProjection["region"],
  preferredLocale: SiteProjection["locale"]
): SiteProjection | undefined {
  const available = projections.filter((item) => item.region === region);
  if (!available.length) return undefined;
  const priorities = [
    preferredLocale,
    ...REGION_LOCALE_PRIORITY[region].filter(
      (locale) => locale !== preferredLocale
    )
  ];
  for (const locale of priorities) {
    const projection = available.find((item) => item.locale === locale);
    if (projection) return projection;
  }
  return undefined;
}

export function switchTarget(
  pathname: string,
  current: SiteProjection,
  target: SiteProjection
): string {
  const logical = logicalPath(pathname, current);
  const sameRelease =
    current.contentReleaseId === target.contentReleaseId &&
    current.region === target.region &&
    current.channel === target.channel;
  if (sameRelease) return siteHref(logical, target);

  for (const [pattern, directory] of ENTITY_DIRECTORY_PATTERNS) {
    if (pattern.test(logical)) {
      const url = new URL(siteHref(directory, target), 'https://ournotes.invalid');
      url.searchParams.set('unavailable', logical);
      return url.pathname + url.search;
    }
  }
  return siteHref(logical, target);
}

export type ProjectionRouteMode = "single" | "matrix";

export function projectionSwitchHref(
  pathname: string,
  current: SiteProjection,
  target: SiteProjection,
  mode: ProjectionRouteMode
): string | null {
  if (mode === "matrix") {
    return switchTarget(pathname, current, target);
  }
  const isCurrentProjection =
    current.contentReleaseId === target.contentReleaseId &&
    current.region === target.region &&
    current.channel === target.channel &&
    current.locale === target.locale;
  return isCurrentProjection ? logicalPath(pathname, current) : null;
}

export function displayedLocale(
  _requestedLocale: SiteProjection["locale"],
  projectedLocale: SiteProjection["locale"]
): SiteProjection["locale"] {
  return projectedLocale;
}
