import {withServer} from './game-servers.mjs';

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const number = (value, min, max, optional = false) => optional && value == null
  || Number.isSafeInteger(value) && value >= min && value <= max;

export function rankingScoreAnomaly(score) {
  return score === 2147483647 ? 'score-int32-max' : null;
}

export function validateHighScoreDeck(deck) {
  if (deck == null) return;
  if (!object(deck) || !number(deck.totalPower, 1, 2147483647, true)
    || !Array.isArray(deck.cards) || deck.cards.length > 5) throw Error('Invalid high score deck');
  const slots = new Set(), orders = new Set();
  for (const row of deck.cards) {
    if (!object(row) || !number(row.slot, 0, 4) || slots.has(row.slot)
      || !number(row.performanceOrder, 0, 4) || orders.has(row.performanceOrder)) throw Error('Invalid deck slot');
    slots.add(row.slot); orders.add(row.performanceOrder);
    for (const kind of ['member', 'support']) {
      const card = row[kind];
      if (card == null) continue;
      if (!object(card) || !number(card.masterId, 1, Number.MAX_SAFE_INTEGER)
        || !number(card.exp, 0, 2147483647, true) || !number(card.rank, 1, 5, true)
        || kind === 'member' && ['awake', 'liveSkillLevel', 'performanceSkillLevel'].some(key => !number(card[key], 1, 5, true))) {
        throw Error('Invalid deck card');
      }
    }
  }
}

export function rankingCard(kind, masterId, catalog) {
  if (!['member', 'support'].includes(kind)) return undefined;
  return catalog?.[kind]?.[String(masterId)];
}

const profileHosts = new Set(['l14-prod-hk-patch-sirius.gamerfusiontech.com','l12-prod-hk-patch-sirius.gamerfusiontech.com',
  'l14-prod-sg-patch-sirius.bilibiligame.net','l12-prod-sg-patch-sirius.bilibiligame.net']);
export function validatePlayerProfile(profile) {
  if (profile == null) return;
  if (!object(profile) || !number(profile.avatarMasterId,1,Number.MAX_SAFE_INTEGER,true)
    || !Array.isArray(profile.profileCardImages) || profile.profileCardImages.length > 8) throw Error('Invalid public profile');
  for (const image of profile.profileCardImages) {
    if (typeof image !== 'string' || image.length > 2048 || /[\u0000-\u0020]/.test(image)) throw Error('Invalid profile image');
    const url = new URL(image);
    if (url.protocol !== 'https:' || !profileHosts.has(url.hostname) || url.username || url.password || url.search || url.hash
      || url.port && url.port !== '443') throw Error('Invalid profile image');
  }
}

export function orderedDeckSlots(deck) {
  return Array.from({length: 5}, (_, slot) => deck?.cards?.find(row => row.slot === slot) ?? {
    slot, performanceOrder: null, member: null, support: null,
  });
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

export function createRankingRow(entry, {en, catalog, server, scoreLabel}) {
  const language = en ? 'en-US' : 'zh-CN', format = value => value.toLocaleString(language);
  const deck = entry.highScoreDeck, known = Boolean(deck?.cards?.length);
  const row = node('li', 'pr-row');
  row.dataset.playerRank = String(entry.rank);
  if (entry.rank <= 3) row.dataset.podium = String(entry.rank);
  const details = node('details', 'pr-player');
  const summary = node('summary', 'pr-summary');
  const rank = node('span', 'pr-rank', format(entry.rank));
  rank.setAttribute('aria-label', `${en ? 'Rank' : '排名'} ${entry.rank}`);
  const player = node('span', 'pr-player-name', entry.name || (en ? 'Unnamed player' : '未命名玩家'));
  const identity = node('span','pr-identity');
  const avatar = node('span','pr-avatar');
  const avatarInfo = rankingCard('member',entry.profile?.avatarMasterId,catalog);
  if (avatarInfo?.image) {
    const image = node('img');image.src = avatarInfo.image;image.alt = en ? 'Player avatar' : '玩家头像';image.loading = 'lazy';image.decoding = 'async';
    image.addEventListener('error',()=>avatar.replaceChildren(node('span','',entry.name?.slice(0,1) || '♪')),{once:true});avatar.append(image);
  } else avatar.append(node('span','',entry.name?.slice(0,1) || '♪'));
  identity.append(avatar,player);
  const profileImages = entry.profile?.profileCardImages || [];
  if (profileImages.length) {
    const namecard = node('span','pr-profile-card');const image = node('img');
    let index = profileImages.length - 1;
    image.src = profileImages[index];image.alt = en ? 'Player profile card' : '玩家名片';image.loading = 'lazy';image.decoding = 'async';image.referrerPolicy = 'no-referrer';
    image.addEventListener('error',()=>{if (--index >= 0) image.src = profileImages[index];else namecard.remove();});namecard.append(image);identity.append(namecard);
  }
  const team = node('span', 'pr-team-preview');
  team.setAttribute('aria-label', en ? 'High-score team members' : '最高分队伍成员');

  function portrait(card, kind, compact = false) {
    const info = card && rankingCard(kind, card.masterId, catalog);
    const label = info?.name || (card ? `${en ? 'Card' : '卡片'} #${card.masterId}` : (en ? 'Not provided' : '未提供'));
    const frame = node('span', `pr-portrait${compact ? ' pr-portrait--small' : ''}`);
    frame.title = label;
    if (info?.image) {
      const image = node('img'); image.src = info.image; image.alt = label;
      image.loading = 'lazy'; image.decoding = 'async'; image.width = 72; image.height = 96;
      image.addEventListener('error', () => { frame.replaceChildren(node('span', 'pr-image-fallback', card ? `#${card.masterId}` : '—')); }, {once:true});
      frame.append(image);
    } else frame.append(node('span', 'pr-image-fallback', card ? `#${card.masterId}` : '—'));
    return frame;
  }

  if (known) for (const slot of orderedDeckSlots(deck)) team.append(portrait(slot.member, 'member', true));
  else team.append(node('span', 'pr-team-missing', en ? 'Team not provided' : '队伍未提供'));
  const stat = (className, label, value) => {
    const box = node('span', className); box.append(node('small', '', label), node('strong', '', value)); return box;
  };
  const power = stat('pr-power', en ? 'Team power' : '综合力', deck?.totalPower ? format(deck.totalPower) : '—');
  const score = stat('pr-score', scoreLabel, format(entry.score));
  const anomaly = rankingScoreAnomaly(entry.score);
  const anomalyReason = en
    ? 'Score reaches the signed 32-bit integer limit (2,147,483,647).'
    : '分数达到 32 位有符号整数上限（2,147,483,647）。';
  if (anomaly) {
    const badge = node('span', 'pr-score-warning', en ? 'Unusual score' : '成绩异常');
    badge.title = anomalyReason;
    badge.dataset.rule = anomaly;
    score.append(badge);
  }
  const toggle = node('span', 'pr-expand');
  toggle.append(node('span', 'pr-open-label', en ? 'View team' : '查看队伍'), node('span', 'pr-close-label', en ? 'Collapse' : '收起队伍'));
  summary.append(rank, identity, team, power, score, toggle);
  details.append(summary); row.append(details);

  function detailCard(card, kind) {
    const info = card && rankingCard(kind, card.masterId, catalog);
    const box = node('div', 'pr-detail-card');
    const title = info?.name || (card ? `${en ? 'Card' : '卡片'} #${card.masterId}` : (en ? 'Not provided' : '未提供'));
    const link = node(info?.href ? 'a' : 'div', 'pr-card-link');
    if (info?.href) link.href = withServer(info.href, server);
    link.append(portrait(card, kind), node('span', 'pr-card-name', title)); box.append(link);
    const stats = node('dl', 'pr-card-stats');
    const add = (label, value) => { const pair = node('div'); pair.append(node('dt', '', label), node('dd', '', value)); stats.append(pair); };
    if (card) {
      if (card.rank != null) add(en ? 'Limit break' : '突破', `${card.rank}/5`);
      if (kind === 'member' && card.awake != null) add(en ? 'Awakening' : '觉醒', `${card.awake}/5`);
      if (kind === 'member') {
        if (card.liveSkillLevel != null) add(en ? 'Live skill' : '演出技能', `Lv. ${card.liveSkillLevel}`);
        if (card.performanceSkillLevel != null) add(en ? 'Performance skill' : '表演技能', `Lv. ${card.performanceSkillLevel}`);
      }
    }
    if (stats.childElementCount) box.append(stats); return box;
  }

  details.addEventListener('toggle', () => {
    if (!details.open || details.dataset.built) return;
    details.dataset.built = 'true';
    const panel = node('div', 'pr-deck-panel');
    const heading = node('div', 'pr-deck-heading');
    heading.append(node('h3', '', en ? 'Highest-score team' : '最高分队伍'),
      node('p', '', en ? 'Team and power saved with this score.' : '取得该成绩时保存的编成与综合力。'));
    panel.append(heading);
    if (anomaly) panel.append(node('p', 'pr-score-warning-detail', anomalyReason + (en
      ? ' Automatically flagged for this score; this is not a confirmed cheating verdict.'
      : ' 此标记由成绩规则自动判定，不代表已确认作弊。')));
    if (!known) panel.append(node('p', 'pr-detail-empty', en ? 'This snapshot did not include a team.' : '本次采集未取得这位玩家的队伍信息。'));
    else {
      const slots = node('div', 'pr-deck-slots');
      for (const slot of orderedDeckSlots(deck)) {
        const cell = node('section', 'pr-deck-slot');
        cell.append(node('h4', '', `${en ? 'Slot' : '位置'} ${slot.slot + 1}`),
          node('p', 'pr-order', slot.performanceOrder == null ? '—' : `${en ? 'Performance order' : '演出顺序'} ${slot.performanceOrder + 1}`),
          node('span', 'pr-card-kind', en ? 'Member' : '成员'), detailCard(slot.member, 'member'),
          node('span', 'pr-card-kind pr-support-label', en ? 'Support' : '留影'), detailCard(slot.support, 'support'));
        slots.append(cell);
      }
      panel.append(slots);
    }
    details.append(panel);
  });
  return row;
}
