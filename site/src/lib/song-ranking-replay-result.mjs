import { SCORE_MODEL_VERSION } from './scoring-rules/model-version.mjs';
import { songSkillProfileKey } from './song-skill-profile.mjs';

export function withSongSkillReplay(row, replay) {
  if (replay?.mode !== 'ordinary' || replay.precision !== 'replay' || replay.modelVersion !== SCORE_MODEL_VERSION
    || replay.chartId !== (row.sourceId ?? row.id) || replay.trackId !== row.trackId.replace(/^(global|jp)--/, '') || replay.difficulty !== row.difficulty
    || replay.power !== row.benchmark?.power || replay.profileKey !== songSkillProfileKey(replay.skills, replay.frameRate)
    || replay.sourceReleaseId !== row.replaySource?.releaseId) throw new Error('精算结果与当前比较条件不一致');
  const distribution = replay.distribution, mean = distribution.mean;
  return { ...row, skillProfile: replay.skills, skillReplay: replay, calculation: 'replay',
    baseScore: replay.baseScore, expectedScore: mean, minimumScore: distribution.minimum,
    maximumScore: distribution.maximum, p10Score: distribution.p10, scoreDistribution: distribution,
    skillScoreGain: mean - replay.baseScore, scoreMultiplier: mean / replay.power,
    skillMultiplier: replay.baseScore > 0 ? mean / replay.baseScore : null, positionContributions: null };
}
