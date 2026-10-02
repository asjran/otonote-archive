import { eventRecords } from "./event-pages";
import { storyLibrary } from "./story-library";
import { eventStoryEntryId } from "./event-content.mjs";
const episodeIds = new Set(eventRecords.flatMap(event => event.story.episodes.map(eventStoryEntryId)));
// The content compiler validates each document and records its line count.
// Directory pages use that index; full text is loaded only by the episode reader.
export const readableEventStoryIds = storyLibrary.entries.filter(entry => episodeIds.has(entry.id) && entry.eventId != null && entry.lineCount > 0).map(entry => entry.id);
export const readableEventStoryCounts = Object.fromEntries(eventRecords.map(event => [event.id,
  event.story.episodes.filter(episode => readableEventStoryIds.includes(eventStoryEntryId(episode))).length]));
