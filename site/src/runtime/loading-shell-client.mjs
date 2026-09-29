import { SITE_NAME } from "../lib/site-brand.mjs";
import { activeNavigationGroup, activeNavigationChild, NAVIGATION_GROUPS } from '../lib/navigation.mjs';
import { loadingKind } from './loading-route.mjs';
import { loadingPresentation } from './loading-presentation.mjs';

// Inline in the entry HTML: runs before downloading any template or game data.
const english = /^\/global\/en(?:\/|$)/.test(location.pathname);
const base = `/global/${english ? 'en' : 'zh-CN'}/`;
const path = location.pathname.replace(/^\/global\/(zh-CN|en)/, '') || '/';
const root = document.documentElement;
root.lang = english ? 'en' : 'zh-CN';
if (new URLSearchParams(location.search).get('motion') === 'off') root.dataset.motion = 'off';
if (english) document.querySelectorAll('[data-loading-en]').forEach(node => { node.textContent = node.dataset.loadingEn; });
document.querySelector('[data-loading-locale]').textContent = english ? 'English' : '简体中文';
const navigation = document.querySelector('[data-site-nav]');
navigation.setAttribute('aria-label', english ? 'Main navigation' : '主导航');
document.querySelector('.site-breadcrumb').setAttribute('aria-label', english ? 'Breadcrumb' : '当前位置');
document.querySelector('.context-switcher summary').setAttribute('aria-label', english ? 'Server and language' : '切换服务器与语言');
document.querySelector('[data-loading-retry]').href = location.href;
const group = NAVIGATION_GROUPS.find(item => item.id === activeNavigationGroup(path));
const child = activeNavigationChild(path, group?.children ?? []);
const currentPath = child?.href ?? group?.href ?? (path === '/updates/' ? path : '/');
let title = english ? 'Overview' : '首页概览';
document.querySelectorAll('[data-loading-route]').forEach(link => {
  const route = link.dataset.loadingRoute;
  link.href = base + route.slice(1);
  if (route === path || (route === child?.href && path.startsWith(route))) link.setAttribute('aria-current', 'page');
  if (route === currentPath) title = link.textContent.trim();
});
const kind = loadingKind(location.pathname);
if (kind === 'detail' || kind === 'story') title += english ? ' · Details' : ' · 详情';
document.querySelectorAll('[data-loading-title]').forEach(node => { node.textContent = title; });
document.title = `${title} · ${SITE_NAME}`;
const skeleton = document.querySelector('[data-loading-skeleton]');
skeleton.dataset.loadingKind = kind;
skeleton.replaceChildren(document.querySelector(`[data-loading-template="${kind}"]`).content.cloneNode(true));
root.dataset.loadingKind = kind;
if (/^\/cards\/members\/?$/.test(path)) root.dataset.loadingCardFormat = 'member';
if (/^\/cards\/supports\/?$/.test(path)) root.dataset.loadingCardFormat = 'support';
const interlude = document.querySelector('[data-loading-interlude]');
const companion = document.querySelector('[data-loading-companion]');
const presentation = loadingPresentation(kind, english ? 'en' : 'zh-CN');
document.querySelector('[data-loading-caption]').textContent = presentation.caption;
// Decorative art is optional and never gates the ready page or its navigation.
companion.addEventListener('load', () => { companion.hidden = false; }, { once: true });
companion.addEventListener('error', () => { companion.hidden = true; }, { once: true });
companion.src = interlude.dataset.artRoot + presentation.art;

const controller = new AbortController();
const options = {signal:controller.signal};
function toggleGroup(button, expanded) {
  const submenu = document.getElementById(button.getAttribute('aria-controls'));
  button.setAttribute('aria-expanded', String(expanded));
  const name = button.closest('.nav-group').querySelector('.nav-primary').textContent.trim();
  button.setAttribute('aria-label', `${english ? (expanded ? 'Collapse navigation group: ' : 'Expand navigation group: ') : (expanded ? '收起导航分组：' : '展开导航分组：')}${name}`);
  button.querySelector('span').textContent = expanded ? '−' : '+';
  submenu.hidden = !expanded;
  submenu.inert = !expanded;
}
document.querySelectorAll('[data-loading-toggle]').forEach(button => {
  const active = button.dataset.loadingToggle === group?.id;
  let expanded = true;
  try { expanded = sessionStorage.getItem(`ournotes-nav-group:${button.dataset.loadingToggle}`) !== 'false'; } catch { /* Storage is optional. */ }
  if (active) button.closest('.nav-group').setAttribute('data-active', '');
  toggleGroup(button, active || expanded);
  button.addEventListener('click', () => {
    const next = button.getAttribute('aria-expanded') !== 'true';
    toggleGroup(button, next);
    try { sessionStorage.setItem(`ournotes-nav-group:${button.dataset.loadingToggle}`, String(next)); } catch { /* Storage is optional. */ }
  }, options);
});
if (group) document.querySelector(`[data-loading-group="${group.id}"]`)?.setAttribute('data-active', '');
const mobile = matchMedia('(max-width: 1100px)');
const menu = document.querySelector('[data-loading-menu]');
const backdrop = document.querySelector('[data-loading-backdrop]');
backdrop.setAttribute('aria-label', english ? 'Close navigation' : '关闭导航');
const background = document.querySelectorAll('#main-content,.site-brand,.site-breadcrumb,.global-search,.context-switcher');
function setMenu(open) {
  menu.setAttribute('aria-expanded', String(open));
  menu.setAttribute('aria-label', english ? (open ? 'Close navigation' : 'Open navigation') : (open ? '关闭导航' : '打开导航'));
  navigation.toggleAttribute('data-open', open);
  navigation.inert = mobile.matches && !open;
  document.body.toggleAttribute('data-nav-open', open);
  backdrop.hidden = !open;
  background.forEach(node => { node.inert = open; });
}
setMenu(false);
menu.addEventListener('click', () => {
  const open = menu.getAttribute('aria-expanded') !== 'true';
  setMenu(open);
  if (open) navigation.querySelector('a[aria-current="page"],a')?.focus();
}, options);
backdrop.addEventListener('click', () => { setMenu(false); menu.focus(); }, options);
mobile.addEventListener('change', () => setMenu(false), options);
document.addEventListener('keydown', event => {
  if (menu.getAttribute('aria-expanded') !== 'true') return;
  if (event.key === 'Escape') { setMenu(false); menu.focus(); }
  if (event.key === 'Tab') {
    const nodes = [...navigation.querySelectorAll('a,button'),menu].filter(node => node.getClientRects().length && !node.closest('[inert]'));
    const index = nodes.indexOf(document.activeElement);
    if (event.shiftKey ? index <= 0 : index < 0 || index === nodes.length - 1) {
      event.preventDefault(); nodes[event.shiftKey ? nodes.length - 1 : 0]?.focus();
    }
  }
}, options);

const errorKey = Symbol.for('ournotes.loading-error.v1');
function showError() {
  const status = document.querySelector('[data-content-status]');
  if (!status || !root.hasAttribute('data-loading')) return;
  status.querySelector('[data-loading-message]').textContent = english ? 'Content could not be loaded' : '内容暂时无法加载';
  status.setAttribute('role', 'alert');
  interlude.dataset.failed = 'true';
  document.querySelector('[data-loading-caption]').textContent = english ? 'Let’s try that again.' : '稍作停顿，再试一次。';
  status.querySelector('.loading-dot').hidden = true;
  document.querySelector('#main-content').setAttribute('aria-busy', 'false');
  skeleton.hidden = true;
  document.querySelector('[data-loading-error]').hidden = false;
}
globalThis[errorKey] = showError;
// This also recovers when the boot module itself fails to download.
const timer = setTimeout(showError, 20000);
window.addEventListener('error', event => {
  if (event.target instanceof HTMLScriptElement && /\/boot-[^/]+\.js$/.test(event.target.src)) showError();
}, {...options,capture:true});
document.addEventListener('ournotes:shell-dispose', () => {
  clearTimeout(timer); controller.abort(); setMenu(false); delete globalThis[errorKey];
}, {once:true});
