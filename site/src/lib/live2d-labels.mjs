const words = {
  casual: ['私服', 'Casual'], spring: ['春季', 'Spring'], summer: ['夏季', 'Summer'], winter: ['冬季', 'Winter'],
  school: ['校服', 'School'], hs: ['高中', 'High school'], jhs: ['初中', 'Middle school'],
  '1st': ['一年级', 'Year 1'], '2nd': ['二年级', 'Year 2'], '3rd': ['三年级', 'Year 3'],
  live: ['演出服', 'Stage outfit'], low: ['轻量版', 'Lite'], roomwear: ['睡衣', 'Roomwear'],
  arbeit: ['工作服', 'Workwear'], livehouse: ['Live house', 'Live house'], ring: ['RiNG', 'RiNG'],
  glasses: ['眼镜', 'Glasses'], nose: ['鼻子道具', 'Prop nose'], hat: ['帽子', 'Hat'], sunglasses: ['墨镜', 'Sunglasses'],
  mask: ['面具', 'Mask'], silhouette: ['剪影', 'Silhouette'], child: ['幼年', 'Childhood'],
  still: ['静态造型', 'Still variant'], virtual: ['虚拟形象', 'Virtual'], soundonly: ['语音占位', 'Voice-only'],
  hairdown: ['披发', 'Hair down'], twintails: ['双马尾', 'Twin tails'], detective: ['侦探', 'Detective'],
  caretaker: ['看护服', 'Caretaker'], idol: ['偶像服', 'Idol'], suits: ['西装', 'Suit'], sweat: ['运动服', 'Sweats'],
  marukun: ['丸君', 'Maru-kun'], maid: ['女仆服', 'Maid'],
};
const clips = {
  idle: ['待机', 'Idle'], angry: ['生气', 'Angry'], bye: ['告别', 'Goodbye'],
  nod: ['点头', 'Nod'], question: ['疑问', 'Question'], sad: ['难过', 'Sad'], serious: ['认真', 'Serious'],
  smile: ['微笑', 'Smile'], bsmile: ['笑容', 'Smile'], cry: ['哭泣', 'Cry'], heart: ['爱心', 'Heart'],
  kime: ['定格姿势', 'Pose'], look: ['注视', 'Look'], kirakira: ['闪亮', 'Sparkle'], pale: ['脸色苍白', 'Pale'],
  panic: ['慌张', 'Panic'], shadow: ['阴影', 'Shadow'], shy: ['害羞', 'Shy'], spin: ['眩晕', 'Dizzy'],
  surprised: ['惊讶', 'Surprised'], thinking: ['思考', 'Thinking'], talk: ['说话', 'Talk'],
};

export function modelLabel(model, en = false) {
  const family = model.modelPath.split('/')[0];
  let name = model.modelPath.split('/').at(-1);
  if (family.startsWith('sub_')) name = name.replace(`adv_live2d_${family}_`, '');
  else name = name.replace(/^(?:adv_)?live2d_[a-z]+_\d+_/, '');
  const label = name.split('_').map(word => words[word]?.[en ? 1 : 0] || word).join(' · ');
  const usage = model.usage === 'live' ? (en ? 'Live' : '舞台模型') : (en ? 'Story' : '剧情模型');
  return `${label} — ${usage}${model.isDefault ? (en ? ' · Default' : ' · 默认') : ''}${model.state !== 'available' ? (en ? ' · Unavailable' : ' · 暂不可用') : ''}`;
}

export function clipLabel(name, en = false) {
  const match = name.replace(/^\d+-/, '').match(/^(?:mtn|exp)_(\D+?)(\d+)(?:_([CLR]))?$/);
  if (!match || !clips[match[1]]) return name;
  const direction = match[3] && { C: ['正面', 'Center'], L: ['左侧', 'Left'], R: ['右侧', 'Right'] }[match[3]][en ? 1 : 0];
  return `${clips[match[1]][en ? 1 : 0]} ${Number(match[2])}${direction ? ` · ${direction}` : ''} / ${name}`;
}

export function preferredMotion(motions) {
  const index = motions.findIndex(m => /(?:^|_)idle\d*(?:_C)?$/i.test(m.sourceName));
  return index < 0 ? 0 : index;
}
