import { serializeTeamDraftSearch } from '../team-draft.mjs';
import { normalizeGekisouScenario } from './gekisou-song-score.mjs';

export function scoringScenarioSearch(draft, mode, scenario) {
  if (!['ordinary', 'gekisou'].includes(mode)) throw new Error('Unknown scoring mode');
  const params = new URLSearchParams(serializeTeamDraftSearch(draft));
  params.set('scoreMode', mode);
  if (mode === 'gekisou') params.set('gekisouScenario', JSON.stringify(normalizeGekisouScenario(scenario)));
  return `?${params}`;
}

export function readScoringScenarioSearch(search) {
  const params = new URLSearchParams(search), mode = params.get('scoreMode') ?? 'ordinary';
  if (!['ordinary', 'gekisou'].includes(mode)) throw new Error('Unknown scoring mode');
  const value = params.get('gekisouScenario');
  if (value && value.length > 12000) throw new Error('Invalid scoring scenario');
  return { mode, scenario: mode === 'gekisou' ? normalizeGekisouScenario(value ? JSON.parse(value) : {}) : null };
}
