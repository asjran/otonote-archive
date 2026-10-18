import { Physics, MixBlend, MixDirection } from '@esotericsoftware/spine-threejs';

// Advance secondary motion on a fixed clock. Rendering a fractional frame must
// not integrate physics again: seeks, person replays and exports can revisit it.
export function createSpinePoseSampler(skeleton, animation) {
  const physical = skeleton.physicsConstraints.length > 0;
  let step = -1;
  function apply(time, previous, physics) {
    skeleton.setToSetupPose();
    animation?.apply(skeleton, previous, time, false, null, 1, MixBlend.setup, MixDirection.mixIn);
    skeleton.updateWorldTransform(physics);
  }
  return time => {
    if (!physical) { apply(time, -1, Physics.pose); return; }
    const target = Math.floor(time * 60 + 1e-7);
    if (step < 0 || target < step) {
      skeleton.time = 0;
      for (const constraint of skeleton.physicsConstraints) constraint.reset();
      apply(0, -1, Physics.reset); step = 0;
    }
    while (step < target) {
      const previous = step / 60;
      skeleton.time = ++step / 60;
      apply(skeleton.time, previous, Physics.update);
    }
    apply(time, time, Physics.pose);
  };
}
