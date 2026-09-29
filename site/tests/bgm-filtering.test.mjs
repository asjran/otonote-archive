import assert from 'node:assert/strict';
import test from 'node:test';
import { matchesBgm, formatBgmTime, formatBgmSize } from '../src/lib/bgm-filtering.mjs';
import { activeNavigationGroup, activeNavigationChild, navigationRoutes, NAVIGATION_GROUPS } from '../src/lib/navigation.mjs';

const home = { title: '主界面', cueName: 'sound_bgm_home', categoryIds: ['home'], status: 'available' };
const story = { title: 'Home Swing', cueName: 'sound_bgm_adv_home_swing', categoryIds: ['story'], status: 'available' };
test('category, all search terms and availability combine without confusing title and scene', () => {
  assert.equal(matchesBgm(home, 'ＨＯＭＥ', 'home', true), true);
  assert.equal(matchesBgm(story, 'home', 'home'), false);
  assert.equal(matchesBgm(story, 'home swing', 'story'), true);
  assert.equal(matchesBgm(story, 'home birthday'), false);
  assert.equal(matchesBgm({ ...home, status: 'missing' }, '', 'all', true), false);
  assert.equal(matchesBgm({ ...home, status: 'missing' }, '', 'all', false), true);
});
test('metadata remains meaningful for missing, short and long tracks', () => {
  assert.equal(formatBgmTime(NaN), '—');
  assert.equal(formatBgmTime(0), '0:00');
  assert.equal(formatBgmTime(142.8), '2:22');
  assert.equal(formatBgmTime(3600), '60:00');
  assert.equal(formatBgmSize(1024), '1 KB');
  assert.equal(formatBgmSize(1.5 * 1024 * 1024), '1.5 MB');
});
test('BGM is a music child route with the same active navigation group', () => {
  assert.ok(navigationRoutes().includes('/music/bgm/'));
  assert.equal(activeNavigationGroup('/music/bgm/'), 'music');
  const children = NAVIGATION_GROUPS.find(group => group.id === 'music').children;
  assert.equal(activeNavigationChild('/music/bgm/', children).href, '/music/bgm/');
  assert.equal(activeNavigationChild('/music/music-1/', children).href, '/music/');
});
