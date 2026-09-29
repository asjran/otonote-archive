import assert from 'node:assert/strict';
import test from 'node:test';
import { parseScoreTime, resolveAtlasRange, getAtlasSegments } from '../src/lib/score-atlas-range.mjs';
import { renderScoreSegment } from '../src/lib/score-sheet-renderer.ts';

test('accepts seconds and minutes:seconds, with blanks using the song bounds', () => {
  assert.equal(parseScoreTime(' 30.5 '), 30.5);
  assert.equal(parseScoreTime('1:02.25'), 62.25);
  assert.deepEqual(resolveAtlasRange('', '', 94.736842), { start: 0, end: 94.736842 });
  assert.deepEqual(resolveAtlasRange('30.5', '1:02', 94.736842), { start: 30.5, end: 62 });
});

test('rejects malformed, reversed, equal and out-of-song time ranges', () => {
  for (const [start, end] of [['1:99', '90'], ['-1', '30'], ['20', '10'], ['30', '30'], ['0', '101'], ['abc', '50'], ['Infinity', '90']]) {
    assert.throws(() => resolveAtlasRange(start, end, 100));
  }
});

test('custom segments begin at the exact selected time and end without overshooting', () => {
  assert.deepEqual(getAtlasSegments(100, { start: 30.5, end: 40.25 }), [
    { index: 0, start: 30.5, end: 34.5, includeEnd: false },
    { index: 1, start: 34.5, end: 38.5, includeEnd: false },
    { index: 2, start: 38.5, end: 40.25, includeEnd: true },
  ]);
  assert.equal(getAtlasSegments(100, { start: 30.125, end: 30.25 }).length, 1);
});

test('a selected end note is included exactly once and outside notes are excluded', () => {
  const chart = { duration: 100, feverRanges: [], skillTimings: [], notes: [29, 30, 34, 38, 39].map(time => ({ id: String(time), type: 'tap', time, position: 6, size: 6 })) };
  const keys = getAtlasSegments(chart.duration, { start: 30, end: 38 }).flatMap(segment => renderScoreSegment(chart, segment, new Set(['tap'])).markers.map(marker => marker.key));
  assert.deepEqual(keys, ['30', '34', '38']);
});
