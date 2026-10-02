import {catalog} from './catalog';
import {activeReleaseContext} from './release-context';
import {editionArtifact,otherEditionArtifact} from '../runtime/content.mjs';
import {combineSongRankings,neutralRankingRulesFingerprint} from './shared-song-rankings.mjs';
import {loadSongRankingData} from './song-ranking-data.mjs';
import rules from '../data/formal-scoring-rules.json';
import {scoringRulesAvailable} from './scoring-release-gate.mjs';
import {attachSkillReferences} from './song-ranking-skill-data.mjs';
const {region,locale}=activeReleaseContext;
const other=region==='jp'?'global':'jp';
const [secondary,otherData,otherRules] = await Promise.all([
  otherEditionArtifact(region,'projection/catalog.json'),otherEditionArtifact(region,'supplemental/song-rankings.json'),
  otherEditionArtifact(region,'supplemental/formal-scoring-rules.json')
]);
let nativeData = null;
if (scoringRulesAvailable(rules,catalog.release.id)) {
  try { nativeData=await loadSongRankingData({rules,releaseId:catalog.release.id,tracks:catalog.musicTracks,charts:catalog.musicCharts,
    sourceRoot:import.meta.env.OURNOTES_RANKING_SOURCE_ROOT});
  } catch {
    // A missing derived ranking must not block unrelated page generation.
    // The shared table renders pending rows until content derivation finishes.
    nativeData=null;
  }
} else {
  try {nativeData=await editionArtifact(region,'supplemental/song-rankings.json',{optional:true});} catch {}
}
export const sharedSongRankings=combineSongRankings([
  {edition:region,catalog,data:nativeData,neutralRulesFingerprint:await neutralRankingRulesFingerprint(rules,catalog.release.id)},
  ...(secondary?[{edition:other,catalog:secondary,data:otherData,
    neutralRulesFingerprint:await neutralRankingRulesFingerprint(otherRules,secondary.release.id)}]:[])
],{region,locale});
await attachSkillReferences(sharedSongRankings,[{edition:region,catalog,rules},{edition:other,catalog:secondary,rules:otherRules}],locale);
