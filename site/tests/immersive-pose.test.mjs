import test from 'node:test';
import assert from 'node:assert/strict';
import { Skeleton, SkeletonJson } from '@esotericsoftware/spine-threejs';
import { createSpinePoseSampler } from '../src/lib/immersive-pose.mjs';

function fixture() {
  const data = new SkeletonJson({}).readSkeletonData({
    skeleton: { spine: '4.2.67' }, bones: [{ name: 'root' }, { name: 'hair', parent: 'root', length: 10 }],
    physics: [{ name: 'hair', bone: 'hair', rotate: 1, gravity: 1, inertia: .5 }],
    animations: { entrance: { bones: { root: { translate: [{ x: 0 }, { time: 4, x: 20, y: 10 }] } } } }
  });
  const skeleton = new Skeleton(data), sample = createSpinePoseSampler(skeleton, data.animations[0]);
  const pose = () => skeleton.bones.map(b => [b.a, b.b, b.c, b.d, b.worldX, b.worldY]);
  return { skeleton, sample, pose };
}

test('secondary motion advances and absolute seeks reproduce it after an export or replay', () => {
  const { skeleton, sample, pose } = fixture();
  sample(1); const first = pose();
  assert.notEqual(skeleton.physicsConstraints[0].rotateOffset, 0);
  sample(4); sample(0); sample(1);
  assert.deepEqual(pose(), first);
  sample(1.001); const offset = skeleton.physicsConstraints[0].rotateOffset;
  sample(1.005); sample(1.005);
  assert.equal(skeleton.physicsConstraints[0].rotateOffset, offset);
  sample(3); const end = pose();
  sample(0);
  for (let frame = 1; frame <= 180; frame++) sample(frame / 60);
  assert.deepEqual(pose(), end);
});

test('a different person can replay her physics without altering a settled person', () => {
  const a = fixture(), b = fixture();
  a.sample(4); b.sample(4); const before = b.pose(), offset = b.skeleton.physicsConstraints[0].rotateOffset;
  a.sample(0); a.sample(.5);
  assert.deepEqual(b.pose(), before);
  assert.equal(b.skeleton.physicsConstraints[0].rotateOffset, offset);
});
