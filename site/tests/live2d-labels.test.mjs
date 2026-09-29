import { test } from 'node:test';
import assert from 'node:assert/strict';
import { modelLabel, clipLabel, preferredMotion } from '../src/lib/live2d-labels.mjs';

test('model names distinguish story school variants from live performance models', () => {
  const model = { modelPath: '018_adv/adv_live2d_nagi_018_school_winter_jhs_2nd/model/adv_live2d_nagi_018_school_winter_jhs_2nd', usage: 'story', state: 'available' };
  assert.equal(modelLabel(model), '校服 · 冬季 · 初中 · 二年级 — 剧情模型');
  const npc = { ...model, modelPath: 'sub_mikus_father/model/adv_live2d_sub_mikus_father_casual_spring_01_still' };
  assert.equal(modelLabel(npc, true), 'Casual · Spring · 01 · Still variant — Story');
});

test('friendly labels retain source identifiers and preserve unknown animation names', () => {
  assert.equal(clipLabel('mtn_idle01_C'), '待机 1 · 正面 / mtn_idle01_C');
  assert.equal(clipLabel('22-exp_smile01', true), 'Smile 1 / 22-exp_smile01');
  assert.equal(clipLabel('unknown_clip'), 'unknown_clip');
});

test('preferred motion selects front idle instead of an alphabetically first angry clip', () => {
  const motions = ['mtn_angry01_C', 'mtn_idle01_L', 'mtn_idle01_C'].map(sourceName => ({ sourceName }));
  assert.equal(preferredMotion(motions), 2);
  assert.equal(preferredMotion([{ sourceName: 'mtn_bye01_C' }]), 0);
});
