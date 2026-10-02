import type {EditionRecord} from "./catalog";
import type { GachaPool, MissionGroup } from "./global-systems";
export interface EventReward {
  rewardId?: number;
  imagePath?: string | null;
  resourceType: number | null;
  resourceId: number | null;
  count: number | null;
  name: string;
  resolved: boolean;
  rarity: number | null;
}
export interface EventRankingReward {
  id: number;
  rankStart: number | null;
  rankEnd: number | null;
  rewards: EventReward[];
}
export interface EventDefinition extends EditionRecord {
  id: number;
  edition: string;
  sourceReleaseId: string;
  name: string;
  nameLocale: string | null;
  mode: string;
  assets?: { image?: string | null; logo?: string | null; background?: string | null; banner?: string | null };
  schedule: { startAt: string | null; endAt: string | null; displayEndAt: string | null; timeZone: string | null; status: string };
  achievements: { id: number; points: number | null; rewards: EventReward[] }[];
  loopRewards: { id: number; startPoints: number | null; intervalPoints: number | null; rewards: EventReward[] }[];
  effects: { id: number; bonusType: number; bonusKind: string; targetNames: string[];
    constraints: Record<string, number | null>; rankValues: (number | null)[]; valueUnit: string }[];
  pickupCards: EventReward[];
  challengeSongs: { id: number; musicId: number; name: string; attributeCode?: number | null; gekisouMissionTypes?: (number | null)[]; startAt: string | null; endAt: string | null; rankingRewards: EventRankingReward[] }[];
  challengeRules?: {
    consumptionOptions: { cost: number | null; pointRate: number | null; rewardRate: number | null }[];
    normalLiveChallengePoints: { scoreRank: number; scoreRankLabel: string; value: number | null }[];
  };
  pointRules: Record<string, { points: { scoreRank: number; scoreRankLabel: string; value: number | null }[];
    rewards: { scoreRank: number; scoreRankLabel: string; group: number; probabilityRaw: number; reward: EventReward }[] }>;
  story: { chapterId: number | null; name: string | null; bandId?: number | null; characterIds?: number[]; episodes: { id: number; number: number; name: string; description?: string; requiredPoints: number | null; isAnotherEpisode: boolean; isExtraEpisode: boolean }[] };
  related?: { recruitment: GachaPool[]; missions: MissionGroup[]; passes: EventPass[] };
  eventItem: EventReward | null;
  exchanges: { id: number; name: string; startAt: string | null; endAt: string | null;
    products: { id: number; reward: EventReward; cost: number | null; limit: number | null; resetType: number | null;
      paymentSteps: number[]; paymentStepResourceCounts: number[]; startAt: string | null; endAt: string | null }[] }[];
  ranking: { configured: { eventPoints: boolean | null; music: boolean | null; totalMusic: boolean | null }; liveDataStatus: string; rewards: EventRankingReward[] };
}
export interface EventArchiveData {
  definitionCount: number;
  edition?: string | null;
  sourceReleaseId?: string;
  records?: EventDefinition[];
  warnings?: string[];
}

export interface EventMedia { image?: string; artwork?: string; href?: string; label?: string }
export type EventMediaMap = Record<string, EventMedia>;
export interface EventIdentity {
  bands: { name: string; image?: string; bonus: boolean }[];
  characters: { name: string; image?: string }[];
  attributes: number[];
}
export interface EventCard extends EventReward {
  bonus: boolean;
  sources: { kind: 'points' | 'exchange' | 'ranking'; points?: number | null; cost?: number | null; count?: number | null; limit?: number | null }[];
}

export interface EventPass {
  id: number; name: string; startAt: string | null; endAt: string | null;
  relationStatus: string; missions: MissionGroup[];
  levels: { level: number; points: number | null; free: EventReward[]; premium: EventReward[] }[];
}
