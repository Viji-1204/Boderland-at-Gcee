// Coordinator console entry: Round 1's admin router and nav, Round 2 screens.
import { api, clearToken, getToken, onUnauthorized, syncServerTime } from '../../shared/js/api.js';
import { esc } from '../../shared/js/ui.js';
import { renderLogin } from './screens/login.js';
import { renderDashboard } from './screens/dashboard.js';
import { renderSetup } from './screens/setup.js';
import { renderSetupRoutes } from './screens/setup-routes.js';
import { renderPuzzles } from './screens/puzzles.js';
import { renderRoutes } from './screens/routes.js';
import { renderTeamsAdmin } from './screens/teams-admin.js';
import { renderQr } from './screens/qr.js';
import { renderLogs } from './screens/logs.js';
import { renderResults } from './screens/results.js';
import { renderAdminAccounts } from './screens/admin-accounts.js';

const root = document.getElementById('app');

const SCREENS = {
  dashboard: { render: renderDashboard, label: 'Live Dashboard', icon: 'monitoring' },
  setup: { render: renderSetup, label: 'Game Setup', icon: 'tune' },
  'setup-routes': { render: renderSetupRoutes, label: 'Setup Routes', icon: 'add_location_alt' },
  puzzles: { render: renderPuzzles, label: 'Puzzles', icon: 'extension' },
  routes: { render: renderRoutes, label: 'Routes', icon: 'route' },
  teams: { render: renderTeamsAdmin, label: 'Teams', icon: 'group' },
  qr: { render: renderQr, label: 'QR Codes', icon: 'qr_code_2' },
  logs: { render: renderLogs, label: 'Logs', icon: 'receipt_long' },
  results: { render: renderResults, label: 'Results', icon: 'emoji_events' },
  admins: { render: renderAdminAccounts, label: 'Admin Accounts', icon: 'admin_panel_settings', superOnly: true },
};

function decodeToken(token) {
  try {
    const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(part + '='.repeat((4 - (part.length % 4)) % 4)));
  } catch {
    return null;
  }
}

export function navigate(hash) {
  if (location.hash === hash) route(); else location.hash = hash;
}

onUnauthorized((kind) => {
  if (kind === 'admin' && !location.hash.startsWith('#/login')) navigate('#/login');
});

let cleanup = null;
let theEvent = null; // the one game; its id addresses every per-game call

async function loadEvent() {
  try {
    theEvent = await api.admin.theEvent();
  } catch (_) {
    theEvent = null;
  }
  return theEvent;
}

async function route() {
  if (typeof cleanup === 'function') {
    try { cleanup(); } catch (_) { /* gone */ }
  }
  cleanup = null;

  const name = (location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]) || 'dashboard';
  const token = getToken('admin');

  if (name === 'login' || !token) {
    if (token) { navigate('#/dashboard'); return; }
    if (name !== 'login') { location.hash = '#/login'; return; }
    root.className = 'admin-shell mode-light login-mode';
    root.innerHTML = '<div class="login-wrap" id="login-mount"></div>';
    cleanup = renderLogin(root.querySelector('#login-mount'), navigate) ?? null;
    return;
  }

  const claims = decodeToken(token);
  if (!claims || claims.type !== 'admin') {
    clearToken('admin');
    location.hash = '#/login';
    return;
  }
  const role = claims.role;
  const screen = SCREENS[name] || SCREENS.dashboard;
  const key = SCREENS[name] ? name : 'dashboard';

  await loadEvent();
  const eventId = theEvent ? theEvent.id : '';

  root.className = 'admin-shell mode-light';
  root.innerHTML = `
    <nav class="admin-nav" id="admin-nav">
      <div class="brand">V</div>
      <div class="r2-event-switch">
        <label>Game</label>
        <div class="r2-game-name">${theEvent ? `Round 2 <span class="pill ${theEvent.status}">${esc(theEvent.status)}</span>` : '<span class="bad">Server unreachable</span>'}</div>
        <button type="button" class="r2-logout-mini" id="logout-mini" title="Log out" aria-label="Log out"><span class="mi">logout</span></button>
      </div>
      <div class="admin-nav-links">
        ${Object.entries(SCREENS).map(([k, s]) => `
          <a href="#/${k}" data-screen="${k}" class="${s.superOnly && role !== 'SUPER_ADMIN' ? 'disabled' : ''}">
            <span class="nav-icon"><span class="mi">${s.icon}</span></span> ${s.label}
          </a>`).join('')}
      </div>
      <div class="role-tag">${esc(String(role).replace('_', ' '))} · ${esc(claims.username || '')} · <a href="#" id="logout-link">Log out</a></div>
    </nav>
    <main class="admin-main" id="admin-main"></main>
  `;
  root.querySelectorAll('.admin-nav a[data-screen]').forEach((a) => a.classList.toggle('active', a.dataset.screen === key));
  // On a phone the menu is one scrolling row: bring the current page's tab into view.
  root.querySelector('.admin-nav a.active')?.scrollIntoView({ block: 'nearest', inline: 'center' });
  const logout = (e) => {
    e.preventDefault();
    clearToken('admin');
    navigate('#/login');
  };
  root.querySelector('#logout-link').addEventListener('click', logout);
  root.querySelector('#logout-mini').addEventListener('click', logout);

  const main = root.querySelector('#admin-main');
  // Wide tables (teams, results, logs...) scroll inside their own box, so
  // the page itself never scrolls sideways on a phone. Screens render
  // asynchronously, so watch for tables as they appear.
  const wrapTables = () => main.querySelectorAll('table.dtable').forEach((table) => {
    if (table.closest('.r2-table-scroll')) return;
    const box = document.createElement('div');
    box.className = 'r2-table-scroll';
    table.replaceWith(box);
    box.appendChild(table);
  });
  new MutationObserver(wrapTables).observe(main, { childList: true, subtree: true });
  if (screen.superOnly && role !== 'SUPER_ADMIN') {
    main.innerHTML = '<p class="status-note">SUPER_ADMIN only.</p>';
    return;
  }
  if (!eventId && !screen.superOnly) {
    main.innerHTML = '<p class="status-note error">The game could not be loaded from the server. Check the connection and refresh.</p>';
    return;
  }
  const ctx = {
    eventId,
    event: theEvent,
    role,
    username: claims.username,
    isSuper: role === 'SUPER_ADMIN',
    navigate,
    reload: route,
  };
  cleanup = screen.render(main, ctx) ?? null;
}

window.addEventListener('hashchange', route);
syncServerTime().finally(route);
