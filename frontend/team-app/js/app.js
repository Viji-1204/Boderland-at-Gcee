// Team app entry: Round 1's hash router, Round 2 screens.
import { getToken, onUnauthorized, syncServerTime } from '../../shared/js/api.js';
import { setNavigate, startLive, stopLive } from './live.js';
import { renderLogin } from './screens/login.js';
import { renderHome } from './screens/home.js';
import { renderScan } from './screens/scan.js';
import { renderPuzzle } from './screens/puzzle.js';
import { renderRadar } from './screens/radar.js';
import { renderRoute } from './screens/route.js';
import { renderPowers } from './screens/powers.js';
import { renderSentence } from './screens/sentence.js';
import { renderLeaderboard } from './screens/leaderboard.js';
import { renderAccount } from './screens/account.js';
import { renderResults } from './screens/results.js';

const root = document.getElementById('app');

// hash -> { render(root, navigate, params), mode: 'light'|'dark', auth }
const ROUTES = {
  '#/login': { render: renderLogin, mode: 'light', auth: false },
  '#/home': { render: renderHome, mode: 'dark', auth: true },
  '#/scan': { render: renderScan, mode: 'dark', auth: true },
  '#/puzzle': { render: renderPuzzle, mode: 'light', auth: true },
  '#/radar': { render: renderRadar, mode: 'light', auth: true },
  '#/route': { render: renderRoute, mode: 'light', auth: true },
  '#/powers': { render: renderPowers, mode: 'light', auth: true },
  '#/sentence': { render: renderSentence, mode: 'light', auth: true },
  '#/leaderboard': { render: renderLeaderboard, mode: 'dark', auth: true },
  '#/account': { render: renderAccount, mode: 'light', auth: true },
  '#/results': { render: renderResults, mode: 'dark', auth: true },
};

export function navigate(hash) {
  if (location.hash === hash) route(); else location.hash = hash;
}
setNavigate(navigate);

onUnauthorized((kind) => {
  if (kind === 'team') {
    stopLive();
    if (!location.hash.startsWith('#/login')) navigate('#/login');
  }
});

let cleanup = null;

function route() {
  if (typeof cleanup === 'function') {
    try { cleanup(); } catch (_) { /* screen already gone */ }
  }
  cleanup = null;

  const hash = location.hash || (getToken('team') ? '#/home' : '#/login');
  const [path, query] = hash.split('?');
  const entry = ROUTES[path];
  if (!entry) {
    location.hash = getToken('team') ? '#/home' : '#/login';
    return;
  }
  if (entry.auth && !getToken('team')) {
    // A QR scanned with the phone's normal camera opens #/scan?c=...; keep it for after login.
    if (path === '#/scan' && query) sessionStorage.setItem('bl2_pending_scan', hash);
    location.hash = '#/login';
    return;
  }
  if (path === '#/login' && getToken('team')) {
    location.hash = '#/home';
    return;
  }
  if (entry.auth) startLive();

  root.className = `app-shell mode-${entry.mode}`;
  root.innerHTML = '';
  cleanup = entry.render(root, navigate, new URLSearchParams(query || '')) ?? null;
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
syncServerTime().finally(route);
