import test from 'node:test';
import assert from 'node:assert/strict';
import { Skeleton, SkeletonJson, Physics, MixBlend, MixDirection } from '@esotericsoftware/spine-threejs';
import { composeSpineDrawOrder, pointInTriangle } from '../src/lib/immersive-composition.mjs';
import profiles from '../src/lib/immersive-client-profiles.json' with { type: 'json' };
import { createImmersivePlayback } from '../src/lib/immersive-playback.mjs';

test('shared people retain full constraint poses and the authored interleaved slot order', () => {
  const data = new SkeletonJson({}).readSkeletonData({
    skeleton: { spine: '4.2.67' },
    bones: [{ name: 'root' }, { name: 'shared', parent: 'root' },
      { name: 'a', parent: 'shared', x: 5 }, { name: 'b', parent: 'shared', x: -5 },
      { name: 'target', parent: 'root', x: 3, y: 10 }],
    slots: [{ name: 'a-back', bone: 'a' }, { name: 'b', bone: 'b' },
      { name: 'a-front', bone: 'a' }, { name: 'table', bone: 'shared' }],
    ik: [{ name: 'hand', bones: ['a'], target: 'target', mix: 1 }],
    animations: { entrance: { bones: { shared: { translate: [{ x: 0 }, { time: 4, x: 20 }] },
      target: { translate: [{ x: 0 }, { time: 4, x: 20, y: -10 }] } } } }
  });
  const scene = new Skeleton(data), a = new Skeleton(data), b = new Skeleton(data);
  const sample = (skeleton, time) => {
    skeleton.setToSetupPose();
    data.animations[0].apply(skeleton, -1, time, false, null, 1, MixBlend.setup, MixDirection.mixIn);
    skeleton.updateWorldTransform(Physics.update);
  };
  sample(scene, 4); sample(a, 1); sample(b, 4);
  const order = composeSpineDrawOrder(scene, new Map([[1, a], [2, b]]), [1, 2, 1, null]);
  assert.deepEqual(order.map(s => s.data.name), ['a-back', 'b', 'a-front', 'table']);
  assert.equal(order[0].bone.skeleton, a);
  assert.equal(order[2].bone, order[0].bone);
  assert.equal(order[1].bone.skeleton, b);
  assert.equal(order[3].bone.skeleton, scene);
  assert.notEqual(a.bones[1].worldX, b.bones[1].worldX);
  assert.notEqual(a.bones[2].a, b.bones[2].a); // IK target belongs to the independently sampled full pose.
  const before = [b.bones[2].worldX, b.bones[2].a, scene.bones[1].worldX];
  sample(a, 2);
  assert.deepEqual([b.bones[2].worldX, b.bones[2].a, scene.bones[1].worldX], before);
  assert.throws(() => composeSpineDrawOrder(scene, new Map(), [1, 2, 1, null]), /slot-unavailable/);
});

test('hit testing handles either winding and rejects collapsed or distant triangles', () => {
  assert.equal(pointInTriangle(1, 1, 0, 0, 5, 0, 0, 5), true);
  assert.equal(pointInTriangle(1, 1, 0, 5, 5, 0, 0, 0), true);
  assert.equal(pointInTriangle(0, 0, 0, 0, 5, 0, 0, 5), true);
  assert.equal(pointInTriangle(9, 9, 0, 0, 5, 0, 0, 5), false);
  assert.equal(pointInTriangle(9, 9, 0, 0, 0, 0, 0, 0), false);
});

test('every reviewed scene has complete, disjoint runnable character bindings', () => {
  assert.equal(Object.keys(profiles).length, 39);
  let members = 0, shared = 0;
  for (const profile of Object.values(profiles)) {
    const layers = new Map();
    for (const c of profile.characters) {
      members++;
      assert.ok(c.nodes.length, `${profile.id}/${c.id}: empty member`);
      for (const node of c.nodes) {
        const partition = profile.partitions[node];
        if (partition) assert.ok(partition.slots.includes(c.id), `${profile.id}/${c.id}: missing visible shared slots`);
        const id = partition ? `${node}@${c.id}` : node;
        assert.equal(layers.has(id), false, `${profile.id}: duplicated character layer`);
        layers.set(id, { id, duration: 4, apply() {} });
      }
    }
    for (const [id, partition] of Object.entries(profile.partitions)) {
      shared++;
      layers.set(id, { id, duration: 4, apply() {} });
      for (const owner of new Set(partition.slots.filter(x => x !== null))) {
        assert.ok(profile.characters.some(c => c.id === owner && c.nodes.includes(id)));
      }
    }
    const characters = profile.characters.map(c => ({ ...c, nodes: c.nodes.map(id => profile.partitions[id] ? `${id}@${c.id}` : id) }));
    const clock = createImmersivePlayback([...layers.values()], characters);
    clock.seek(4);
    for (const c of characters) {
      clock.replay(c.id); clock.advance(.2);
      for (const other of clock.characters) if (other.id !== c.id) assert.equal(other.time, 4);
      clock.seek(4);
    }
    assert.equal(profile.camera.ease, 9);
    assert.ok(profile.packages.length && profile.folders.length);
  }
  assert.equal(members, 150);
  assert.equal(shared, 9);
  // This back layer contains only Arare, despite the native controller's ArareRitsu name.
  assert.equal(profiles['30006'].characters.find(c => c.id === 13).nodes.includes('8632064090355800901'), false);
});
