export function createGameSkin(manifest, base = '/') {
  const url = name => {
    const value = manifest.images[name]?.url;
    if (!value) throw new Error(`Missing game skin texture: ${name}`);
    return value.startsWith('/content/') ? value : `${base.replace(/\/$/, '')}${value}`;
  };
  const slices = name => ({ leftUrl: url(`notes_${name}_side_L`), centerUrl: url(`notes_${name}_side_0`), rightUrl: url(`notes_${name}_side_R`) });
  return {
    theme: {
      palette: { top: '#0a152d', middle: '#142d4b', bottom: '#080e21', track: '10, 18, 42', lane: '110, 199, 242' },
      backgroundUrl: url('live_stage_bg_sprite'),
      laneSkin: { baseUrl: url('lane_base'), tapAreaUrl: url('lane_tap_area'), outsideLineUrl: url('out_side_line') },
      noteSkin: {
        tap: slices('tap'), flick: slices('flick'), flickLeft: slices('flick_left'), flickRight: slices('flick_right'),
        slide: slices('slide'), slideEnd: slices('slide_end'), slideConnection: slices('slide_connection'), trace: slices('trace'),
        arrows: {
          left: [5, 7, 10, 13, 16, 19, 21, 99].map((maxWidth, i) => ({ maxWidth, url: url(`notes_flick_arrow_left_${String(i + 1).padStart(2, '0')}`) })),
          right: [5, 7, 10, 13, 16, 19, 21, 99].map((maxWidth, i) => ({ maxWidth, url: url(`notes_flick_arrow_right_${String(i + 1).padStart(2, '0')}`) })),
          up: [5, 12, 18, 999].map((maxWidth, i) => ({ maxWidth, url: url(`notes_flick_arrow_upper_${['S', 'M', 'L', 'LL'][i]}`) }))
        },
        overlays: { tapDecorationUrl: url('tap_decoration'), slideConnectionUrl: url('slide_connection_icon'), flickDecorationUrl: url('flick_decoration'), flickLeftDecorationUrl: url('flick_left_decoration'), flickRightDecorationUrl: url('flick_right_decoration'),
          flickUpArrowUrl: url('notes_flick_arrow_upper_M'), flickLeftArrowUrl: url('notes_flick_arrow_left_04'), flickRightArrowUrl: url('notes_flick_arrow_right_04'), slideDecorationUrl: url('slide_decoration') }
      },
      effectTextures: { tapLineUrl: url('ef_tap_line'), tapPillarUrl: url('ef_tap_pillar'), particleStarUrl: url('ef_tap_particle_star') },
      judgementUrl: url('judgment_perfect')
    },
    comboSkin: { capability: 'available', digitUrls: Array.from({ length: 10 }, (_, i) => url(`SP_combo_perfect_${i}`)), labelUrl: url('SP_combo_perfect') }
  };
}

export function gameSkinUrls(skin) {
  const urls = new Set();
  const visit = value => {
    if (typeof value === 'string' && value.endsWith('.webp')) urls.add(value);
    else if (value && typeof value === 'object') Object.values(value).forEach(visit);
  };
  visit(skin);
  return [...urls];
}

const cachedImages = new Map();
export async function loadGameSkin(skin, images, { onProgress = () => {} } = {}) {
  let completed = 0;
  const urls = gameSkinUrls(skin);
  const results = await Promise.allSettled(urls.map(async url => {
    if (!cachedImages.has(url)) {
      cachedImages.set(url, new Promise((resolve, reject) => {
        const img = new Image();
        img.decoding = 'async';
        img.onload = () => resolve(img);
        img.onerror = () => { cachedImages.delete(url); reject(new Error(`Texture failed: ${url}`)); };
        img.src = url;
      }));
    }
    try { images.set(url, await cachedImages.get(url)); }
    finally { onProgress(++completed, urls.length); }
  }));
  return { total: urls.length, loaded: results.filter(result => result.status === 'fulfilled').length };
}
