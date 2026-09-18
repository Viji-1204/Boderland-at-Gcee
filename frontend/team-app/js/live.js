// Team "live" layer: one source of truth for GET /me/state, the WebSocket,
// and the full-screen overlays (frozen, incoming attack, paused, resync).
//
// Rules from the spec (section 28): resync with GET /me/state on load and on
// every WebSocket reconnect, never trust cached UI, and drive every timer
// from a server timestamp. A 20 s poll is the safety net if the socket dies.

import { api, clearToken, getToken } from '../../shared/js/api.js';
import { POWERS } from '../../shared/js/copy.js';
import { LiveChannel } from '../../shared/js/ws.js';
import { dialog, formatClock, startCountdown, toast, vibrate } from '../../shared/js/ui.js';
import { glyphSVG } from '../../shared/js/suit-icons.js';
import { sound } from '../../shared/js/sound.js';

let state = null;
let channel = null;
let pollTimer = null;
let inflight = null;
let navigateFn = (hash) => { location.hash = hash; };
const stateListeners = new Set();
const liveListeners = new Map();

export function setNavigate(fn) { navigateFn = fn; }
export function currentState() { return state; }

export function onState(fn) {
  stateListeners.add(fn);
  if (state) fn(state);
  return () => stateListeners.delete(fn);
}

/** Subscribe to a raw WebSocket message type (e.g. 'leaderboard'). */
export function onLive(type, fn) {
  if (!liveListeners.has(type)) liveListeners.set(type, new Set());
  liveListeners.get(type).add(fn);
  return () => liveListeners.get(type).delete(fn);
}

let refreshAgain = false;

export function refresh() {
  if (!getToken('team')) return Promise.resolve(null);
  if (inflight) {
    // A request already on the wire may predate the change we were just told
    // about (e.g. an attack), so fetch once more when it lands.
    refreshAgain = true;
    return inflight;
  }
  const startedAt = Date.now();
  inflight = api.team.state()
    .then((s) => { apply(s, startedAt); return s; })
    .catch((err) => {
      if (err.status === 0) showBanner('offline', 'Offline - retrying...', 0);
      throw err;
    })
    .finally(() => {
      inflight = null;
      if (refreshAgain) {
        refreshAgain = false;
        refresh().catch(() => {});
      }
    });
  return inflight;
}

function apply(next, startedAt = Date.now()) {
  const prev = state;
  state = next;
  hideBanner('offline');
  syncOverlays(prev, next, startedAt);
  stateListeners.forEach((fn) => { try { fn(next); } catch (e) { console.error(e); } });
}

function onVisible() {
  if (document.visibilityState === 'visible') refresh().catch(() => {});
}

export function startLive() {
  if (channel || !getToken('team')) return;
  channel = new LiveChannel('/team', onMessage, 'team', {
    onOpen: (reconnected) => {
      refresh().then(() => { if (reconnected) showBanner('sync', 'Reconnected - everything synced', 2200); }).catch(() => {});
    },
    onStatus: (s) => {
      if (s === 'closed') showBanner('offline', 'Connection lost - reconnecting...', 0);
    },
    onAuthError: () => logout(),
  });
  pollTimer = setInterval(() => refresh().catch(() => {}), 20000);
  document.addEventListener('visibilitychange', onVisible);
  refresh().catch(() => {});
}

export function stopLive() {
  if (channel) channel.close();
  channel = null;
  clearInterval(pollTimer);
  pollTimer = null;
  document.removeEventListener('visibilitychange', onVisible);
  state = null;
  hideFrozen();
  hideAttack();
  Object.keys(banners).forEach(hideBanner);
}

export function logout() {
  stopLive();
  clearToken('team');
  navigateFn('#/login');
}

function onMessage(msg) {
  (liveListeners.get(msg.type) || []).forEach((fn) => { try { fn(msg); } catch (e) { console.error(e); } });
  switch (msg.type) {
    case 'attack_incoming':
      vibrate([220, 80, 220, 80, 420]);
      sound.attackAlarm();
      // Open the prompt from the push itself - the window is only seconds long.
      if (state) showAttack({ usage_id: msg.usage_id, kind: msg.kind, expires_at: msg.expires_at }, state);
      refresh().catch(() => {});
      break;
    case 'attack_result': {
      const name = msg.target_name || 'The other team'; // toast() sets textContent - no escaping needed
      const power = (POWERS[msg.kind] || { en: 'attack' }).en;
      const landed = { FREEZE: "they're frozen!", JAM: 'their radar is jammed!', TRAP: 'foul +1 for them!' }[msg.kind] || 'it landed!';
      const text = msg.status === 'CANCELLED'
        ? { SHIELD: `${name} blocked your ${power} with a Shield.`, REFLECT: `${name} REFLECTED your ${power} - it hit you instead!`, WARD: `${name} has a Ward up - your ${power} bounced off.` }[msg.resolved_with] || `${name} blocked your ${power}.`
        : msg.status === 'CONFIRMED' ? `${name} accepted the ${power} - ${landed}` : `${name} didn't answer in time - ${landed}`;
      toast(text, { success: msg.status !== 'CANCELLED', error: msg.resolved_with === 'REFLECT' });
      refresh().catch(() => {});
      break;
    }
    case 'jammed':
      vibrate([120, 60, 120]);
      toast('Your radar has been JAMMED by a rival. You can still scan and solve puzzles.', { error: true, duration: 5000 });
      refresh().catch(() => {});
      break;
    case 'trapped':
      vibrate([120, 60, 120]);
      toast(`You walked into a TRAP - foul +1 (now ${msg.foul_count}).`, { error: true, duration: 5000 });
      refresh().catch(() => {});
      break;
    case 'toast':
      toast(msg.message);
      refresh().catch(() => {});
      break;
    case 'state':
    case 'frozen':
    case 'unfrozen':
    case 'completed':
    case 'event_status':
      refresh().catch(() => {});
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// Overlays
// ---------------------------------------------------------------------------

const banners = {};

function showBanner(kind, text, ms) {
  let el = banners[kind];
  if (!el) {
    el = document.createElement('div');
    el.className = `r2-banner ${kind}`;
    document.body.appendChild(el);
    banners[kind] = el;
  }
  el.textContent = text;
  clearTimeout(el._timer);
  if (ms > 0) el._timer = setTimeout(() => hideBanner(kind), ms);
}

function hideBanner(kind) {
  const el = banners[kind];
  if (el) { clearTimeout(el._timer); el.remove(); delete banners[kind]; }
}

function syncOverlays(prev, s, startedAt) {
  if (s.event.status === 'PAUSED') showBanner('paused', 'Game paused by the coordinators', 0);
  else hideBanner('paused');

  if (s.team.status === 'FROZEN' && s.team.frozen_until) showFrozen(s.team.frozen_until);
  else hideFrozen();

  // Shown even while frozen (events may allow stacked attacks), above the
  // frozen overlay. A state fetched before the prompt opened can't close it.
  if (s.incoming_attack) showAttack(s.incoming_attack, s);
  else if (!(attackEl && startedAt < attackShownAt)) hideAttack();

  if (prev && prev.team.status !== 'COMPLETED' && s.team.status === 'COMPLETED') celebrate(s);
  if (prev && prev.event.status !== s.event.status) {
    const text = { LIVE: prev.event.status === 'PAUSED' ? 'The game is back on!' : 'ROUND 2 HAS STARTED!', ENDED: 'The game is over - results are in.' }[s.event.status];
    if (text) { toast(text, { success: true, duration: 4200 }); sound.puzzleSolved(); vibrate([120, 60, 120]); }
  }
}

let frozenEl = null;
let stopFrozenClock = null;

function showFrozen(untilIso) {
  if (frozenEl && frozenEl.dataset.until === untilIso) return;
  hideFrozen();
  frozenEl = document.createElement('div');
  frozenEl.className = 'r2-frozen-overlay';
  frozenEl.dataset.until = untilIso;
  frozenEl.innerHTML = `
    <div class="r2-snow">${glyphSVG('snow', { size: 72, stroke: 1.6 })}</div>
    <div class="r2-frozen-title">FROZEN</div>
    <div class="r2-frozen-jp">凍結中 / You can't move</div>
    <div class="countdown-face" id="r2-frozen-clock">--:--</div>
    <p style="max-width:300px;opacity:.8;font-size:.85rem;">Your team was attacked. The radar and scanner come back when the timer runs out.</p>`;
  document.body.appendChild(frozenEl);
  const clock = frozenEl.querySelector('#r2-frozen-clock');
  stopFrozenClock = startCountdown(untilIso, (sec) => { clock.textContent = formatClock(sec); }, () => {
    setTimeout(() => refresh().catch(() => {}), 500);
  });
}

function hideFrozen() {
  if (stopFrozenClock) stopFrozenClock();
  stopFrozenClock = null;
  if (frozenEl) frozenEl.remove();
  frozenEl = null;
}

let attackEl = null;
let attackId = null;
let attackShownAt = 0;
let stopAttackClock = null;
const answeredAttacks = new Set(); // a state fetched before we answered must not reopen it

function showAttack(incoming, s) {
  if (attackEl && attackId === incoming.usage_id) return;
  if (answeredAttacks.has(incoming.usage_id)) return;
  if (!incoming.expires_at || Date.parse(incoming.expires_at) <= api.getServerNow()) return;
  hideAttack();
  attackId = incoming.usage_id;
  attackShownAt = Date.now();
  const left = (kind) => ((s.powers.items || []).find((p) => p.kind === kind) || {}).remaining || 0;
  const shields = left('SHIELD');
  const reflects = left('REFLECT');
  const kind = incoming.kind || 'FREEZE';
  const power = (POWERS[kind] || { en: 'Attack', jp: '攻撃' });
  const st = s.event.settings;
  const effect = incoming.effect || {
    FREEZE: `freezes you for ${st.freeze_duration_s}s: no radar, scanner or puzzle`,
    JAM: `jams your radar for ${st.jam_duration_s}s (you can still scan and solve)`,
    TRAP: 'plants a foul on your team (+1 foul)',
  }[kind];
  attackEl = document.createElement('div');
  attackEl.className = 'r2-attack-overlay';
  attackEl.innerHTML = `
    <div class="r2-attack-card" role="alertdialog" aria-labelledby="r2-atk-title">
      <div class="r2-attack-body">
        <div class="r2-attack-title" id="r2-atk-title">INCOMING ${power.en.toUpperCase()}</div>
        <div class="muted" style="font-family:var(--font-body-jp);">${power.jp}を受けています</div>
        <div class="countdown-face" id="r2-atk-clock">--:--</div>
        <p style="font-size:.88rem;margin:0;">A rival's <strong>${power.en}</strong> ${effect}.
        Block it with a Shield, Reflect it back at them, or accept it. No answer in time and it lands.</p>
      </div>
      <div class="r2-attack-actions">
        <button class="cta-btn" id="r2-shield" type="button" ${shields ? '' : 'disabled'}>SHIELD (${shields} left)</button>
        <button class="cta-btn" id="r2-reflect" type="button" ${reflects ? '' : 'disabled'}>REFLECT (${reflects} left)</button>
        <button class="cta-btn ghost" id="r2-accept" type="button">ACCEPT THE ${power.en.toUpperCase()}</button>
      </div>
    </div>`;
  document.body.appendChild(attackEl);
  const clock = attackEl.querySelector('#r2-atk-clock');
  stopAttackClock = startCountdown(incoming.expires_at, (sec) => { clock.textContent = formatClock(sec); }, () => {
    clock.textContent = '00:00';
    setTimeout(() => refresh().catch(() => {}), 900);
  });

  const respond = async (defence) => {
    attackEl.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    answeredAttacks.add(incoming.usage_id);
    try {
      const res = await api.team.defend(incoming.usage_id, defence);
      toast(res.message, { success: res.status === 'CANCELLED' });
    } catch (err) {
      toast(err.message, { error: true });
    }
    hideAttack();
    refresh().catch(() => {});
  };
  attackEl.querySelector('#r2-shield').addEventListener('click', () => respond('SHIELD'));
  attackEl.querySelector('#r2-reflect').addEventListener('click', () => respond('REFLECT'));
  attackEl.querySelector('#r2-accept').addEventListener('click', () => respond(null));
}

function hideAttack() {
  if (stopAttackClock) stopAttackClock();
  stopAttackClock = null;
  if (attackEl) attackEl.remove();
  attackEl = null;
  attackId = null;
}

function celebrate(s) {
  sound.puzzleSolved();
  vibrate([150, 80, 150, 80, 400]);
  const confetti = document.createElement('div');
  confetti.className = 'bl-confetti-container';
  const colors = ['#10b981', '#34d399', '#f59e0b', '#fbbf24', '#ffffff', '#D5262B'];
  for (let i = 0; i < 45; i += 1) {
    const piece = document.createElement('div');
    piece.className = 'bl-confetti-piece';
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.backgroundColor = colors[i % colors.length];
    piece.style.animationDelay = `${Math.random() * 0.8}s`;
    piece.style.animationDuration = `${1.8 + Math.random() * 1.5}s`;
    confetti.appendChild(piece);
  }
  document.body.appendChild(confetti);
  setTimeout(() => confetti.remove(), 4500);
  const time = s.team.elapsed_s != null ? formatClock(s.team.elapsed_s) : '--:--';
  dialog({
    titleJp: 'ジョーカー発見',
    titleEn: 'JOKER FOUND',
    message: `<div class="r2-celebrate-card"><div class="countdown-face">${time}</div>
      <div>All ${s.team.total_checkpoints} checkpoints cleared. Final rankings appear when the game ends.</div></div>`,
    confirm: 'See the leaderboard',
  }).then(() => navigateFn('#/leaderboard'));
}
