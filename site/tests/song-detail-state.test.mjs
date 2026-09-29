import test from 'node:test';
import assert from 'node:assert/strict';
import { songViewFromLocation, songDifficultyFromLocation } from '../src/lib/song-detail-state.mjs';

test('direct module links preserve their view alongside difficulty', () => {
  for (const view of ['playback', 'analysis', 'rewards']) {
    assert.equal(songViewFromLocation(`?view=${view}&difficulty=hard`), view);
  }
  assert.equal(songViewFromLocation('?view=unknown'), null);
  assert.equal(songViewFromLocation('?view=rewards', '#score-track'), 'rewards');
});

test('detail pages and retired links do not open a dialog by default', () => {
  assert.equal(songViewFromLocation('?view=details&difficulty=hard'), null);
  assert.equal(songViewFromLocation(''), null);
});

test('existing score and reward anchors still open the relevant module', () => {
  assert.equal(songViewFromLocation('?difficulty=easy', '#score-track'), 'analysis');
  assert.equal(songViewFromLocation('', '#chart-analysis'), 'analysis');
  assert.equal(songViewFromLocation('', '#track-rewards'), 'rewards');
  assert.equal(songViewFromLocation('', '#unknown'), null);
});

test('difficulty links fall back to a chart that actually exists', () => {
  assert.equal(songDifficultyFromLocation('?difficulty=easy', ['easy', 'expert']), 'easy');
  assert.equal(songDifficultyFromLocation('?difficulty=invalid', ['easy', 'expert']), 'expert');
  assert.equal(songDifficultyFromLocation('', ['normal', 'hard']), 'normal');
  assert.equal(songDifficultyFromLocation('?difficulty=expert', ['easy']), 'easy');
});
