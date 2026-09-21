// Event setup: settings, final destination, power prices. The checkpoints
// themselves (GPS points, photos) are in Setup Routes.
import { api } from '../../../shared/js/api.js';
import { POWER_FAMILIES, POWERS, powerDesc } from '../../../shared/js/copy.js';
import { esc, toast } from '../../../shared/js/ui.js';
import { guarded, pill } from '../common.js';

const SETTING_FIELDS = [
  ['radar_near_radius_m', 'Radar "goal is near" radius (m)', 'number'],
  ['attack_response_window_s', 'Attack response window (s)', 'number'],
  ['freeze_duration_s', 'Freeze: how long a team is frozen (s)', 'number'],
  ['jam_duration_s', 'Jam: how long a radar is jammed (s)', 'number'],
  ['ward_duration_s', 'Ward: how long it protects (s)', 'number'],
  ['guide_duration_s', 'Guide: how long the target is shown (s)', 'number'],
  ['staggered_start_offset_s', 'Stagger for shared starts (s)', 'number'],
  ['starting_power_points', 'Starting power points', 'number'],
  ['puzzle_cooldown_s', 'Puzzle retry cooldown (s)', 'number'],
  ['photo_hints_per_team', 'Photo hints per team (0 = off)', 'number'],
  ['photo_hint_locked_last', 'No photo hints on the last N checkpoints', 'number'],
];
const FAMILY_ORDER = ['HELP', 'ATTACK', 'DEFENCE'];

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
    <div class="admin-topline"><h1 class="admin-h1">Game Setup</h1><div id="status"></div></div>
    <div id="setup"><div class="spinner"></div></div>`;
  const box = main.querySelector('#setup');

  async function load() {
    try {
      const [event, locations, powers] = await Promise.all([
        api.admin.event(ctx.eventId), api.admin.checkpoints(), api.admin.powers(ctx.eventId),
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
      ${draft ? '' : `<div class="r2-banner-note warn">The game is <strong>${event.status}</strong>, so its structure is locked.
        ${event.status === 'CONFIGURED' ? 'Use <em>Unlock</em> on the dashboard to change more.' : event.status === 'ENDED' ? 'Use <em>Restart game</em> on the dashboard, then <em>Unlock</em>, to set up the next run.' : ''}</div>`}

      <div class="dash-card r2-ckpt-pointer" style="margin-bottom:16px;">
        <span class="mi">add_location_alt</span>
        <div><strong>Checkpoints: ${locations.length}</strong> (${inGame} in the game).
          GPS points and photos are set in <a href="#/setup-routes">Setup Routes</a>; the Jack, Queen and King are dealt per team on <a href="#/routes">Routes</a>.</div>
        <a class="btn" href="#/setup-routes">Open Setup Routes</a>
      </div>

      <div class="dash-card" style="margin-bottom:16px;">
        <div class="section-header"><span class="mi">settings</span> Game & rules</div>
        <form id="settings-form" class="r2-form-grid">
          ${SETTING_FIELDS.map(([k, label]) => `<label>${label}<input name="${k}" type="number" value="${s[k]}" required /></label>`).join('')}
          <label>Geofence on scans
            <select name="geofence_mode">
              ${['off', 'warn', 'block'].map((m) => `<option value="${m}" ${s.geofence_mode === m ? 'selected' : ''}>${m}</option>`).join('')}
            </select></label>
          <label>Freeze a frozen team / jam a jammed radar
            <select name="allow_attack_frozen">
              <option value="false" ${!s.allow_attack_frozen ? 'selected' : ''}>Blocked (default)</option>
              <option value="true" ${s.allow_attack_frozen ? 'selected' : ''}>Allowed (stacking)</option>
            </select></label>
          <div style="grid-column:1/-1;"><button class="btn primary" type="submit"><span class="mi">save</span> Save settings</button></div>
        </form>
        <p class="r2-hint-text">Geofence "warn" flags scans made far from the checkpoint; "block" rejects them (phones must share location).
          <strong>Photo hints:</strong> a team standing at its checkpoint (radar says YOU'RE HERE) that can't find the sticker can ask for the checkpoint's photo from Setup Routes - this many times per game, never on the last N checkpoints of its route.</p>
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
        <div class="section-header"><span class="mi">bolt</span> Powers - prices and limits</div>
        <p class="r2-hint-text" style="margin:0 0 10px;">Teams spend their starting points (${s.starting_power_points}) in the shop before the start. Durations are set above.
          <strong>Help</strong>: for the team itself. <strong>Attack</strong>: the rival gets ${s.attack_response_window_s}s to Shield or Reflect it. <strong>Defence</strong>: Shield/Reflect answer an attack; a Ward is raised in advance.</p>
        <form id="powers-form">
          <table class="dtable">
            <thead><tr><th>Family</th><th>Power</th><th>What it does</th><th>Cost (points)</th><th>Max per team</th><th>Available</th></tr></thead>
            <tbody>${FAMILY_ORDER.flatMap((fam) => powers.filter((p) => p.family === fam)).map((p) => `
              <tr data-kind="${p.kind}">
                <td>${pill(p.family === 'ATTACK' ? 'DISQUALIFIED' : p.family === 'DEFENCE' ? 'WAITING' : 'LIVE', (POWER_FAMILIES[p.family] || { en: p.family }).en)}</td>
                <td><strong>${esc((POWERS[p.kind] || { en: p.label }).en)}</strong><div class="r2-hint-text mono">${p.kind}</div></td>
                <td class="r2-hint-text" style="max-width:320px;">${esc(powerDesc(p.kind, s))}</td>
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
      if (await guarded(() => api.admin.updateEvent(ctx.eventId, { settings }), 'Settings saved')) ctx.reload();
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
