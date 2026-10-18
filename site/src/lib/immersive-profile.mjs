// Global 1.0.1 (25), scene 10007. See docs/designs/2026-10-18-immersive-home.md.
// Bind the reconstruction to exact input bytes; never unlock unknown scene packages.
const lobby = {
  id: 10007,
  camera: { fov: 19, start: [0, 0, 2], end: [0, 0, 1], target: [0, 0, 0], duration: 1 },
  background: { position: [.78, -.37, -2.48], rotation: [0, 0, 353], scale: [1, 1, 1] },
  characters: [
    { id: 2, name: '千早爱音', nameEn: 'Anon Chihaya', nodes: ['-9203547340554194180', '1543566874860172028'] },
    { id: 1, name: '高松灯', nameEn: 'Tomori Takamatsu', nodes: ['-5901079113184660740', '8614942568377332476'] },
    { id: 4, name: '长崎素世', nameEn: 'Soyo Nagasaki', nodes: ['7268099421199512316'] }
  ],
  packages: [
    {
        "01_mygo_02_lobby_01_anon_back.json": "4bb95785302ffccabcdbe4dd0f2115d7e88f032cbbdecf06448df2d4554b42ad",
        "01_mygo_02_lobby_01_anon_before.json": "f218d6572398ea80ae45093df0a79ab05d740b7ce174248d01c2169f4741d018",
        "01_mygo_02_lobby_01_soyo.json": "cd749708e45fb07432e32853d878552070d267218c1eb2f48a12e2b943fe9d62",
        "01_mygo_02_lobby_01_table.json": "9405d66f5ad90ad4c57516aac60144394cc9c669c34c846613e7263302670134",
        "01_mygo_02_lobby_01_tomori_back.json": "f8348910b660823eb93d89fb35b75d638d745bf93680894f64fc52840be5ae6a",
        "01_mygo_02_lobby_01_tomori_before.json": "a44edce52d97a85cc45062f04c2c006545843a3fecaeb2d4189e53b1df462300",
        "background.webp": "588d54d8e8820ae14b5e345d8c9304260bd7e02ff6b984c271d854b3fc6d9dd8",
        "characters.atlas": "290b1afed3a60befa7b8e07ba901277fe90925f4b0ad8986fff362dd8b8bbfbb",
        "characters.webp": "8f88e6d9313e35bf2b6eb8330e7a4d958ef3adcb6f21645564ab04c73975cc9d",
        "poster.webp": "89c7ac1d560fe884a91cee8cabbe84b273a1af60c4a15c1e6e5e7a37051ebb93",
        "scene.json": "06743c8dcbd0769efd7d0c3ce6315d8288c93d5544b127eb81da1fb39651ac64"
    },
    {
        "../shared/t--1586070576559010383-a058d014115d.webp": "374d7328a379b009930ea0ffb8dbedaf22a812ead2d13db323f32c57f9ad69dd",
        "../shared/t--7377477482447697237-a058d014115d.webp": "22eaa5de5192d6de42127de7791e7d11dcc55479469d274a3f7e493d18ebe5cf",
        "a-5804445911411708950.atlas": "244069dc407d99ebdb90480d2f9e02fdd9267afb5bd03265494eb28c5ef0905c",
        "poster.webp": "f4e5f31b6c43957a60bc39ef25aca094c7be48c4fabbe8233fca7b747360943d",
        "s--3818126645997712365.json": "d84e74b94d54742c3e905fa0fe961226f820106e53f8f0d0e95bca4d04e30327",
        "s--5480456665878750966.json": "5fab21b479304a3adb7fb9210d75f567de15506704a6d1850db2c05b7df41343",
        "s--5646794770564093312.json": "1d9dbc959efe336c3e3465f0aefd524b39467e58b8a581f3c9313bdcd06ee68d",
        "s--7391226498102374502.json": "b0b066a23c0deacba6c62c4f4221954d1158a8cc5c9eb7701936ec3a27ecec05",
        "s-1094249083465937324.json": "fb7388cb6c08fec1c23a15514ba8accbbda61896974acbc80d53b2ad07e16303",
        "s-2557303169801795355.json": "d9b21a022f74909c0c2204d14043bd7ef39bde2a33b1d7989bed9068d786ebba",
        "scene.json": "6c2e782c4528ea4ab691eee4bfd4d10593216b07c89780d7f16c944007a79dc5"
    }
]
};

export function immersiveClientProfile(scene) {
  return Number(scene.id) === lobby.id && /\/(?:mygo-lobby-v1|scene-10007-v1)\/$/.test(scene.assetRoot ?? '') ? lobby : null;
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
