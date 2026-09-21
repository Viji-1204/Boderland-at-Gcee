// Radar (spec section 13). The phone sends its GPS position; the server
// answers with a rounded distance and bearing to the current target only -
// never its name or coordinates (except the start and a paid Guide).
//
// The screen is built around one rule anyone can follow: TURN UNTIL THE
// ARROW POINTS UP, THEN WALK. The arrow is drawn relative to the way the
// phone is facing, so there is nothing to know about north:
//   1. phone compass (Android: automatic; iPhone: after tapping the button),
//   2. otherwise the direction the phone is moving in (GPS), once walking,
//   3. otherwise north-up, and the screen says so - plus a direction word
//      ("North-East") and a warmer/colder bar that work without any of it.
// Every locked state (frozen, puzzle, jammed, paused...) is a plain card
// with the one thing to do next, not a padlock on a dial.
import { api } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { glyphSVG } from '../../../shared/js/suit-icons.js';
import { esc, formatClock, toast } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState } from '../live.js';

const ARROW = '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M50 6 L86 58 L61 51 L61 94 L39 94 L39 51 L14 58 Z" fill="currentColor"/></svg>';
const DIRS = ['North', 'North-East', 'East', 'South-East', 'South', 'South-West', 'West', 'North-West'];
const ALIGNED_DEG = 18; // "points up" tolerance
const WALK_M_PER_MIN = 80;

const dirWord = (bearing) => DIRS[Math.round(((bearing % 360) + 360) % 360 / 45) % 8];
const fmtDistance = (m) => (m >= 1000 ? `${(m / 1000).toFixed(m >= 10000 ? 0 : 1)}<small>km</small>` : `${m}<small>m</small>`);
const fmtWalk = (m) => { const min = Math.max(1, Math.round(m / WALK_M_PER_MIN)); return min >= 90 ? `about ${Math.round(min / 60)} h on foot` : `about ${min} min on foot`; };

// What each locked state means for the team, and the one button that helps.
const LOCKED = {
  PUZZLE: { title: 'Solve the puzzle first', text: 'You scanned the checkpoint - the radar switches on again when its puzzle is solved.', icon: 'puzzle', action: ['OPEN THE PUZZLE', '#/puzzle'] },
  FROZEN: { title: "You're frozen", text: 'A rival froze your team. The radar and scanner come back when the timer ends.', icon: 'freeze', clock: 'frozen_until', tone: 'cold' },
  JAMMED: { title: 'Radar jammed', text: 'A rival scrambled your radar. You can still walk, scan and solve puzzles - or use a Guide to cut through it.', icon: 'jam', clock: 'jammed_until', tone: 'warn', action: ['MY POWERS', '#/powers'] },
  START_TIME: { title: 'Your start time', text: 'Teams sharing a start set off a little apart. Head to your starting checkpoint - the radar opens when the timer ends.', icon: 'guide', clock: 'start_at', action: ['WHERE DO I START?', '#/home'] },
  PAUSED: { title: 'Game paused', text: 'Stay where you are. The coordinators will resume shortly.', icon: 'lock' },
  NOT_STARTED: { title: 'Not started yet', text: 'The radar switches on when the coordinators start the game.', icon: 'lock', action: ['BACK TO HOME', '#/home'] },
  ENDED: { title: 'Game over', text: 'The hunt has ended - see the results.', icon: 'trophy', action: ['RESULTS', '#/leaderboard'] },
  COMPLETED: { title: 'Joker found!', text: 'The hunt is over for you - well played.', icon: 'joker', action: ['LEADERBOARD', '#/leaderboard'] },
  DISQUALIFIED: { title: 'Disqualified', text: 'Please see a coordinator.', icon: 'lock' },
  NOT_IN_GAME: { title: 'Not in the game yet', text: 'Please see a coordinator.', icon: 'lock' },
  NO_FINAL: { title: 'Find the Joker', text: "Head to the coordinators' bench.", icon: 'joker' },
  NO_ROUTE: { title: 'Route not set up', text: 'Please see a coordinator.', icon: 'lock' },
};

export function renderRadar(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.radar)}
    <div class="r2-body r2-radar" id="radar-body">
      <div class="r2-eyebrow r2-radar-target" id="target-label">Radar</div>
      <div id="radar-main"><div class="spinner" style="margin:40px auto;"></div></div>
    </div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const $ = (sel) => root.querySelector(sel);
  const labelEl = $('#target-label');
  const mainEl = $('#radar-main');

  let pos = null; // {lat, lng, accuracy}
  let compassHeading = null; // from the magnetometer
  let gpsHeading = null; // from movement
  let last = null; // last server answer
  let watchId = null;
  let pollTimer = null;
  let clockTimer = null;
  let stopped = false;
  let geoError = '';
  let shownAngle = 0; // the arrow's cumulative rotation, so it never spins the long way round
  let view = ''; // which layout is on screen, to avoid rebuilding it every tick
  let hintUrl = null; // object URL of the revealed checkpoint photo
  let hintBusy = false;
  const iosCompass = typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function';
  let compassAsked = false;

  const heading = () => (compassHeading != null ? compassHeading : gpsHeading);
  const headingSource = () => (compassHeading != null ? 'compass' : gpsHeading != null ? 'gps' : 'none');

  // ---- the arrow -------------------------------------------------------------

  function rotateArrow(el, target) {
    const delta = ((target - shownAngle + 540) % 360) - 180; // shortest way round
    shownAngle += delta;
    el.style.transform = `rotate(${shownAngle}deg)`;
  }

  function directionLine(r) {
    const h = heading();
    const word = dirWord(r.bearing_deg);
    if (h == null) {
      return { cls: '', text: `Head ${word.toUpperCase()}`, sub: 'No compass yet: the top of the screen is North. Walk a few steps and the arrow will follow your direction.' };
    }
    const off = Math.abs((((r.bearing_deg - h) % 360) + 540) % 360 - 180);
    if (off <= ALIGNED_DEG) return { cls: 'aligned', text: 'WALK STRAIGHT AHEAD', sub: `Towards the ${word}` };
    const rel = (((r.bearing_deg - h) % 360) + 360) % 360;
    return { cls: '', text: rel < 180 ? 'TURN RIGHT' : 'TURN LEFT', sub: 'until the arrow points straight up, then walk' };
  }

  function heatLevel(r) {
    if (r.near) return 5;
    const d = r.distance_m;
    return d <= 100 ? 4 : d <= 250 ? 3 : d <= 600 ? 2 : 1;
  }

  function statusLine(r) {
    const acc = pos && pos.accuracy ? `GPS ±${Math.round(pos.accuracy)} m` : 'GPS on';
    const src = { compass: 'Compass on', gps: 'Direction from your movement', none: 'No compass - top of the screen is North' }[headingSource()];
    return `${src} · ${acc}`;
  }

  // ---- layouts ---------------------------------------------------------------------

  function guidePanelHTML(r) {
    if (!(r.guided && r.target)) return '';
    const head = r.is_start && !r.guide_until
      ? 'START HERE · your first checkpoint'
      : 'GUIDE · ends in <span class="mono" data-until="' + esc(r.guide_until || '') + '">--:--</span>';
    return `
      <div class="r2-guide">
        <div class="r2-eyebrow">${head}</div>
        <div class="r2-guide-name">${esc(r.target.name || 'Your next checkpoint')}</div>
        <div class="r2-guide-meta">${r.needs_location ? '' : `${r.distance_m} m · `}${esc(dirWord(r.bearing_deg || 0))} of you</div>
        <a class="cta-btn" href="${esc(r.target.maps_url)}" target="_blank" rel="noopener">${glyphSVG('map', { size: 18, stroke: 2 })} OPEN IN GOOGLE MAPS</a>
      </div>`;
  }

  function buttonsHTML(r, near) {
    return `
      <div class="r2-radar-buttons">
        <button class="cta-btn ${near ? '' : 'ghost'}" id="scan-btn" type="button">${glyphSVG('scan', { size: 18, stroke: 2 })} ${near ? 'FOUND THE QR - SCAN IT' : 'SCAN THE QR CODE'}</button>
        ${iosCompass && !compassAsked && compassHeading == null ? '<button class="cta-btn ghost" id="compass-btn" type="button">TURN ON THE COMPASS</button>' : ''}
      </div>`;
  }

  function hintPanelHTML(r) {
    const h = r.photo_hint;
    if (!h || r.is_final) return '';
    if (h.revealed) {
      return `
        <div class="r2-hint-photo" id="hint-photo">
          <div class="r2-eyebrow">PHOTO OF THE SPOT · ${h.remaining} hint${h.remaining === 1 ? '' : 's'} left</div>
          <div class="r2-hint-img"><div class="spinner"></div></div>
        </div>`;
    }
    if (h.usable_here) {
      return `
        <button class="cta-btn ghost r2-photo-hint-btn" id="hint-btn" type="button">
          ${glyphSVG('camera', { size: 18, stroke: 2 })} CAN'T FIND IT? SHOW ME A PHOTO <span class="mono">(${h.remaining} left)</span>
        </button>`;
    }
    return h.reason ? `<div class="r2-hint-off">${glyphSVG('camera', { size: 14, stroke: 2 })} ${esc(h.reason)}</div>` : '';
  }

  async function loadHintPhoto() {
    const box = mainEl.querySelector('#hint-photo .r2-hint-img');
    if (!box) return;
    try {
      if (hintUrl) URL.revokeObjectURL(hintUrl);
      hintUrl = URL.createObjectURL(await api.team.photoHintImage());
      box.innerHTML = `<img src="${hintUrl}" alt="Photo of the checkpoint" />`;
    } catch (err) {
      box.innerHTML = `<p class="muted" style="font-size:.8rem;">${esc(err.message)}</p>`;
    }
  }

  async function askForHint() {
    if (hintBusy) return;
    hintBusy = true;
    try {
      const res = await api.team.photoHint(pos ? { lat: pos.lat, lng: pos.lng, accuracy: pos.accuracy } : {});
      toast(res.message, { success: true });
      view = ''; // rebuild the near card with the photo
      await poll();
    } catch (err) {
      toast(err.message, { error: true, duration: 5000 });
    } finally {
      hintBusy = false;
    }
  }

  function wireButtons() {
    const hint = mainEl.querySelector('#hint-btn');
    if (hint) hint.addEventListener('click', askForHint);
    if (mainEl.querySelector('#hint-photo')) loadHintPhoto();
    const scan = mainEl.querySelector('#scan-btn');
    if (scan) scan.addEventListener('click', () => navigate('#/scan'));
    const compass = mainEl.querySelector('#compass-btn');
    if (compass) compass.addEventListener('click', enableIosCompass);
    const locate = mainEl.querySelector('#locate-btn');
    if (locate) locate.addEventListener('click', () => { stopGps(); startGps(); });
    mainEl.querySelectorAll('[data-goto]').forEach((b) => b.addEventListener('click', () => navigate(b.dataset.goto)));
  }

  function renderLocked(r) {
    const spec = LOCKED[r.code] || { title: 'Radar off', text: r.reason, icon: 'lock' };
    const until = spec.clock ? r[spec.clock] : null;
    const key = `locked:${r.code}:${until || ''}`;
    if (view !== key) {
      view = key;
      mainEl.innerHTML = `
        <div class="r2-locked-card ${spec.tone || ''}">
          <div class="r2-locked-icon">${glyphSVG(spec.icon, { size: 44, stroke: 1.6 })}</div>
          <div class="r2-locked-title">${esc(spec.title)}</div>
          ${until ? `<div class="countdown-face r2-locked-clock" data-until="${esc(until)}">--:--</div>` : ''}
          <p class="r2-locked-text">${esc(spec.text)}</p>
          ${spec.action ? `<button class="cta-btn" type="button" data-goto="${spec.action[1]}">${esc(spec.action[0])}</button>` : ''}
        </div>
        ${r.code === 'JAMMED' ? buttonsHTML(r, false) : ''}`;
      wireButtons();
    }
    labelEl.textContent = r.target_label || 'Radar';
    tickClocks();
  }

  function renderNeedsLocation(r) {
    const key = 'needs-location';
    if (view !== key) {
      view = key;
      mainEl.innerHTML = `
        <div class="r2-locked-card">
          <div class="r2-locked-icon">${glyphSVG('radar', { size: 44, stroke: 1.6 })}</div>
          <div class="r2-locked-title">Turn on location</div>
          <p class="r2-locked-text" id="geo-text"></p>
          <button class="cta-btn" type="button" id="locate-btn">ALLOW LOCATION</button>
        </div>
        ${guidePanelHTML(r)}
        ${buttonsHTML(r, false)}`;
      wireButtons();
    }
    labelEl.textContent = r.target_label || 'Radar';
    mainEl.querySelector('#geo-text').textContent = geoError
      || (window.isSecureContext ? 'The radar needs your GPS position to point the way.' : 'Location needs a secure (https://) link - or localhost when testing.');
  }

  function renderActive(r) {
    const near = Boolean(r.near);
    const ph = r.photo_hint || {};
    const key = `active:${near ? 'near' : 'far'}:${r.guided ? 'g' : ''}:${iosCompass && !compassAsked && compassHeading == null ? 'c' : ''}:${ph.revealed ? 'p' : ph.usable_here ? 'u' : ph.reason || ''}`;
    if (view !== key) {
      view = key;
      mainEl.innerHTML = near
        ? `
          <div class="r2-near-card">
            <div class="r2-near-pulse">${glyphSVG('scan', { size: 46, stroke: 1.8 })}</div>
            <div class="r2-near-title">YOU'RE HERE</div>
            <p class="r2-near-text">${r.is_final ? 'Find the coordinators and the Joker!' : 'The checkpoint is within a few steps. Look around for the QR sticker and scan it.'}</p>
          </div>
          ${hintPanelHTML(r)}
          ${guidePanelHTML(r)}
          ${buttonsHTML(r, true)}`
        : `
          <div class="r2-arrow-box" id="arrow-box">
            <span class="r2-north" id="north-mark">N</span>
            <div class="r2-arrow" id="arrow">${ARROW}</div>
          </div>
          <div class="r2-instruction" id="instruction">--</div>
          <div class="r2-instruction-sub" id="instruction-sub"></div>
          <div class="r2-distance-row">
            <div class="r2-distance" id="distance">--</div>
            <div class="r2-walk" id="walk"></div>
          </div>
          <div class="r2-heat" id="heat">${[1, 2, 3, 4, 5].map((i) => `<span data-i="${i}"></span>`).join('')}</div>
          <div class="r2-heat-label" id="heat-label"></div>
          <div class="r2-status-line" id="status-line"></div>
          ${guidePanelHTML(r)}
          ${buttonsHTML(r, false)}`;
      wireButtons();
    }
    labelEl.textContent = (r.guided && !r.is_start ? 'GUIDE · ' : '') + (r.target_label || 'Radar');
    if (near) { tickClocks(); return; }

    const box = mainEl.querySelector('#arrow-box');
    const h = heading();
    rotateArrow(mainEl.querySelector('#arrow'), h == null ? r.bearing_deg : r.bearing_deg - h);
    box.classList.toggle('north-up', h == null);
    const line = directionLine(r);
    box.classList.toggle('aligned', line.cls === 'aligned');
    mainEl.querySelector('#instruction').textContent = line.text;
    mainEl.querySelector('#instruction').className = `r2-instruction ${line.cls}`;
    mainEl.querySelector('#instruction-sub').textContent = line.sub;
    mainEl.querySelector('#distance').innerHTML = fmtDistance(r.distance_m);
    mainEl.querySelector('#walk').textContent = fmtWalk(r.distance_m);
    const level = heatLevel(r);
    mainEl.querySelectorAll('#heat span').forEach((el) => el.classList.toggle('on', Number(el.dataset.i) <= level));
    mainEl.querySelector('#heat').dataset.level = String(level);
    mainEl.querySelector('#heat-label').textContent = r.proximity;
    mainEl.querySelector('#status-line').textContent = statusLine(r);
    tickClocks();
  }

  function render() {
    const r = last;
    if (!r) return;
    if (r.locked) renderLocked(r);
    else if (r.needs_location) renderNeedsLocation(r);
    else renderActive(r);
  }

  function tickClocks() {
    mainEl.querySelectorAll('[data-until]').forEach((el) => {
      const left = (Date.parse(el.dataset.until) - api.getServerNow()) / 1000;
      el.textContent = left > 0 ? formatClock(left) : '00:00';
      if (left <= 0 && !el.dataset.done) { el.dataset.done = '1'; setTimeout(poll, 800); }
    });
  }

  // ---- data ------------------------------------------------------------------------

  async function poll() {
    if (stopped) return;
    try {
      last = await api.team.radar(pos?.lat, pos?.lng, pos?.accuracy);
      render();
    } catch (err) {
      const el = mainEl.querySelector('#instruction-sub') || mainEl.querySelector('.r2-locked-text');
      if (el) el.textContent = err.message;
    }
  }

  function startGps() {
    if (!navigator.geolocation) {
      geoError = 'This browser has no location support.';
      render();
      return;
    }
    watchId = navigator.geolocation.watchPosition(
      (p) => {
        const first = !pos;
        geoError = '';
        pos = { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
        // Direction of travel is only meaningful while actually walking.
        const moving = typeof p.coords.speed === 'number' && p.coords.speed >= 0.6;
        gpsHeading = moving && typeof p.coords.heading === 'number' && !Number.isNaN(p.coords.heading) ? p.coords.heading : gpsHeading;
        if (first) poll(); else render();
      },
      (err) => {
        geoError = err.code === 1 ? 'Location is blocked for this site. Allow it in the browser settings, then tap the button.' : 'Waiting for a GPS fix - step into the open.';
        render();
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 },
    );
  }

  function stopGps() {
    if (watchId != null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }

  function onOrientation(e) {
    let h = null;
    if (typeof e.webkitCompassHeading === 'number') h = e.webkitCompassHeading; // iOS
    else if (e.absolute && typeof e.alpha === 'number') h = (360 - e.alpha) % 360; // Android
    if (h != null) {
      compassHeading = h;
      if (last && !last.locked && !last.needs_location) render();
    }
  }

  function startCompass() {
    window.addEventListener('deviceorientationabsolute', onOrientation, true);
    window.addEventListener('deviceorientation', onOrientation, true);
  }

  async function enableIosCompass() {
    compassAsked = true;
    try {
      if ((await DeviceOrientationEvent.requestPermission()) === 'granted') startCompass();
    } catch (_) { /* denied: the arrow falls back to movement / north-up */ }
    view = ''; // rebuild without the button
    render();
  }

  if (!iosCompass) startCompass();
  startGps();
  poll();
  pollTimer = setInterval(poll, 3000);
  clockTimer = setInterval(tickClocks, 1000);
  const unsubscribe = onState(() => poll()); // puzzle solved / frozen / jammed / guided -> re-check at once

  return () => {
    stopped = true;
    unsubscribe();
    clearInterval(pollTimer);
    clearInterval(clockTimer);
    stopGps();
    if (hintUrl) URL.revokeObjectURL(hintUrl);
    window.removeEventListener('deviceorientationabsolute', onOrientation, true);
    window.removeEventListener('deviceorientation', onOrientation, true);
  };
}
