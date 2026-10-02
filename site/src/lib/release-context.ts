import releaseIndexData from "@projection-data/release-index.json";
import { validateArtifact } from "./artifact-contracts";

export type Region = "global" | "jp";
export type Channel = "staging" | "production";
export type Locale = "zh-CN" | "zh-TW" | "ja" | "en";

export interface ReleaseProjection {
  contentReleaseId: string;
  region: Region;
  channel: Channel;
  locale: Locale;
  catalogPath: string;
}

export interface ReleaseIndex {
  schemaVersion: 1;
  active: ReleaseProjection;
  projections: ReleaseProjection[];
}

export const releaseIndex = validateArtifact<ReleaseIndex>(
  "release-index.json",
  releaseIndexData,
  {
    schemaVersion: 1,
    fields: {
      active: "object",
      "active.contentReleaseId": "string",
      "active.region": "string",
      "active.channel": "string",
      "active.locale": "string",
      "active.catalogPath": "string",
      projections: "array",
      "projections[]": "object",
      "projections[].contentReleaseId": "string",
      "projections[].region": "string",
      "projections[].channel": "string",
      "projections[].locale": "string",
      "projections[].catalogPath": "string"
    }
  }
);
export const activeReleaseContext = releaseIndex.active;

export function projectionsForServer(
  region: Region,
  channel: Channel
): ReleaseProjection[] {
  return releaseIndex.projections.filter(
    (projection) =>
      projection.region === region && projection.channel === channel
  );
}

export function switchLocale(
  current: ReleaseProjection,
  locale: Locale
): ReleaseProjection | undefined {
  return releaseIndex.projections.find(
    (projection) =>
      projection.contentReleaseId === current.contentReleaseId &&
      projection.region === current.region &&
      projection.channel === current.channel &&
      projection.locale === locale
  );
}
