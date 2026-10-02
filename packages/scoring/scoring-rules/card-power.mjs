// Verified against Global production 1.0.1 (25) IL2CPP, not the earlier test APK:
// input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/libil2cpp.decoded.so
// App.CardParameter.CardPower stores each component in basis points. Native
// op_Multiply (0x55bc214) divides component products by 10,000 toward zero;
// ToFloor (0x55bc2cc) converts to float32 before flooring.
export const CARD_POWER_SCALE = 10000n;

const component = (value) => {
  if (typeof value === "bigint") return value;
  if (typeof value === "number" && Number.isSafeInteger(value)) return BigInt(value);
  throw new TypeError("CardPower components must be safe integers or bigint values");
};

export function createCardPowerBP(performance, technic, visual) {
  return {
    performance: component(performance),
    technic: component(technic),
    visual: component(visual)
  };
}

export function createCardPowerInt(performance, technic, visual) {
  return createCardPowerBP(
    component(performance) * CARD_POWER_SCALE,
    component(technic) * CARD_POWER_SCALE,
    component(visual) * CARD_POWER_SCALE
  );
}

export function addCardPower(left, right) {
  return createCardPowerBP(
    component(left.performance) + component(right.performance),
    component(left.technic) + component(right.technic),
    component(left.visual) + component(right.visual)
  );
}

export function multiplyCardPower(left, right) {
  return createCardPowerBP(
    component(left.performance) * component(right.performance) / CARD_POWER_SCALE,
    component(left.technic) * component(right.technic) / CARD_POWER_SCALE,
    component(left.visual) * component(right.visual) / CARD_POWER_SCALE
  );
}

const floorDiv = (value, divisor) => {
  const quotient = value / divisor;
  return value < 0n && value % divisor !== 0n ? quotient - 1n : quotient;
};

const nativeFloorToInt = (value) => {
  const number = Number(value);
  if (!Number.isSafeInteger(number)) {
    throw new RangeError("CardPower float conversion requires a safe integer");
  }
  // scvtf s -> fdiv s -> fcvtms: both floating steps round to float32.
  const whole = Math.floor(Math.fround(Math.fround(number) / 10000));
  if (!Number.isSafeInteger(whole)) {
    throw new RangeError("CardPower floored component exceeds safe range");
  }
  return BigInt(whole);
};

export function floorCardPower(value) {
  return createCardPowerBP(
    nativeFloorToInt(component(value.performance)) * CARD_POWER_SCALE,
    nativeFloorToInt(component(value.technic)) * CARD_POWER_SCALE,
    nativeFloorToInt(component(value.visual)) * CARD_POWER_SCALE
  );
}

export function cardPowerPoints(value) {
  const points = ["performance", "technic", "visual"].map((key) =>
    floorDiv(component(value[key]), CARD_POWER_SCALE)
  );
  const safe = points.map((point) => {
    const number = Number(point);
    if (!Number.isSafeInteger(number)) throw new RangeError("CardPower exceeds safe point range");
    return number;
  });
  const total = Number(points[0] + points[1] + points[2]);
  if (!Number.isSafeInteger(total)) throw new RangeError("CardPower total exceeds safe point range");
  return {
    performance: safe[0],
    technic: safe[1],
    visual: safe[2],
    total
  };
}
