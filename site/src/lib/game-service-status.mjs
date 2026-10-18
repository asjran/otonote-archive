import {currentServerContext, gameServer} from './game-servers.mjs';

export function maintenanceNotice(observation, locale = 'zh', now = Date.now()) {
  if (observation?.status !== 'maintenance') return '';
  const en = locale === 'en';
  const end = Date.parse(observation.maintenance?.expectedEndAt);
  const time = Number.isFinite(end) ? new Intl.DateTimeFormat(en ? 'en-GB' : 'zh-CN', {
    timeZone:'Asia/Shanghai', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false
  }).format(end) : null;
  return en ? `Official game maintenance. Online reads are paused.${time ? end <= now
    ? ' The expected end time has passed; recovery is not confirmed.' : ` Expected end: ${time} (UTC+8).` : ''}`
    : `游戏官方维护中，在线读取暂时停止。${time ? end <= now
      ? '预计结束时间已过，等待官方恢复确认。' : `预计 ${time}（UTC+8）结束。` : ''}`;
}

export function installGameServiceNotice(root) {
  if (!root) return;
  const locale = root.dataset.locale, en = locale === 'en';
  let disposed = false, inFlight = false, timer, controller;
  const events = new AbortController();
  const refresh = async () => {
    if (disposed || inFlight) return;
    clearTimeout(timer);
    inFlight = true;
    const request = controller = new AbortController();
    const timeout = setTimeout(() => request.abort(), 9000);
    try {
      const response = await fetch('/api/growth-export/status/', {
        credentials:'omit', cache:'no-store', signal:request.signal
      });
      if (!response.ok) throw Error();
      const data = await response.json();
      if (data.schemaVersion !== 1 || !data.servers || Date.parse(data.validUntil) <= Date.now()
          || !Number.isFinite(Date.parse(data.validUntil))) throw Error();
      if (disposed) return;
      const {serverId} = currentServerContext();
      const selected = serverId ? [[serverId,data.servers[serverId]]] : Object.entries(data.servers);
      const affected = selected.filter(([,row]) => row?.status === 'maintenance');
      if (affected.length) {
        const names = affected.map(([id]) => en ? gameServer(id)?.englishLabel : gameServer(id)?.label).filter(Boolean);
        root.querySelector('[data-game-service-message]').textContent = `${names.join(' / ')} · ${maintenanceNotice(affected[0][1],locale)}`;
        root.querySelector('[data-game-service-detail]').textContent = en
          ? 'Browsing, team planning and local imports remain available.' : '资料浏览、配队和本地文件导入仍可使用。';
        root.hidden = false;
      } else {
        const uncertain = selected.some(([,row]) => row?.status !== 'no_maintenance_signal');
        if (!root.hidden && uncertain) throw Error();
        root.hidden = true;
      }
      window.dispatchEvent(new CustomEvent('game-service-status-change',{detail:data}));
    } catch {
      if (!disposed && !root.hidden) {
        root.querySelector('[data-game-service-message]').textContent = en
          ? 'Game status could not be refreshed; recovery is not confirmed.' : '游戏状态暂时无法更新，尚不能确认维护已经结束。';
        window.dispatchEvent(new CustomEvent('game-service-status-change', {detail:{servers:{}}}));
      }
    } finally {
      clearTimeout(timeout);
      inFlight = false;
      if (!disposed) timer = setTimeout(refresh,60000);
    }
  };
  const stop = () => { disposed=true; clearTimeout(timer); controller?.abort(); events.abort(); };
  window.addEventListener('pagehide',event => { if (!event.persisted) stop(); },{signal:events.signal});
  window.addEventListener('pageshow',event => { if (event.persisted) refresh(); },{signal:events.signal});
  document.addEventListener('ournotes:shell-dispose',stop,{once:true,signal:events.signal});
  refresh();
  return stop;
}
