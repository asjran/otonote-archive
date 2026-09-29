import assert from 'node:assert/strict';
import test from 'node:test';
import { getScoreSegments } from '../src/lib/score-track-layout.mjs';
import { renderScoreSegment, SHEET_SEGMENT_SECONDS } from '../src/lib/score-sheet-renderer.ts';

const chart = {
  duration: 17.25,
  skillTimings: [8], feverRanges: [{ start: 7, end: 10 }],
  notes: [
    { id: 'boundary', type: 'tap', time: 8, position: 6, size: 4 },
    { id: 'last', type: 'flick', time: 17.25, position: 12, size: 4, direction: 'right' },
    { id: 'crossing', type: 'long', nodes: [
      { time: 7, position: 2, size: 4, visible: true },
      { time: 9, position: 10, size: 4, visible: true },
    ] },
  ],
};
const enabled = new Set(['tap', 'flick', 'long', 'events']);

test('atlas cards cover the song in four-second steps without losing or duplicating notes', () => {
  const segments = getScoreSegments(chart.duration, SHEET_SEGMENT_SECONDS);
  assert.equal(segments.length, 5);
  assert.equal(segments.at(-1).end, chart.duration);
  assert.ok(segments.every(segment => segment.end - segment.start <= 4));
  const keys = segments.flatMap(segment => renderScoreSegment(chart, segment, enabled).markers.map(marker => marker.key));
  assert.deepEqual(keys.sort(), ['boundary', 'crossing:0', 'crossing:1', 'last'].sort());
});

test('segments cover the entire chart in order including a fractional final window', () => {
  assert.deepEqual(getScoreSegments(chart.duration), [
    { index: 0, start: 0, end: 8 }, { index: 1, start: 8, end: 16 }, { index: 2, start: 16, end: 17.25 },
  ]);
  assert.deepEqual(getScoreSegments(0), []);
  assert.deepEqual(getScoreSegments(10, 0), []);
});

test('boundary notes and skill lines occur once, including the last note', () => {
  const plans = getScoreSegments(chart.duration).map(segment => renderScoreSegment(chart, segment, enabled));
  assert.equal(plans.flatMap(plan => plan.markers).filter(note => note.key === 'boundary').length, 1);
  assert.equal(plans[1].markers.find(note => note.key === 'boundary').y, plans[1].height);
  assert.equal(plans[2].markers.find(note => note.key === 'last').y, 0);
  assert.equal(plans.flatMap(plan => plan.skillLines).length, 1);
});

test('long ribbons continue across segment boundaries and fever bands stay clipped', () => {
  const plans = getScoreSegments(chart.duration).map(segment => renderScoreSegment(chart, segment, enabled));
  assert.equal(plans[0].longRibbons.length, 1);
  assert.equal(plans[1].longRibbons.length, 1);
  assert.equal(plans[2].longRibbons.length, 0);
  assert.deepEqual(plans[0].feverBands, [{ top: 0, height: 168 }]);
  assert.deepEqual(plans[1].feverBands, [{ top: 1008, height: 336 }]);
  const hidden = renderScoreSegment(chart, getScoreSegments(chart.duration)[0], new Set(['tap']));
  assert.equal(hidden.longRibbons.length, 0);
  assert.equal(hidden.feverBands.length, 0);
});
