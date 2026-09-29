// Support-card power is stored in basis points; member power is absolute.
// Keep the raw growth snapshot unchanged for formation calculations.
export function formatCardPower(value, cardKind, locale = "zh-CN") {
  return cardKind === "support"
    ? `${Number((value / 100).toFixed(2))}%`
    : Number(value).toLocaleString(locale);
}
