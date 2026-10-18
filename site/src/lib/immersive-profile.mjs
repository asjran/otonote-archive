import profiles from './immersive-client-profiles.json' with { type: 'json' };

// Native camera settings and member bindings are byte-bound to reviewed packages.
export function immersiveClientProfile(scene, region = 'global') {
  if (region !== 'global') return null;
  const profile = profiles[String(scene.id)];
  const folder = (scene.assetRoot ?? '').replace(/\/$/, '').split('/').at(-1);
  return profile?.folders.includes(folder) ? profile : null;
}

export async function verifyImmersiveClientProfile(resources, profile) {
  if (resources.manifest.sceneId !== profile.id || !resources.sceneBlob) throw Error('scene-profile-mismatch');
  const sha256 = async blob => [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
  const sceneDigest = await sha256(resources.sceneBlob);
  const files = profile.packages.find(files => files['scene.json'] === sceneDigest);
  if (!files) throw Error('scene-profile-mismatch');
  const blobs = new Map(resources.blobs); blobs.set('scene.json', resources.sceneBlob);
  await Promise.all([...blobs].map(async ([name, blob]) => {
    const expected = files[name];
    if (!expected) throw Error('scene-profile-mismatch');
    const digest = await sha256(blob);
    if (digest !== expected) throw Error('scene-profile-mismatch');
  }));
  for (const name of Object.keys(files)) if (name !== 'poster.webp' && !blobs.has(name)) throw Error('scene-profile-mismatch');
  return profile;
}
