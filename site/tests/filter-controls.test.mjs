import assert from 'node:assert/strict';
import test from 'node:test';
import { matchesFilter, filterValues, restoreFilterControl, selectedControlValues } from '../src/lib/filter-controls.mjs';

test('multi-select groups use OR and treat the all choice as unrestricted', () => {
  assert.equal(matchesFilter(['band-1', 'band-3'], 'band-1,band-2'), true);
  assert.equal(matchesFilter(['band-3'], 'band-1,band-2'), false);
  assert.equal(matchesFilter('4', ['2', '4']), true);
  assert.equal(matchesFilter('4', 'all'), true);
  assert.deepEqual(filterValues('all,,band-2'), ['band-2']);
});

test('URL restore replaces selections and reset restores the all button', () => {
  const control = { multiple: true, options: ['all', 'band-1', 'band-2', 'band-3'].map(value => ({value, selected: false})) };
  restoreFilterControl(control, 'band-1,band-2');
  assert.deepEqual(control.options.filter(o => o.selected).map(o => o.value), ['band-1', 'band-2']);
  restoreFilterControl(control, 'band-3');
  assert.deepEqual(control.options.filter(o => o.selected).map(o => o.value), ['band-3']);
  restoreFilterControl(control, '');
  assert.deepEqual(control.options.filter(o => o.selected).map(o => o.value), ['all']);
  assert.deepEqual(selectedControlValues({...control, selectedOptions: control.options.filter(o => o.selected)}), []);
});
