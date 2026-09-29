import { SITE_NAME } from "./site-brand.mjs";
import catalogData from "@projection-data/catalog.json";
import { validateArtifact } from "./artifact-contracts";

export interface Release {
  id: string;
  region: "global";
  channel: string;
  locale: "zh-CN" | "zh-TW" | "ja" | "en";
  packageName: string;
  versionName: string;
  versionCode: number;
  unityVersion: string;
  label: string;
}

export interface Asset {
  id: string;
  displayName: string;
  kind:
    | "character"
    | "card"
    | "background"
    | "banner"
    | "cover"
    | "logo"
    | "item"
    | "skill"
    | "card_taxonomy"
    | "band_logo"
    | "other";
  objectType: string;
  width: number;
  height: number;
  byteSize: number;
  sha256: string;
  sourcePath: string;
  sourceBundle: string;
  sourceObjectId: string;
  containerPath: string;
  sourceReleaseId: string;
  catalogStatus: "identified" | "archive_only" | "source_placeholder" | "pending";
  publicPolicy: "public" | "archive_only" | "not_public" | "review_required";
  classificationReason: string;
  classificationEvidence: string;
  classificationConfidence: number;
  downloadPolicy: "preview_and_download" | "preview_only" | "private";
  previewUrl: string;
  thumbnailUrl?: string;
  originalUrl: string;
}

export interface Band {
  id: string;
  masterId: number;
  displayName: string;
  localizedText: Partial<Record<"zh-CN" | "zh-TW" | "ja" | "en", string>>;
  description: string;
  mainColor: string;
  subColor: string;
  logoAssetId: string;
  whiteLogoAssetId: string;
  characterIds: string[];
  sourceReleaseIds: string[];
  catalogStatus: "identified";
}

export interface CardAttributeDefinition {
  code: number;
  names: Record<"zh-CN" | "zh-TW" | "ja" | "en", string>;
  color: string;
  iconAssetId: string;
}

export interface CardRarityDefinition {
  code: number;
  label: "R" | "SR" | "SSR" | "BD" | "EX";
  iconAssetId: string;
}

export interface CardTaxonomy {
  attributes: CardAttributeDefinition[];
  rarities: CardRarityDefinition[];
  growthIcons: {
    memberLevel: string;
    supportLevel: string;
    rank: string;
    awake: string;
    awakeBase: string;
  };
}

export interface Character {
  id: string;
  masterId: number;
  displayName: string;
  localizedText: Partial<Record<"zh-CN" | "zh-TW" | "ja" | "en", string>>;
  shortName: string;
  aliases: string[];
  bandId: string;
  role: string;
  profile: {
    voiceActor: string;
    description: string;
    catchphrase: string;
    bloodType: string;
    height: string;
    constellation: string;
    school: string;
    schoolClass: string;
    favoriteFood: string;
    hobby: string;
  };
  birthday: {
    month: number;
    day: number;
  };
  mainColor: string;
  subColor: string;
  profileAssetId: string | null;
  portraitAssetIds: string[];
  memberCardIds: string[];
  featuredSupportCardIds: string[];
  sourceReleaseIds: string[];
  catalogStatus: "identified" | "missing_asset";
  sourceBundle: string;
}

export interface MemberCard {
  id: string;
  legacyId: string | null;
  masterId: number;
  assetId: number;
  displayName: string;
  localizedText: Partial<Record<"zh-CN" | "zh-TW" | "ja" | "en", string>>;
  name: string;
  subtitle: string;
  characterId: string;
  rarity: number;
  attributeCode: number;
  performancePowerMax: number;
  technicPowerMax: number;
  visualPowerMax: number;
  leaderSkillId: number;
  liveSkillId: number;
  startAt: string;
  primaryAssetId: string | null;
  variantAssetIds: string[];
  thumbnailAssetId: string | null;
  sourceReleaseIds: string[];
  catalogStatus: "identified" | "missing_asset";
  sourceBundle: string;
  sourceContainerPath: string;
}

export interface SupportCard {
  id: string;
  masterId: number;
  assetId: number;
  displayName: string;
  localizedText: Partial<Record<"zh-CN" | "zh-TW" | "ja" | "en", string>>;
  name: string;
  description: string;
  diary?: string;
  featuredCharacterIds: string[];
  rarity: number;
  attributeCode: number;
  performancePowerMax: number;
  technicPowerMax: number;
  visualPowerMax: number;
  supportSkillIds: number[];
  startAt: string;
  primaryAssetId: string | null;
  variantAssetIds: string[];
  thumbnailAssetId: string | null;
  sourceReleaseIds: string[];
  catalogStatus: "identified" | "missing_asset";
  sourceBundle: string;
  sourceContainerPath: string;
}

export type MusicDifficulty = "easy" | "normal" | "hard" | "expert";

export interface MusicRewardEntry {
  resourceType: number;
  resourceId: number;
  resourceCount: number;
}

export interface MusicTrack {
  id: string;
  masterId: number;
  title: string;
  phoneticTitle: string;
  rubyTitle: string;
  sortOrder: number;
  bandIds: string[];
  bandLabels: string[];
  vocalCharacterIds: string[];
  vocalistLabels: string[];
  musicType: number;
  musicTypeLabel: string;
  categoryIds: number[];
  categoryLabels: string[];
  tagIds: number[];
  tagLabels: string[];
  lyricist: string;
  composer: string;
  arranger: string;
  startAt: string;
  jacketAssetId: string | null;
  chartIds: string[];
  musicSoundId: number;
  jingleSoundId: number;
  audioStatus: "missing" | "available";
  audioPlayback: boolean;
  audioDownload: boolean;
  audioUrl: string | null;
  audioDuration: number | null;
  audioCodec: "aac" | null;
  maxLevel: number;
  expertNoteCount: number;
  bpm: { min: number; max: number };
  hasCompleteCharts: boolean;
  gekisouMissions: Array<{
    index: 1 | 2 | 3;
    typeCode: 1 | 2 | 3;
    type: "combo" | "luck" | "just";
    label: "COMBO" | "LUCK" | "JUST";
    sourceField:
      | "_gekisouMission1"
      | "_gekisouMission2"
      | "_gekisouMission3";
    evidenceStatus: "confirmed-data";
  }>;
  soloRewards: {
    scoreRanks: Array<{ rank: number; requiredScore: number }>;
    scoreRewards: Array<{
      liveScoreRank: number;
      requiredScore: number;
      entry: MusicRewardEntry;
    }>;
    comboRewards: Array<{
      difficulty: MusicDifficulty;
      comboRateType: number;
      entry: MusicRewardEntry;
    }>;
  };
  sourceReleaseIds: string[];
  catalogStatus: "identified" | "missing_asset";
  relationStatus: "identified" | "partial";
}

export interface MusicChart {
  id: string;
  masterId: number;
  trackId: string;
  difficulty: MusicDifficulty;
  level: number;
  displayLevel: number;
  fullComboCount: number;
  judgementCount: number;
  judgementCountSource: "client-runtime-reconstruction";
  sourceJudgementCount: number;
  masterFullComboCount: number;
  fullComboDelta: number;
  fullComboClassification: "MATCH" | "RUNTIME_HIGHER" | "RUNTIME_LOWER";
  fullComboStatus: "match" | "conflict";
  runtimeAlgorithmVersion: string;
  explicitJudgementCount: number;
  slideComboCandidateCount: number;
  skippedSlideComboCount: number;
  mergedEndpointReduction: number;
  guidePathCount: number;
  autoControlNodeCount: number;
  scoreLogicalPath: string;
  duration: number;
  bpm: { min: number; max: number };
  noteCounts: { tap: number; flick: number; trace: number; long: number };
  averageDensity: number;
  peakDensity: number;
  skillCount: number;
  feverCount: number;
  analysisDataUrl: string;
  sourceReleaseIds: string[];
  catalogStatus: "identified";
}

export interface Module {
  id: string;
  displayName: string;
  status: "reserved" | "preview" | "published";
  route: string;
}

export interface Editorial {
  siteTitle: string;
  siteSubtitle: string;
  heroEyebrow: string;
  heroTitle: string;
  heroDescription: string;
  notice: string;
}

export interface Catalog {
  schemaVersion: 6;
  generatedAt: string;
  release: Release;
  projectionContext: {
    contentReleaseId: string;
    region: "global";
    channel: "staging" | "production";
    locale: "zh-CN" | "zh-TW" | "ja" | "en";
  };
  editorial: Editorial;
  cardTaxonomy: CardTaxonomy;
  modules: Module[];
  bands: Band[];
  characters: Character[];
  memberCards: MemberCard[];
  supportCards: SupportCard[];
  musicTracks: MusicTrack[];
  musicCharts: MusicChart[];
  entityVariants: Array<{
    variantRef: string;
    entityType: string;
    region: "global";
    channel: "staging" | "production";
    sourceMasterId: string;
    firstSeenContentRelease: string;
    lastSeenContentRelease: string;
    availability: string;
    localizedText: Partial<
      Record<"zh-CN" | "zh-TW" | "ja" | "en", string>
    >;
    assetRelations: string[];
    sourceEvidence: string[];
  }>;
  canonicalEntities: Array<{
    id: string;
    variantRefs: string[];
    evidence: Array<{ kind: string; value: string }>;
  }>;
  publicationPolicy: {
    music: {
      enabled: boolean;
      audioPlayback: boolean;
      audioDownload: boolean;
      scoreExport: boolean;
    };
    characterMedia: {
      enabled: boolean;
      audioPlayback: boolean;
      audioDownload: boolean;
      live2dPlayback: boolean;
    };
  };
  story: {
    chapterCount: number;
    entryCount: number;
    entriesByKind: Record<string, number>;
    advStateCounts: Record<string, number>;
    availableAdvCount: number;
  };
  characterMedia: {
    costumeCount: number;
    voiceCount: number;
    talkCount: number;
    friendshipCount: number;
    liveDialogueCount: number;
    mediaItemCount: number;
    voiceStateCounts: Record<string, number>;
    talkStateCounts: Record<string, number>;
    capabilityCounts: Record<string, number>;
  };
  assets: Asset[];
}

export const catalog = validateArtifact<Catalog>("catalog.json", catalogData, {
  schemaVersion: 6,
  fields: {
    generatedAt: "string",
    release: "object",
    "release.id": "string",
    "release.region": "string",
    "release.channel": "string",
    "release.locale": "string",
    projectionContext: "object",
    "projectionContext.contentReleaseId": "string",
    "projectionContext.region": "string",
    "projectionContext.channel": "string",
    "projectionContext.locale": "string",
    editorial: "object",
    cardTaxonomy: "object",
    modules: "array",
    bands: "array",
    "bands[]": "object",
    "bands[].id": "string",
    characters: "array",
    "characters[]": "object",
    "characters[].id": "string",
    memberCards: "array",
    supportCards: "array",
    musicTracks: "array",
    musicCharts: "array",
    entityVariants: "array",
    canonicalEntities: "array",
    publicationPolicy: "object",
    story: "object",
    characterMedia: "object",
    assets: "array",
    "assets[]": "object",
    "assets[].id": "string"
  }
});

const assetsById = new Map(catalog.assets.map((asset) => [asset.id, asset]));
const bandsById = new Map(catalog.bands.map((band) => [band.id, band]));
const charactersById = new Map(
  catalog.characters.map((character) => [character.id, character])
);
const memberCardsById = new Map(
  catalog.memberCards.map((card) => [card.id, card])
);
const supportCardsById = new Map(
  catalog.supportCards.map((card) => [card.id, card])
);
const musicTracksById = new Map(
  catalog.musicTracks.map((track) => [track.id, track])
);
const musicChartsById = new Map(
  catalog.musicCharts.map((chart) => [chart.id, chart])
);
const attributesByCode = new Map(
  catalog.cardTaxonomy.attributes.map((attribute) => [
    attribute.code,
    attribute
  ])
);
const raritiesByCode = new Map(
  catalog.cardTaxonomy.rarities.map((rarity) => [rarity.code, rarity])
);

export function getAsset(id: string | null | undefined): Asset | undefined {
  return id ? assetsById.get(id) : undefined;
}

export function getCharacter(
  id: string | null | undefined
): Character | undefined {
  return id ? charactersById.get(id) : undefined;
}

export function getBand(id: string | null | undefined): Band | undefined {
  return id ? bandsById.get(id) : undefined;
}

export function getCardAttribute(
  code: number | null | undefined
): CardAttributeDefinition | undefined {
  return typeof code === "number" ? attributesByCode.get(code) : undefined;
}

export function getCardRarity(
  code: number | null | undefined
): CardRarityDefinition | undefined {
  return typeof code === "number" ? raritiesByCode.get(code) : undefined;
}

export function getMemberCard(
  id: string | null | undefined
): MemberCard | undefined {
  return id ? memberCardsById.get(id) : undefined;
}

export function getSupportCard(
  id: string | null | undefined
): SupportCard | undefined {
  return id ? supportCardsById.get(id) : undefined;
}

export function getMusicTrack(
  id: string | null | undefined
): MusicTrack | undefined {
  return id ? musicTracksById.get(id) : undefined;
}

export function getMusicChart(
  id: string | null | undefined
): MusicChart | undefined {
  return id ? musicChartsById.get(id) : undefined;
}

export function getMusicCharts(trackId: string): MusicChart[] {
  return catalog.musicCharts.filter((chart) => chart.trackId === trackId);
}

export function getCharacterMemberCards(characterId: string): MemberCard[] {
  return catalog.memberCards.filter(
    (card) => card.characterId === characterId
  );
}

export function getCharacterSupportCards(characterId: string): SupportCard[] {
  return catalog.supportCards.filter((card) =>
    card.featuredCharacterIds.includes(characterId)
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${unit}`;
}

export function formatBpm(value: number): string {
  return Number(value.toFixed(2)).toString();
}

export function formatBpmRange(range: { min: number; max: number }): string {
  return Math.abs(range.min - range.max) < 0.001
    ? formatBpm(range.min)
    : `${formatBpm(range.min)}–${formatBpm(range.max)}`;
}

export function kindLabel(
  kind: Asset["kind"],
  locale: string = catalog.release.locale
): string {
  const labels = locale === "en"
    ? {
        character: "Character asset",
        card: "Card art",
        background: "Background",
        banner: "Banner",
        cover: "Cover",
        logo: "Logo",
        item: "Item icon",
        skill: "Skill icon",
        card_taxonomy: "Card UI icon",
        band_logo: "Band logo",
        other: "Other"
      }
    : {
        character: "角色素材",
        card: "卡面",
        background: "背景",
        banner: "横幅",
        cover: "封面",
        logo: "标识",
        item: "道具图标",
        skill: "技能图标",
        card_taxonomy: "卡牌功能图标",
        band_logo: "乐队标识",
        other: "其他"
      };
  return labels[kind];
}

export function statusLabel(
  status: string,
  locale: string = catalog.release.locale
): string {
  const labels: Record<string, string> = locale === "en"
    ? {
        identified: "Identified",
        pending: "Pending archive",
        missing_asset: "Missing image"
      }
    : {
        identified: "已识别",
        pending: "待归档",
        missing_asset: "缺少图片"
      };
  return labels[status] ?? status;
}

export function pageTitle(title?: string): string {
  const siteTitle = SITE_NAME;
  return title
    ? `${title} — ${siteTitle}`
    : siteTitle;
}

export function bestHeroAsset(): Asset {
  const heroCandidates = catalog.assets
    .filter((asset) => {
      const ratio = asset.width / Math.max(asset.height, 1);
      const pixels = asset.width * asset.height;
      return ratio >= 1.5 && pixels >= 1_000_000;
    })
    .sort((left, right) => {
      const kindPriority = (asset: Asset) =>
        asset.kind === "card" ? 2 : asset.kind === "background" ? 1 : 0;
      return (
        kindPriority(right) - kindPriority(left) ||
        right.width * right.height - left.width * left.height
      );
    });

  return (
    heroCandidates[0] ??
    getAsset(catalog.supportCards[0]?.primaryAssetId) ??
    getAsset(catalog.memberCards[0]?.primaryAssetId) ??
    catalog.assets[0]
  );
}
