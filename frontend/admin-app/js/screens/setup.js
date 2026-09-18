// Event setup: settings, final destination, power prices. The checkpoints
// themselves (GPS points, photos) are in Setup Routes.
import { api } from '../../../shared/js/api.js';
import { esc, toast } from '../../../shared/js/ui.js';
import { guarded, pill } from '../common.js';

const SETTING_FIELDS = [
  ['radar_near_radius_m', 'Radar "goal is near" radius (m)', 'number'],
  ['freeze_duration_s', 'Freeze duration (s)', 'number'],
  ['attack_response_window_s', 'Attack response window (s)', 'number'],
  ['staggered_start_offset_s', 'Stagger for shared starts (s)', 'number'],
  ['starting_power_points', 'Starting power points', 'number'],
  ['puzzle_cooldown_s', 'Puzzle retry cooldown (s)', 'number'],
];

function myPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('No location support in this browser.')); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve(p.coords),
      (err) => reject(new Error(err.code === 1 ? 'Location permission denied.' : 'Could not get a GPS fix.')),
      { enableHighAccuracy: true, timeout: 15000 },
    );
  });
}

export function renderSetup(main, ctx) {
  main.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Event Setup</h1><div id="status"></div></div>
    <div id="setup"><div class="spinner"></div></div>`;
  const box = main.querySelector('#setup');

  async function load() {
    try {
      const [event, locations, powers] = await Promise.all([
        api.admin.event(ctx.eventId), api.admin.locations(ctx.eventId), api.admin.powers(ctx.eventId),
      ]);
      render(event, locations, powers);
    } catch (err) {
      box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  function render(event, locations, powers) {
    const draft = event.status === 'DRAFT';
    const s = event.settings;
    const inGame = locations.filter((l) => l.is_selected).length;
    main.querySelector('#status').innerHTML = pill(event.status);

    box.innerHTML = `
      ${draft ? '' : `<div class="r2-banner-note warn">The event is <strong>${event.status}</strong>, so the game's structure is locked.
        ${event.status === 'CONFIGURED' ? 'Use <em>Unlock</em> on the dashboard to change more.' : ''}</div>`}

      <div class="dash-card r2-ckpt-pointer" style="margin-bottom:16px;">
        <span class="mi">add_location_alt</span>
        <div><strong>Checkpoints: ${locations.length}</strong> (${inGame} in the game).
          GPS points and photos are set in <a href="#/setup-routes">Setup Routes</a>; the Jack, Queen and King are dealt per team on <a href="#/routes">Routes</a>.</div>
        <a class="btn" href="#/setup-routes">Open Setup Routes</a>
      </div>

      <div class="dash-card" style="margin-bottom:16px;">
        <div class="section-header"><span class="mi">settings</span> Event & rules</div>
        <form id="settings-form" class="r2-form-grid">
          <label>Event name<input name="name" value="${esc(event.name)}" maxlength="120" required /></label>
          ${SETTING_FIELDS.map(([k, label]) => `<label>${label}<input name="${k}" type="number" value="${s[k]}" required /></label>`).join('')}
          <label>Geofence on scans
            <select name="geofence_mode">
              ${['off', 'warn', 'block'].map((m) => `<option value="${m}" ${s.geofence_mode === m ? 'selected' : ''}>${m}</option>`).join('')}
            </select></label>
          <label>Attacks on frozen teams
            <select name="allow_attack_frozen">
              <option value="false" ${!s.allow_attack_frozen ? 'selected' : ''}>Blocked (default)</option>
              <option value="true" ${s.allow_attack_frozen ? 'selected' : ''}>Allowed (stacking)</option>
            </select></label>
          <div style="grid-column:1/-1;"><button class="btn primary" type="submit"><span class="mi">save</span> Save settings</button></div>
        </form>
        <p class="r2-hint-text">Geofence "warn" flags scans made far from the checkpoint; "block" rejects them (phones must share location).</p>
      </div>

      <div class="dash-card" style="margin-bottom:16px;">
        <div class="section-header"><span class="mi">playing_cards</span> Final destination - where the coordinators verify the Joker</div>
        <form id="final-form" class="r2-form-grid">
          <label>Name<input name="final_location_name" value="${esc(event.final_location_name || '')}" maxlength="120" /></label>
          <label>Latitude<input name="final_latitude" type="number" step="any" value="${event.final_latitude ?? ''}" /></label>
          <label>Longitude<input name="final_longitude" type="number" step="any" value="${event.final_longitude ?? ''}" /></label>
          <div style="grid-column:1/-1;display:flex;gap:8px;">
            <button class="btn primary" type="submit" ${draft || event.status === 'CONFIGURED' ? '' : 'disabled'}><span class="mi">save</span> Save</button>
            <button class="btn" type="button" id="final-here"><span class="mi">my_location</span> Use my current location</button>
          </div>
        </form>
      </div>

      <div class="dash-card">
        <div class="section-header"><span class="mi">bolt</span> Power prices</div>
        <form id="powers-form">
          <table class="dtable">
            <thead><tr><th>Power</th><th>Cost (points)</th><th>Max per team</th><th>Available</th></tr></thead>
            <tbody>${powers.map((p) => `
              <tr data-kind="${p.kind}">
                <td><strong>${p.kind}</strong></td>
                <td><input class="r2-inline-input" data-f="cost" type="number" min="0" value="${p.cost}" /></td>
                <td><input class="r2-inline-input" data-f="max_per_team" type="number" min="0" max="20" value="${p.max_per_team}" /></td>
                <td><input type="checkbox" data-f="active" ${p.active ? 'checked' : ''} /></td>
              </tr>`).join('')}</tbody>
          </table>
          <button class="btn primary" type="submit" ${['DRAFT', 'CONFIGURED'].includes(event.status) ? '' : 'disabled'}><span class="mi">save</span> Save prices</button>
        </form>
      </div>`;

    box.querySelector('#settings-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const settings = {};
      SETTING_FIELDS.forEach(([k]) => { settings[k] = Number(fd.get(k)); });
      settings.geofence_mode = fd.get('geofence_mode');
      settings.allow_attack_frozen = fd.get('allow_attack_frozen') === 'true';
      if (await guarded(() => api.admin.updateEvent(ctx.eventId, { name: fd.get('name'), settings }), 'Settings saved')) ctx.reload();
    });

    const finalForm = box.querySelector('#final-form');
    finalForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(finalForm);
      const body = { final_location_name: fd.get('final_location_name') };
      if (fd.get('final_latitude') !== '') body.final_latitude = Number(fd.get('final_latitude'));
      if (fd.get('final_longitude') !== '') body.final_longitude = Number(fd.get('final_longitude'));
      if (await guarded(() => api.admin.updateEvent(ctx.eventId, body), 'Final destination saved')) load();
    });
    box.querySelector('#final-here').addEventListener('click', async () => {
      try {
        const c = await myPosition();
        finalForm.final_latitude.value = c.latitude.toFixed(6);
        finalForm.final_longitude.value = c.longitude.toFixed(6);
        toast(`Got it (±${Math.round(c.accuracy)} m) - press Save`);
      } catch (err) { toast(err.message, { error: true }); }
    });

    box.querySelector('#powers-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const items = Array.from(box.querySelectorAll('tr[data-kind]')).map((row) => ({
        kind: row.dataset.kind,
        cost: Number(row.querySelector('[data-f="cost"]').value),
        max_per_team: Number(row.querySelector('[data-f="max_per_team"]').value),
        active: row.querySelector('[data-f="active"]').checked,
      }));
      if (await guarded(() => api.admin.setPowers(ctx.eventId, items), 'Prices saved')) load();
    });
  }

  load();
}
