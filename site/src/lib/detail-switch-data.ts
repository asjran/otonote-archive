import {
  catalog,
  getAsset,
  getBand,
  getCharacter,
  getCardAttribute
} from "./catalog";
import { filterVisualOptions } from "./filter-visuals";

const option = (value: string, label: string) => ({ value, label });
const rarityOptions = filterVisualOptions.rarity;
const attributeOptions = (values: number[]) =>
  [...new Set(values)]
    .sort((left, right) => left - right)
    .map((value) => option(String(value), getCardAttribute(value)?.names[catalog.release.locale] ?? `属性 ${value}`));

const characterOptions = catalog.characters.map((character) =>
  option(character.id, character.displayName)
);
const bandOptions = catalog.bands.map((band) =>
  option(band.id, band.displayName)
);

export const memberCardSwitchData = {
  label: "成员卡",
  facets: [
    { name: "character", label: "角色", options: characterOptions },
    { name: "band", label: "乐队", options: bandOptions },
    {
      name: "rarity",
      label: "稀有度",
      options: rarityOptions
    },
    {
      name: "attribute",
      label: "属性",
      options: attributeOptions(catalog.memberCards.map((card) => card.attributeCode))
    }
  ],
  items: catalog.memberCards.map((card) => {
    const character = getCharacter(card.characterId);
    const band = getBand(character?.bandId);
    return {
      id: card.id,
      href: `/cards/members/${card.id}/`,
      title: card.subtitle || card.displayName,
      subtitle: [character?.displayName, band?.displayName].filter(Boolean).join(" · "),
      imageUrl: getAsset(card.thumbnailAssetId)?.previewUrl,
      mediaKind: "portrait" as const,
      facets: {
        character: [card.characterId],
        band: character?.bandId ? [character.bandId] : [],
        rarity: [String(card.rarity)],
        attribute: [String(card.attributeCode)]
      }
    };
  })
};

export const supportCardSwitchData = {
  label: "留影",
  facets: [
    { name: "character", label: "登场角色", options: characterOptions },
    { name: "band", label: "关联乐队", options: bandOptions },
    {
      name: "rarity",
      label: "稀有度",
      options: rarityOptions
    },
    {
      name: "attribute",
      label: "属性",
      options: attributeOptions(catalog.supportCards.map((card) => card.attributeCode))
    }
  ],
  items: catalog.supportCards.map((card) => {
    const characters = card.featuredCharacterIds
      .map(getCharacter)
      .filter((character) => character !== undefined);
    const bands = [...new Set(characters.map((character) => character.bandId))];
    return {
      id: card.id,
      href: `/cards/supports/${card.id}/`,
      title: card.description || card.displayName,
      subtitle: characters.map((character) => character.displayName).join("、"),
      imageUrl: getAsset(card.thumbnailAssetId)?.previewUrl,
      mediaKind: "landscape" as const,
      facets: {
        character: card.featuredCharacterIds,
        band: bands,
        rarity: [String(card.rarity)],
        attribute: [String(card.attributeCode)]
      }
    };
  })
};

export const characterSwitchData = {
  label: "角色",
  facets: [{ name: "band", label: "乐队", options: bandOptions }],
  items: catalog.characters.map((character) => ({
    id: character.id,
    href: `/characters/${character.id}/`,
    title: character.displayName,
    subtitle: [getBand(character.bandId)?.displayName, character.role]
      .filter(Boolean)
      .join(" · "),
    imageUrl: getAsset(character.profileAssetId)?.previewUrl,
    mediaKind: "portrait" as const,
    facets: { band: [character.bandId] }
  }))
};

const musicBandOptions = [
  ...new Map(
    catalog.musicTracks.flatMap((track) =>
      track.bandIds.map((id, index) => [
        id,
        option(id, track.bandLabels[index] ?? id)
      ])
    )
  ).values()
];
const musicCharacterOptions = [
  ...new Map(
    catalog.musicTracks.flatMap((track) =>
      track.vocalCharacterIds.map((id, index) => [
        id,
        option(id, track.vocalistLabels[index] ?? id)
      ])
    )
  ).values()
];
const musicTypeOptions = [
  ...new Map(
    catalog.musicTracks.map((track) => [
      String(track.musicType),
      option(String(track.musicType), track.musicTypeLabel)
    ])
  ).values()
];
const musicCategoryOptions = [
  ...new Map(
    catalog.musicTracks.flatMap((track) =>
      track.categoryIds.map((id, index) => [
        String(id),
        option(String(id), track.categoryLabels[index] ?? String(id))
      ])
    )
  ).values()
];
const musicTagOptions = [
  ...new Map(
    catalog.musicTracks.flatMap((track) =>
      track.tagIds.map((id, index) => [
        String(id),
        option(String(id), track.tagLabels[index] ?? String(id))
      ])
    )
  ).values()
];

export const musicSwitchData = {
  label: "歌曲",
  facets: [
    { name: "band", label: "演唱乐队", options: musicBandOptions },
    { name: "character", label: "演唱角色", options: musicCharacterOptions },
    { name: "music-type", label: "歌曲属性", options: musicTypeOptions },
    { name: "category", label: "客户端分类", options: musicCategoryOptions },
    { name: "tag", label: "Best Music 标签", options: musicTagOptions }
  ],
  items: catalog.musicTracks.map((track) => ({
    id: track.id,
    href: `/music/${track.id}/`,
    title: track.title,
    subtitle: [...track.bandLabels, ...track.vocalistLabels].join(" · "),
    imageUrl: getAsset(track.jacketAssetId)?.previewUrl,
    mediaKind: "square" as const,
    facets: {
      band: track.bandIds,
      character: track.vocalCharacterIds,
      "music-type": [String(track.musicType)],
      category: track.categoryIds.map(String),
      tag: track.tagIds.map(String)
    }
  }))
};
