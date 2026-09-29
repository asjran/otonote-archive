import type {
  CardDetailProjection,
  GrowthProfile,
  SkillDefinition
} from "./game-database";
import type { MemberCard, SupportCard } from "./catalog";

export interface GrowthState {
  level: number;
  rank: number;
  awake: number;
  skillLevels: Record<string, number>;
}

export interface MaterialAmount {
  itemId: string;
  amount: number;
}

export interface MaterialAxis {
  key: string;
  usageKind: string;
  currentStage: number;
  maxStage: number;
  nextStage: number | null;
  next: MaterialAmount[];
  remaining: MaterialAmount[];
}

export interface GrowthSnapshot {
  state: GrowthState;
  maxLevel: number;
  power: {
    performance: number;
    technic: number;
    visual: number;
    total: number;
    accuracy: "verified";
  };
  bonuses: {
    leaderSkillLevel: number;
    musicTypeBonusRate: number;
    musicTagBonusRate: number;
    cardTypeLinkBonusRate: number;
  };
  exp: {
    current: number;
    toCurrentCap: number;
    toFinalCap: number;
  };
  materialAxes: MaterialAxis[];
  effectiveSkills: Array<{
    skillId: string;
    slot: string;
    level: number | null;
    name: string;
    iconAssetId: string | null;
    renderedSummary: string;
  }>;
  projection: CardDetailProjection;
}

export function createGrowthSnapshot(input: {
  card: MemberCard | SupportCard;
  profile: GrowthProfile;
  projection: CardDetailProjection;
  skills?: SkillDefinition[];
  state: GrowthState;
}): GrowthSnapshot;

export function maximumGrowthState(profile: GrowthProfile, skills?: SkillDefinition[]): GrowthState;
