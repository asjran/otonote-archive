// NoteJudgementTypeMap.ConvertJudgementType, 0x6a67884 (global 1.0.1/25).
// Operate types and judgement types are DIFFERENT enums: a normal slide end
// is judgement 11, which has no native JUST timing window.
export function formalJudgementType(operateType, critical = false) {
  if (operateType === 1) return critical ? 2 : 1;
  if (operateType === 20) return critical ? 15 : 10;
  if ([40, 41, 42, 102].includes(operateType)) return 5;
  if (operateType === 22) return 11;
  if (operateType === 62) return 22;
  if ([60, 61, 63, 104, 105, 120].includes(operateType)) return 21;
  if ([80, 82, 100, 101, 103, 121, 122].includes(operateType)) return 1;
  if ([0, 21].includes(operateType)) return operateType;
  throw new Error(`Unsupported native note operate type ${operateType}`);
}
