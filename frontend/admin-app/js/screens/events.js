// Events (spec section 2: several independent events, e.g. Round 2 2026 / 2027).
import { api } from '../../../shared/js/api.js';
import { esc } from '../../../shared/js/ui.js';
import { confirmModal, fmtDateTime, guarded, openModal, pill, setEventId } from '../common.js';

export function renderEvents(main, ctx) {
  main.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Events</h1>
      <div class="btn-row">${ctx.isSuper ? '<button class="btn primary" id="new-event"><span class="mi">add</span> New event</button>' : ''}</div></div>
    <div id="events"><div class="spinner"></div></div>`;
  const box = main.querySelector('#events');
  let events = [];

  async function load() {
    try {
      events = await api.admin.events();
      box.innerHTML = events.length ? `
        <div class="dash-card"><table class="dtable">
          <thead><tr><th>Event</th><th>Status</th><th>Teams</th><th>Checkpoints</th><th>Created</th><th></th></tr></thead>
          <tbody>${events.map((e) => `
            <tr>
              <td><strong>${esc(e.name)}</strong>${e.id === ctx.eventId ? ' <span class="pill LIVE">selected</span>' : ''}</td>
              <td>${pill(e.status)}</td>
              <td class="mono">${e.counts.teams}</td>
              <td class="mono">${e.counts.selected_locations} of ${e.counts.locations}</td>
              <td>${fmtDateTime(e.created_at)}</td>
              <td><div class="btn-row">
                <button class="btn tiny" data-select="${e.id}"><span class="mi mi-sm">check</span> Open</button>
                ${ctx.isSuper && ['DRAFT', 'ENDED'].includes(e.status) ? `<button class="btn tiny danger" data-del="${e.id}" data-name="${esc(e.name)}"><span class="mi mi-sm">delete</span></button>` : ''}
              </div></td>
            </tr>`).join('')}</tbody>
        </table></div>` : `<div class="empty-state">No events yet. ${ctx.isSuper ? 'Create the first one.' : 'Ask a SUPER_ADMIN to create one.'}</div>`;
      box.querySelectorAll('[data-select]').forEach((b) => b.addEventListener('click', () => { setEventId(b.dataset.select); ctx.navigate('#/dashboard'); }));
      box.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
        if (!(await confirmModal(`Delete "${b.dataset.name}" and everything in it (teams, routes, logs)? This can't be undone.`, { okLabel: 'Delete event', danger: true }))) return;
        if (await guarded(() => api.admin.deleteEvent(b.dataset.del), 'Event deleted')) ctx.reload();
      }));
    } catch (err) {
      box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  const newBtn = main.querySelector('#new-event');
  if (newBtn) newBtn.addEventListener('click', () => openModal('New event', `
    <div class="field"><label class="tier-label"><span class="primary">Name</span></label><input name="name" required maxlength="120" placeholder="Round 2 - 2026" /></div>
    <div class="field"><label class="tier-label"><span class="primary">Copy setup from</span><span class="secondary">Locations, puzzles, prices and settings - with fresh QR codes. Teams (and their routes) are not copied.</span></label>
      <select name="clone"><option value="">- start empty -</option>${events.map((e) => `<option value="${e.id}">${esc(e.name)}</option>`).join('')}</select></div>`, {
    submitLabel: 'Create',
    onSubmit: async (fd) => {
      const res = await guarded(() => api.admin.createEvent(fd.get('name'), fd.get('clone') || null), 'Event created');
      if (!res) return false;
      setEventId(res.id);
      ctx.navigate('#/setup');
      return true;
    },
  }));

  load();
}
