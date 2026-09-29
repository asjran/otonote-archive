import gameModeData from "@projection-data/game-modes.json";
import { validateArtifact } from "./artifact-contracts";

export interface ModeEvidence {
  table: string;
  rowCount: number;
}

export interface ModeMetric {
  label: string;
  value: number;
}

export interface GameModeDefinition {
  id: "battle-live" | "gekisou";
  name: string;
  masterName: string;
  aliases: string[];
  description: string;
  status: "archive_available";
  capabilities: {
    archive: boolean;
    autoDemo: boolean;
    offlineSimulation: boolean;
    onlineMultiplayer: boolean;
  };
  metrics: ModeMetric[];
  rewardSummary: {
    rowCount: number;
    groupCount: number;
    rankCount: number;
  };
  evidence: ModeEvidence[];
  evidenceRowCount: number;
  blockers: string[];
}

export interface EventCapabilityRecord {
  definitionCount: number;
  instanceRoutesEnabled: boolean;
  orphanAuxiliaryRowCount: number;
  capabilities: {
    hasStory: boolean;
    hasMode: boolean;
    hasRewards: boolean;
    hasRanking: boolean;
  };
  evidence: ModeEvidence[];
  status: string;
}

export interface GameModeDatabase {
  schemaVersion: 1;
  sourceReleaseId: string;
  modes: GameModeDefinition[];
  events: EventCapabilityRecord;
}

export const gameModeDatabase = validateArtifact<GameModeDatabase>(
  "game-modes.json",
  gameModeData,
  {
    schemaVersion: 1,
    fields: {
      sourceReleaseId: "string",
      modes: "array",
      "modes[]": "object",
      "modes[].id": "string",
      "modes[].capabilities": "object",
      "modes[].metrics": "array",
      "modes[].evidence": "array",
      events: "object",
      "events.capabilities": "object",
      "events.evidence": "array"
    }
  }
);

const modesById: ReadonlyMap<string, GameModeDefinition> = new Map(
  gameModeDatabase.modes.map((mode) => [mode.id, mode])
);

export function getGameMode(id: string): GameModeDefinition | undefined {
  return modesById.get(id);
}
