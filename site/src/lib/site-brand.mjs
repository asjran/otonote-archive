// Website identity is independent of the game title in content snapshots.
export const SITE_NAME = 'OtoNote';
export const GAME_NAME = 'BanG Dream! Our Notes';

export function siteDescription(locale = 'zh-CN') {
  return locale === 'en'
    ? `${SITE_NAME} is an unofficial fan resource for ${GAME_NAME}, with character data, music and team tools.`
    : `${SITE_NAME} 是 ${GAME_NAME} 的非官方资料站，提供角色、音乐与配队工具。`;
}
