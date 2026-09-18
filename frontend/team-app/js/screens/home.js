// Dark "phone" hub from Round 1, with Round 2 apps and a glanceable status strip.
// When the game goes live it also shows the team where to begin: the
// starting checkpoint by name, the live distance from the phone's GPS, and a
// Google Maps walking route - the app sends teams to their start, not the
// volunteers.
import { api } from '../../../shared/js/api.js';
import { EVENT_STATUS, TEAM_STATUS } from '../../../shared/js/copy.js';
import { glyphSVG } from '../../../shared/js/suit-icons.js';
import { esc, formatClock, startCountdown } from '../../../shared/js/ui.js';
import { bindChrome, navHTML } from '../chrome.js';
import { onState, refresh } from '../live.js';
import { showRules, showVisa } from './modals.js';

const APPS = [
  { id: 'scan', label: 'Scanner', glyph: 'scan', suit: '♠', tone: 'red', route: '#/scan' },
  { id: 'radar', label: 'Radar', glyph: 'radar', suit: '♦', tone: 'green', route: '#/radar' },
  { id: 'puzzle', label: 'Puzzle', glyph: 'puzzle', suit: '♣', tone: 'gold', route: '#/puzzle' },
  { id: 'route', label: 'Route', glyph: 'route', suit: '♥', tone: 'blue', route: '#/route' },
  { id: 'powers', label: 'Powers', glyph: 'powers', suit: '♠', tone: 'red', route: '#/powers' },
  { id: 'sentence', label: 'Sentence', glyph: 'sentence', suit: '♦', tone: 'gold', route: '#/sentence' },
  { id: 'visa', label: 'VISA', img: '../shared/img/app_icon_visa.png' },
  { id: 'rules', label: 'Rules', img: '../shared/img/app_icon_game.png' },
];

/** The one thing the team should do next, for the status strip. */
function nextStep(s) {
  const ev = s.event.status;
  const t = s.team;
  const n = t.total_checkpoints;
  if (ev === 'DRAFT' || ev === 'CONFIGURED') {
    return { text: 'Waiting for the coordinators to start', sub: s.powers.purchase_open ? 'Buy your powers now - the shop closes when the game starts.' : '' };
  }
  if (ev === 'PAUSED') return { text: 'Game paused', sub: 'Stay where you are - the coordinators will resume shortly.' };
  if (ev === 'ENDED') return { text: 'Game over', sub: 'Tap Results to see the final standings.' };
  switch (t.status) {
    case 'FROZEN': return { text: 'FROZEN', until: t.frozen_until, sub: 'Your radar and scanner are jammed.' };
    case 'PUZZLE_LOCKED': return { text: `Solve the puzzle - checkpoint ${t.progress} of ${n}`, sub: 'The radar unlocks when you get it right.' };
    case 'ACTIVE':
      if (t.start_at && Date.parse(t.start_at) > api.getServerNow() + 1000) return { text: 'Your start time', until: t.start_at, sub: 'Teams sharing a start set off a little apart.' };
      return t.progress === 0
        ? { text: `Go to your starting checkpoint (1 of ${n})`, sub: 'Follow the map below, then scan its QR code.' }
        : { text: `Follow the radar to checkpoint ${t.progress + 1} of ${n}`, sub: 'Find its QR code and scan it.' };
    case 'FINAL': return { text: 'Find the Joker!', sub: `All checkpoints cleared - the radar points to ${s.event.final_location_name || 'the coordinators'}.` };
    case 'COMPLETED': return { text: 'Joker found - you finished!', sub: t.elapsed_s != null ? `Your time: ${formatClock(t.elapsed_s)}` : '' };
    case 'DISQUALIFIED': return { text: 'Disqualified', sub: 'Please see a coordinator.' };
    default: return { text: TEAM_STATUS[t.status]?.en || t.status, sub: '' };
  }
}

export function renderHome(root, navigate) {
  root.innerHTML = `
    <div class="phone-dashboard-container">
      <div id="r2-status" class="r2-status-card"><div class="spinner" style="margin:10px auto;"></div></div>
      <div id="r2-start"></div>
      <div class="phone-apps-view r2">
        <div class="phone-apps-grid" id="r2-apps"></div>
        <div id="r2-lobby"></div>
      </div>
    </div>
    ${navHTML('home')}
  `;
  bindChrome(root, navigate);

  const statusBox = root.querySelector('#r2-status');
  const startBox = root.querySelector('#r2-start');
  const grid = root.querySelector('#r2-apps');
  const lobby = root.querySelector('#r2-lobby');
  let stopClock = null;
  let stopStartClock = null;
  let watchId = null;
  let pos = null;
  let startTarget = null;

  // Great-circle distance in metres (same maths as the server's radar).
  function distanceM(a, b) {
    const R = 6371000;
    const p1 = (a.lat * Math.PI) / 180;
    const p2 = (b.lat * Math.PI) / 180;
    const dp = ((b.lat - a.lat) * Math.PI) / 180;
    const dl = ((b.lng - a.lng) * Math.PI) / 180;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  }

  function renderDistance() {
    const el = startBox.querySelector('#r2-start-dist');
    if (!el || !startTarget) return;
    if (!pos) { el.textContent = 'Finding your location...'; return; }
    const d = distanceM(pos, startTarget);
    const mins = Math.max(1, Math.round(d / 80)); // a brisk walk
    el.innerHTML = d <= 25
      ? "<strong>You're here</strong> - find the QR code and scan it"
      : `<strong>${Math.round(d)} m</strong> away · about ${mins} min on foot · GPS ±${Math.round(pos.accuracy || 0)} m`;
  }

  function watchGps() {
    if (watchId != null || !navigator.geolocation) return;
    watchId = navigator.geolocation.watchPosition(
      (p) => { pos = { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }; renderDistance(); },
      () => { const el = startBox.querySelector('#r2-start-dist'); if (el && !pos) el.textContent = 'Turn on location to see how far it is - or just open the map.'; },
      { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 },
    );
  }

  function stopGps() {
    if (watchId != null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }

  function renderStart(s) {
    const st = s.start;
    if (stopStartClock) stopStartClock();
    stopStartClock = null;
    if (!st) {
      startTarget = null;
      startBox.innerHTML = '';
      stopGps();
      return;
    }
    startTarget = { lat: st.latitude, lng: st.longitude };
    const waiting = st.start_at && Date.parse(st.start_at) > api.getServerNow() + 1000;
    const paused = s.event.status === 'PAUSED';
    startBox.innerHTML = `
      <div class="r2-start-card">
        <div class="r2-start-head">
          <div class="r2-eyebrow">${waiting ? 'Your start is in <span class="mono" id="r2-start-clock">--:--</span> - head there now' : 'Start here'}</div>
          <div class="r2-start-name">${glyphSVG('guide', { size: 22, stroke: 2 })} ${esc(st.name)}</div>
          <div class="r2-start-sub">Checkpoint 1 of ${st.total} · ${esc(st.code)}</div>
        </div>
        <div class="r2-start-dist" id="r2-start-dist">Finding your location...</div>
        <div class="r2-start-actions">
          <a class="cta-btn r2-start-maps" href="${esc(st.maps_url)}" target="_blank" rel="noopener">${glyphSVG('map', { size: 18, stroke: 2 })} OPEN IN GOOGLE MAPS</a>
          <button class="cta-btn ghost" type="button" id="r2-start-scan" ${waiting || paused ? 'disabled' : ''}>${paused ? 'GAME PAUSED' : waiting ? 'SCAN OPENS AT YOUR START TIME' : "I'M HERE - SCAN THE QR"}</button>
        </div>
        <div class="r2-start-note">Google Maps gives you live turn-by-turn directions. Once you're there, scan the checkpoint's QR code to begin.</div>
      </div>`;
    const scanBtn = startBox.querySelector('#r2-start-scan');
    if (scanBtn) scanBtn.addEventListener('click', () => navigate('#/scan'));
    const clock = startBox.querySelector('#r2-start-clock');
    if (clock) stopStartClock = startCountdown(st.start_at, (sec) => { clock.textContent = formatClock(sec); }, () => refresh().catch(() => {}));
    renderDistance();
    watchGps();
  }

  function renderApps(s) {
    const ended = s.event.status === 'ENDED';
    const apps = ended ? [...APPS, { id: 'results', label: 'Results', glyph: 'trophy', suit: '♥', tone: 'gold', route: '#/results' }] : APPS;
    grid.innerHTML = apps.map((a) => {
      let badge = '';
      if (a.id === 'puzzle' && s.puzzle) badge = '<span class="r2-badge-dot">!</span>';
      if (a.id === 'sentence' && s.fragments.length) badge = `<span class="r2-badge-dot">${s.fragments.length}</span>`;
      if (a.id === 'radar' && s.team.guide_until) badge = '<span class="r2-badge-dot">GO</span>';
      const icon = a.img
        ? `<div class="phone-app-card-icon"><img src="${a.img}" alt="" /></div>`
        : `<div class="r2-app-icon ${a.tone}" data-suit="${a.suit}">${glyphSVG(a.glyph, { size: 34, stroke: 1.8 })}</div>`;
      return `
        <button class="phone-app-card-btn" type="button" data-app="${a.id}" style="position:relative;">
          ${badge}${icon}
          <span class="phone-app-card-label">${a.label}</span>
        </button>`;
    }).join('');
    grid.querySelectorAll('[data-app]').forEach((btn) => {
      const app = apps.find((x) => x.id === btn.dataset.app);
      btn.addEventListener('click', () => {
        if (app.id === 'visa') showVisa();
        else if (app.id === 'rules') showRules();
        else navigate(app.route);
      });
    });
  }

  function renderStatus(s) {
    const t = s.team;
    const step = nextStep(s);
    const pillStatus = ['DRAFT', 'CONFIGURED', 'PAUSED', 'ENDED'].includes(s.event.status) ? s.event.status : t.status;
    const pillText = (EVENT_STATUS[pillStatus] || TEAM_STATUS[pillStatus] || { en: pillStatus }).en;
    const pips = s.checkpoints.map((c) => `<span class="r2-pip ${c.state}">${c.state === 'DONE' ? '✓' : c.seq}</span>`).join('');
    const joker = ['FINAL', 'COMPLETED'].includes(t.status) ? `<span class="r2-pip JOKER ${t.status === 'COMPLETED' ? 'DONE' : 'CURRENT'}">🃏</span>` : '';
    statusBox.innerHTML = `
      <div class="r2-status-top">
        <div>
          <div class="r2-team-name">${esc(t.team_name)}</div>
          <div class="r2-team-code">${esc(t.team_code)}</div>
        </div>
        <span class="r2-pill ${pillStatus}">${esc(pillText)}</span>
      </div>
      <div class="r2-next">
        <div>
          <div>${esc(step.text)} ${step.until ? '<span class="mono" id="r2-step-clock">--:--</span>' : ''}</div>
          ${step.sub ? `<div class="r2-next-sub">${esc(step.sub)}</div>` : ''}
        </div>
      </div>
      <div class="r2-pips">${pips}${joker}</div>`;
    if (stopClock) stopClock();
    stopClock = null;
    const clock = statusBox.querySelector('#r2-step-clock');
    if (clock && step.until) {
      stopClock = startCountdown(step.until, (sec) => { clock.textContent = formatClock(sec); }, () => refresh().catch(() => {}));
    }

    const lobbyNotes = [];
    if (s.event.status === 'DRAFT' || s.event.status === 'CONFIGURED') {
      lobbyNotes.push(`<strong>Before the start:</strong> open <strong>Powers</strong> to spend your ${t.power_points} power points,
        and read the <strong>Rules</strong>. Keep this screen open - it updates by itself when the game begins.`);
    }
    lobby.innerHTML = lobbyNotes.map((n) => `<div class="r2-lobby-note">${n}</div>`).join('');
  }

  const unsubscribe = onState((s) => { renderStatus(s); renderStart(s); renderApps(s); });
  refresh().catch((err) => { statusBox.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });

  return () => { unsubscribe(); if (stopClock) stopClock(); if (stopStartClock) stopStartClock(); stopGps(); };
}
