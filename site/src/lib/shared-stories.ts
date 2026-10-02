import {storyLibrary as native, type TextStoryEntry} from './story-library';
import {storyIdentity} from './shared-archives';
import {otherEditionArtifact} from '../runtime/content.mjs';
import {activeReleaseContext} from './release-context';
import {decorateEventStories} from './event-content.mjs';
import {mergeEditionRows} from './edition-library.mjs';
export * from './story-library';
const {region,locale}=activeReleaseContext;
const [other,modes]=await Promise.all([otherEditionArtifact(region,'projection/story-library.json'),otherEditionArtifact(region,'projection/game-modes.json')]);
export const storyLibrary = {...native, entries:mergeEditionRows(native.entries,
  other?decorateEventStories(other.entries,modes?.events?.records??[]):null,
  {region,locale,key:storyIdentity,difference:row=>row.contentComparison??'',path:(row:TextStoryEntry)=>`/stories/episodes/${row.id}/`}) as TextStoryEntry[]};
