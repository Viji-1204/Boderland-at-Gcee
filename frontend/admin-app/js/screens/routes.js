// Route table (spec sections 5 and 6): generate, review, edit one team by hand.
// Generating also deals each team its own Jack, Queen and King: three of its
// stops, picked at random, in visit order. The edit modal can move them.
import { api } from '../../../shared/js/api.js';
import { esc } from '../../../shared/js/ui.js';
import { confirmModal, guarded, openModal, pill } from '../common.js';

const FACES = ['JACK', 'QUEEN', 'KING'];
const title = (face) => face[0] + face.slice(1).toLowerCase();

export function renderRoutes(main, ctx) {
  main.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Routes</h1>
      <div class="btn-row"><button class="btn primary" id="generate"><span class="mi">shuffle</span> Generate routes</button></div></div>
    <div id="routes"><div class="spinner"></div></div>`;
  const box = main.querySelector('#routes');
  let data = null;

  async function load() {
    try {
      data = await api.admin.routes(ctx.eventId);
      render();
    } catch (err) {
      box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  function render() {
    const draft = data.status === 'DRAFT';
    main.querySelector('#generate').disabled = !draft;
    const cap = data.capacity;
    const poolCount = data.selected_locations.length;
    const locCount = data.route_length || poolCount; // stops per team
    box.innerHTML = `
      <div class="r2-banner-note ${cap && cap.feasible ? 'info' : 'warn'}"><strong>Each team visits ${locCount} of the ${poolCount} checkpoints in the game</strong>, in its own order - a different selection per team. Change the pool in <a href="#/setup-routes">Setup Routes</a> and the route length in <a href="#/setup">Game Setup</a>.${cap ? ` ${esc(cap.message)}` : ' Put some checkpoints in the game first.'}</div>
      ${data.problems.length ? `<div class="r2-banner-note bad"><strong>Needs attention:</strong><br>${data.problems.map(esc).join('<br>')}</div>` : (data.teams.length ? '<div class="r2-banner-note info">Every route is valid and unique, and every team holds its own Jack, Queen and King in that order.</div>' : '')}
      ${draft ? '' : `<div class="r2-banner-note warn">The event is ${data.status} - routes are locked.</div>`}
      <div class="dash-card" style="overflow-x:auto;">
        <table class="dtable">
          <thead><tr><th>Team</th><th>Start</th>${Array.from({ length: locCount }, (_, i) => `<th>${i + 1}</th>`).join('')}<th></th></tr></thead>
          <tbody>
            ${data.teams.map((t) => `
              <tr>
                <td><strong>${esc(t.team_name)}</strong><div class="r2-hint-text mono">${esc(t.team_code)} ${t.status === 'DISQUALIFIED' ? pill('DISQUALIFIED') : ''}</div></td>
                <td class="mono">${t.start_offset_s ? `+${t.start_offset_s}s` : '0'}</td>
                ${t.stops.length ? t.stops.map((s) => `<td class="r2-route-cell">${esc(s.code)}${s.face_card ? ` <span class="face" title="${title(s.face_card)}">${s.face_card[0]}</span>` : ''}</td>`).join('') : `<td colspan="${locCount}" class="r2-hint-text">no route</td>`}
                <td>${draft && t.status !== 'DISQUALIFIED' ? `<button class="btn tiny" data-edit="${t.team_id}"><span class="mi mi-sm">edit</span></button>` : ''}</td>
              </tr>`).join('') || `<tr><td colspan="${locCount + 3}" class="empty-state">No teams yet.</td></tr>`}
          </tbody>
        </table>
        <p class="r2-hint-text">J/Q/K mark where each team meets its Jack, Queen and King - dealt at random per team when routes are generated, so they differ from team to team. Teams that share a start get a staggered start time (shown as +seconds).</p>
      </div>`;

    box.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', () => editRoute(b.dataset.edit)));
  }

  function editRoute(teamId) {
    const team = data.teams.find((t) => t.team_id === teamId);
    const locs = data.selected_locations;
    const current = team.stops.map((s) => s.location_id);
    const holder = (face) => (team.stops.find((s) => s.face_card === face) || {}).location_id || '';
    const locCount = data.route_length || locs.length;
    const rows = Array.from({ length: locCount }, (_, i) => `
      <label style="display:flex;gap:10px;align-items:center;margin-bottom:6px;font-size:.8rem;">
        <span class="mono" style="width:24px;">${i + 1}</span>
        <select name="pos${i}" style="flex:1;padding:6px;border:1px solid #dee2e6;border-radius:6px;">
          ${locs.map((l) => `<option value="${l.id}" ${current[i] === l.id ? 'selected' : ''}>${esc(l.code)} · ${esc(l.name)}</option>`).join('')}
        </select>
      </label>`).join('');
    const faces = FACES.map((face) => `
      <label style="display:flex;gap:10px;align-items:center;margin-bottom:6px;font-size:.8rem;">
        <span class="mono" style="width:24px;font-weight:800;color:#b91c1c;">${face[0]}</span>
        <select name="${face}" style="flex:1;padding:6px;border:1px solid #dee2e6;border-radius:6px;">
          ${locs.map((l) => `<option value="${l.id}" ${holder(face) === l.id ? 'selected' : ''}>${esc(l.code)} · ${esc(l.name)}</option>`).join('')}
        </select>
      </label>`).join('');
    openModal(`Edit route - ${team.team_name}`, `
      <p class="r2-hint-text">${locCount} different checkpoints from the ones in the game; not identical to another team's route. Position 1 is the starting checkpoint.</p>
      ${rows}
      <p class="r2-hint-text" style="margin-top:12px;"><strong>This team's face cards.</strong> Three different checkpoints, visited in the order Jack, Queen, King.</p>
      ${faces}`, {
      submitLabel: 'Save route',
      onSubmit: async (fd) => {
        const ids = Array.from({ length: locCount }, (_, i) => fd.get(`pos${i}`));
        const cards = Object.fromEntries(FACES.map((face) => [face, fd.get(face)]));
        const res = await guarded(() => api.admin.setRoute(ctx.eventId, teamId, ids, cards), 'Route saved');
        if (!res) return false;
        data = res;
        render();
        return true;
      },
    });
  }

  main.querySelector('#generate').addEventListener('click', async () => {
    const hasRoutes = data && data.teams.some((t) => t.stops.length);
    if (hasRoutes && !(await confirmModal('Regenerate every route? Manual edits will be replaced.', { okLabel: 'Regenerate' }))) return;
    const res = await guarded(() => api.admin.generateRoutes(ctx.eventId), 'Routes generated');
    if (res) { data = res; render(); }
  });

  load();
}
