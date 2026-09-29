import mediaIndexData from "@projection-data/media-index.json";

export interface MediaVariant {
  url: string;
  width?: number;
  height?: number;
  byteSize?: number;
  sha256?: string;
  mimeType?: string;
}

export interface MediaTier extends Omit<MediaVariant, "url"> {
  // Unavailable tiers have no URL; responsive previews can use variants only.
  url?: string | null;
  state: string;
  activation?: string;
  variants?: MediaVariant[];
}

export interface MediaRecord {
  id: string;
  kind: "image" | "audio" | "video" | "live2d";
  owner?: { kind: string; id: string };
  owners?: Array<{ kind: string; id: string }>;
  tiers: {
    list?: MediaTier;
    poster?: MediaTier;
    webPreview: MediaTier;
    original: MediaTier;
  };
}

interface MediaIndex {
  contentReleaseId: string;
  records: MediaRecord[];
  bySourceUrl: Record<string, string>;
}

export const mediaIndex = mediaIndexData as MediaIndex;
const recordsById = new Map(mediaIndex.records.map((record) => [record.id, record]));
const recordsByOwner = new Map(
  mediaIndex.records.flatMap((record) => {
    const owners = record.owners ?? (record.owner ? [record.owner] : []);
    return owners.map((owner) => [`${owner.kind}:${owner.id}`, record] as const);
  })
);

export function getMediaRecord(id: string | null | undefined): MediaRecord | undefined {
  return id ? recordsById.get(id) : undefined;
}

export function getMediaRecordByOwner(
  kind: string,
  id: string | null | undefined
): MediaRecord | undefined {
  return id ? recordsByOwner.get(`${kind}:${id}`) : undefined;
}

export function getWebPreviewBySourceUrl(
  sourceUrl: string | null | undefined
): string | null {
  if (!sourceUrl) return null;
  return mediaIndex.bySourceUrl[sourceUrl] ?? null;
}
