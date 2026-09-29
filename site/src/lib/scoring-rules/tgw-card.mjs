import { createCardPowerBP, floorCardPower, multiplyCardPower } from "./card-power.mjs";

// Global production 1.0.1 (25) looks up MasterVipRankBonus type 7 for each
// slot. CalculateSlotPower multiplies a CardPower base by that raw BP rate and
// then calls ToFloor. The construction of that base is still being traced.
export const TGW_ALL_PARAMETERS_BONUS_TYPE = 7;

export function calculateTgwCardSlotBonus(basePower, rawBonusBP) {
  if (!Number.isSafeInteger(rawBonusBP) || rawBonusBP < 0) {
    throw new RangeError("T.G.W CARD bonus must be nonnegative integer basis points");
  }
  const rate = createCardPowerBP(rawBonusBP, rawBonusBP, rawBonusBP);
  return floorCardPower(multiplyCardPower(basePower, rate));
}

export function resolveTgwCardRankBonus(vipRanks, rank) {
  if (!Number.isInteger(rank) || rank < 1) {
    throw new RangeError("T.G.W CARD rank must be a positive integer");
  }
  if (!Array.isArray(vipRanks)) throw new TypeError("vipRanks must be an array");
  const configuredRank = vipRanks.find((entry) => entry.rank === rank);
  if (!configuredRank) throw new RangeError(`T.G.W CARD rank ${rank} is not configured`);
  const bonuses = (configuredRank.bonuses ?? []).filter(
    (bonus) => bonus.type === TGW_ALL_PARAMETERS_BONUS_TYPE
  );
  if (bonuses.length > 1) throw new RangeError(`T.G.W CARD rank ${rank} has duplicate parameter bonuses`);
  if (bonuses.length === 0 && rank !== 1) {
    throw new RangeError(`T.G.W CARD rank ${rank} has no parameter bonus`);
  }
  const rawValue = bonuses[0]?.rawValue ?? 0;
  if (!Number.isSafeInteger(rawValue) || rawValue < 0) {
    throw new RangeError(`T.G.W CARD rank ${rank} has an invalid parameter bonus`);
  }
  return {
    rank,
    type: TGW_ALL_PARAMETERS_BONUS_TYPE,
    rawValue,
    calculationStatus: "base_power_unverified"
  };
}
