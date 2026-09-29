import bandItemData from "@projection-data/band-items.json";
import { validateArtifact } from "./artifact-contracts";

export type BandItemInterpretationStatus = "identified" | "partial";

export interface BandItemEffect {
  sourceEffectId: number;
  effectType: number;
  effectName: string;
  rawValue: number;
  displayValue: string;
  targetMasterIds: number[];
  targetBandIds: string[];
  interpretationStatus: BandItemInterpretationStatus;
}

export interface BandItemLevel {
  level: number;
  playerRank: number;
  renderedSummary: string;
  effects: BandItemEffect[];
  upgradeMaterials: {
    itemId: string;
    name: string;
    amount: number;
    previewUrl: string | null;
    sourceResourceId: number;
  }[] | null;
}

export interface BandItemDefinition {
  id: string;
  masterId: number;
  name: string;
  descriptionTemplate: string;
  bandId: string;
  bandName: string;
  resourceGroupId: number;
  displayOrder: number;
  assetId: string | null;
  previewUrl: string | null;
  containerPath: string;
  catalogStatus: "identified" | "missing_asset";
  levels: BandItemLevel[];
  interpretationStatus: BandItemInterpretationStatus;
  sourceReleaseIds: string[];
}

export interface BandItemBand {
  id: string;
  masterId: number;
  name: string;
  mainColor: string;
  subColor: string;
  itemIds: string[];
}

export interface BandItemDatabase {
  schemaVersion: 1;
  sourceReleaseId: string;
  bands: BandItemBand[];
  items: BandItemDefinition[];
  quality: {
    bandCount: number;
    itemCount: number;
    levelCount: number;
    effectCount: number;
    missingAssetCount: number;
    partialItemCount: number;
    warnings: string[];
  };
}

export const bandItemDatabase = validateArtifact<BandItemDatabase>(
  "band-items.json",
  bandItemData,
  {
    schemaVersion: 1,
    fields: {
      sourceReleaseId: "string",
      bands: "array",
      "bands[]": "object",
      "bands[].id": "string",
      "bands[].itemIds": "array",
      items: "array",
      "items[]": "object",
      "items[].id": "string",
      "items[].levels": "array",
      quality: "object",
      "quality.warnings": "array"
    }
  }
);

const itemsById = new Map(
  bandItemDatabase.items.map((item) => [item.id, item])
);

export function getBandItem(
  id: string | null | undefined
): BandItemDefinition | undefined {
  return id ? itemsById.get(id) : undefined;
}

export function getBandItemsForBand(bandId: string): BandItemDefinition[] {
  return bandItemDatabase.items.filter((item) => item.bandId === bandId);
}
