import { catalog, getAsset, type Character } from "./catalog";
import { createSpeakerResolver } from "./story-speaker.mjs";
export const resolveStorySpeaker = createSpeakerResolver(catalog.characters);
export function storyAvatar(character?: Character | null) {
  return character?.portraitAssetIds.map(getAsset).find(asset => asset?.containerPath?.endsWith("/character_face_icon.png"));
}
export function storyCharacter(id: number) { return catalog.characters.find(character => character.masterId === id); }
