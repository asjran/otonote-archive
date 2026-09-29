import { normalizeGekisouOpponents } from './scoring-rules/gekisou-ranking.mjs';

export function readGekisouOpponentInputs(root) {
  return normalizeGekisouOpponents([...root.querySelectorAll('[data-gekisou-opponent]')]
    .filter(row => row.querySelector('[data-opponent-enabled]').checked)
    .map(row => ({ sections: [...row.querySelectorAll('[data-opponent-section]')].map(section =>
      Object.fromEntries([...section.querySelectorAll('[data-opponent-field]')].map(input => {
        if (input.value.trim() === '') throw new Error('请完整填写启用对手的段落数据');
        return [input.dataset.opponentField, Number(input.value)];
      }))) })));
}

export function writeGekisouOpponentInputs(root, opponents) {
  const normalized = normalizeGekisouOpponents(opponents);
  [...root.querySelectorAll('[data-gekisou-opponent]')].forEach((row, index) => {
    row.querySelector('[data-opponent-enabled]').checked = index < normalized.length;
    [...row.querySelectorAll('[data-opponent-section]')].forEach((section, i) => {
      for (const input of section.querySelectorAll('[data-opponent-field]')) {
        input.value = String(normalized[index]?.sections[i][input.dataset.opponentField] ?? 0);
      }
    });
  });
}
