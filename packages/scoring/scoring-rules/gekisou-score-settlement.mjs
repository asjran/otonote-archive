/** Global build 25 multiplayer section settlement:
 * OnTryConnectGekisouResult 0x613c948 fetches only on transition to state 7.
 * GetScoreAtTimeMs 0x55ccb28 reads START then END using the live calculator.
 * NetworkGekisouRankingUpdater can credit at state 8, after all results arrive.
 * For supplied ranks/opponents, assume results available on that first eligible
 * frame. This is an explicit offline condition, not simulated network latency.
 */
export function gekisouSettlementActions(states, award, { confirmationDelayFrames = [0, 0, 0] } = {}) {
  if (!Array.isArray(confirmationDelayFrames) || confirmationDelayFrames.length < states.length ||
      confirmationDelayFrames.some(value => !Number.isSafeInteger(value) || value < 0 || value > 3600)) throw new Error('无效的排名确认延迟');
  return states.flatMap((state, index) => [
    { frame: state.releaseFrame, run(replay) {
      const startScore = replay.calculate(state.startMs);
      const endScore = replay.calculate(state.endMs);
      state.scoreQuery = { frame: state.releaseFrame, startScore, endScore };
      state.noteScore = endScore - startScore;
      if (award) state.rankingBonus = award(state);
    } },
    ...(award ? [{ frame: state.releaseFrame + 1 + confirmationDelayFrames[index], run(replay) {
      state.confirmationFrame = state.releaseFrame + 1 + confirmationDelayFrames[index];
      replay.addFixedScore({ timeMs: state.endMs, score: state.rankingBonus });
    } }] : [])
  ]);
}
