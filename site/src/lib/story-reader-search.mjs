const normalize = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase().trim();
export const storyLineSpeakers = speaker => String(speaker ?? '').split(/\s+\/\s+/).filter(Boolean);

/** Return line indexes, keeping the original transcript and excerpt indexes intact. */
export function findStoryLines(lines, query = '', speaker = '') {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  if (!words.length && !speaker) return [];
  return lines.flatMap((line, index) => {
    const text = normalize(`${line.speaker} ${line.text}`);
    return (!speaker || storyLineSpeakers(line.speaker).includes(speaker)) && words.every(word => text.includes(word)) ? [index] : [];
  });
}

export function stepStoryMatch(current, direction, count) {
  if (count <= 0) return -1;
  if (current < 0) return direction < 0 ? count - 1 : 0;
  return (current + direction + count) % count;
}
