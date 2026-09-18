// Coordinator console entry: Round 1's admin router and nav, Round 2 screens.
import { api, clearToken, getToken, onUnauthorized, syncServerTime } from '../../shared/js/api.js';
import { esc } from '../../shared/js/ui.js';
import { getEventId, setEventId } from './common.js';
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
import { renderEvents } from './screens/events.js';
import { renderAdminAccounts } from './screens/admin-accounts.js';

const root = document.getElementById('app');

const SCREENS = {
  dashboard: { render: renderDashboard, label: 'Live Dashboard', icon: 'monitoring', event: true },
  setup: { render: renderSetup, label: 'Event Setup', icon: 'tune', event: true },
  'setup-routes': { render: renderSetupRoutes, label: 'Setup Routes', icon: 'add_location_alt', event: true },
  puzzles: { render: renderPuzzles, label: 'Puzzles', icon: 'extension', event: true },
  routes: { render: renderRoutes, label: 'Routes', icon: 'route', event: true },
  teams: { render: renderTeamsAdmin, label: 'Teams', icon: 'group', event: true },
  qr: { render: renderQr, label: 'QR Codes', icon: 'qr_code_2', event: true },
  logs: { render: renderLogs, label: 'Logs', icon: 'receipt_long', event: true },
  results: { render: renderResults, label: 'Results', icon: 'emoji_events', event: true },
  events: { render: renderEvents, label: 'Events', icon: 'event' },
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
let events = [];

async function loadEvents() {
  try {
    events = await api.admin.events();
  } catch (_) {
    events = [];
  }
  const current = getEventId();
  if (!events.find((e) => e.id === current)) setEventId(events[0]?.id || '');
  return events;
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

  await loadEvents();
  const eventId = getEventId();

  root.className = 'admin-shell mode-light';
  root.innerHTML = `
    <nav class="admin-nav" id="admin-nav">
      <div class="brand">V</div>
      <div class="r2-event-switch">
        <label for="event-select">Event</label>
        <select id="event-select">
          ${events.length ? events.map((e) => `<option value="${e.id}" ${e.id === eventId ? 'selected' : ''}>${esc(e.name)} (${e.status})</option>`).join('') : '<option value="">No events yet</option>'}
        </select>
      </div>
      ${Object.entries(SCREENS).map(([k, s]) => `
        <a href="#/${k}" data-screen="${k}" class="${s.superOnly && role !== 'SUPER_ADMIN' ? 'disabled' : ''}">
          <span class="nav-icon"><span class="mi">${s.icon}</span></span> ${s.label}
        </a>`).join('')}
      <div class="role-tag">${esc(String(role).replace('_', ' '))} · ${esc(claims.username || '')} · <a href="#" id="logout-link">Log out</a></div>
    </nav>
    <main class="admin-main" id="admin-main"></main>
  `;
  root.querySelectorAll('.admin-nav a[data-screen]').forEach((a) => a.classList.toggle('active', a.dataset.screen === key));
  // On a phone the menu is one scrolling row: bring the current page's tab into view.
  root.querySelector('.admin-nav a.active')?.scrollIntoView({ block: 'nearest', inline: 'center' });
  root.querySelector('#logout-link').addEventListener('click', (e) => {
    e.preventDefault();
    clearToken('admin');
    navigate('#/login');
  });
  root.querySelector('#event-select').addEventListener('change', (e) => {
    setEventId(e.target.value);
    route();
  });

  const main = root.querySelector('#admin-main');
  if (screen.superOnly && role !== 'SUPER_ADMIN') {
    main.innerHTML = '<p class="status-note">SUPER_ADMIN only.</p>';
    return;
  }
  if (screen.event && !eventId) {
    navigate('#/events');
    return;
  }
  const ctx = {
    eventId,
    event: events.find((e) => e.id === eventId) || null,
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
