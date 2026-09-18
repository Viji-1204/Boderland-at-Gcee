// The two separate trails from spec section 23: what the system decided
// (game_events) vs what a human overrode (admin_actions).
import { api } from '../../../shared/js/api.js';
import { esc } from '../../../shared/js/ui.js';
import { fmtTime } from '../common.js';

export function renderLogs(main, ctx) {
  let tab = 'game';
  main.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Activity & Audit Logs</h1>
      <div class="btn-row"><label style="font-size:.8rem;display:flex;gap:6px;align-items:center;"><input type="checkbox" id="auto" checked /> Auto-refresh</label></div></div>
    <div class="r2-tabs">
      <button class="btn active" data-tab="game"><span class="mi">sports_esports</span> Game events (automatic)</button>
      <button class="btn" data-tab="admin"><span class="mi">gavel</span> Coordinator actions (manual)</button>
    </div>
    <div class="dash-card"><div id="log-body"><div class="spinner"></div></div></div>`;
  const body = main.querySelector('#log-body');

  async function load() {
    try {
      const rows = await api.admin.logs(ctx.eventId, tab, 500);
      body.innerHTML = rows.length ? `
        <table class="dtable">
          <thead><tr><th>Time</th><th>Type</th>${tab === 'admin' ? '<th>By</th>' : ''}<th>Team</th><th>Details</th></tr></thead>
          <tbody>${rows.map((r) => `
            <tr><td class="mono">${fmtTime(r.at)}</td><td><span class="pill NOT_STARTED">${esc(r.kind)}</span></td>
            ${tab === 'admin' ? `<td>${esc(r.admin)}</td>` : ''}<td>${esc(r.team_name || '-')}</td><td>${esc(r.message || '')}</td></tr>`).join('')}
          </tbody>
        </table>` : '<div class="empty-state">Nothing logged yet.</div>';
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  main.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => {
    tab = b.dataset.tab;
    main.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('active', x === b));
    body.innerHTML = '<div class="spinner"></div>';
    load();
  }));
  const timer = setInterval(() => { if (main.querySelector('#auto')?.checked) load(); }, 8000);
  load();
  return () => clearInterval(timer);
}
