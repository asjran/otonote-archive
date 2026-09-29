import base from "@projection-data/unified-search-index.json";
import { activeReleaseContext } from "../lib/release-context";
import { storyLibrary } from "../lib/story-library";
import { itemIndex, skillIndex } from "../lib/game-database";
import { buildPublishedSearchIndex } from "../lib/unified-search-index.mjs";

export const prerender = true;

export function GET() {
  const index = buildPublishedSearchIndex(base, {
    releaseId: activeReleaseContext.contentReleaseId,
    locale: activeReleaseContext.locale,
    library: storyLibrary,
    items: itemIndex,
    skills: skillIndex
  });
  return new Response(JSON.stringify(index), {
    headers: { "Content-Type": "application/json; charset=utf-8" }
  });
}
