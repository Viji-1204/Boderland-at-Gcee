import { api } from './api.js';

export function toast(message, opts = {}) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const el = document.createElement('div');
  el.className = `toast${opts.error ? ' error' : ''}${opts.success ? ' success' : ''}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), opts.duration || 3200);
}

/** Escape text before it goes into innerHTML. Round 1 skipped this for team
 *  names, which let a name inject markup; every screen here uses it. */
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Seconds -> HH:MM:SS (Round 1's digital clock face). */
export function formatCountdown(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

/** Seconds -> MM:SS, or H:MM:SS past an hour. */
export function formatClock(totalSeconds) {
  const s = Math.max(0, Math.ceil(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${String(m).padStart(2, '0')}:${sec}`;
}

/**
 * Drive a countdown from a server timestamp (never a local timer), so tab
 * backgrounding or a wrong phone clock can't desync it (spec section 28).
 * @returns {() => void} stop
 */
export function startCountdown(deadlineIso, onTick, onExpire) {
  let stopped = false;
  let timerId = null;
  const deadline = new Date(deadlineIso).getTime();
  function tick() {
    if (stopped) return;
    const remainingMs = deadline - api.getServerNow();
    if (remainingMs <= 0) {
      onTick(0);
      if (onExpire) onExpire();
      return;
    }
    onTick(remainingMs / 1000);
    timerId = setTimeout(tick, 200);
  }
  tick();
  return () => { stopped = true; if (timerId) clearTimeout(timerId); };
}

export function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function friendlyError(err, translateFn) {
  const jp = translateFn ? translateFn(err.detail) : null;
  return jp ? `${jp} / ${err.message}` : err.message;
}

export function vibrate(pattern) {
  try {
    if (navigator.vibrate && (!navigator.userActivation || navigator.userActivation.hasBeenActive)) {
      navigator.vibrate(pattern);
    }
  } catch (_) { /* unsupported */ }
}

/** Round 1's warning-popup styling as a small promise-based dialog. */
export function dialog({ titleJp = '', titleEn = '', message = '', confirm = '確認 / OK', cancel = null, danger = false }) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'bl-warn-popup-overlay';
    overlay.innerHTML = `
      <div class="bl-warn-popup-card">
        ${titleJp ? `<div class="bl-warn-title-jp">${esc(titleJp)}</div>` : ''}
        ${titleEn ? `<div class="bl-warn-title-en">${esc(titleEn)}</div>` : ''}
        <div class="bl-warn-message-box"><div class="bl-warn-message-en">${message}</div></div>
        <div class="r2-dialog-actions">
          ${cancel ? `<button type="button" class="cta-btn ghost" data-v="0">${esc(cancel)}</button>` : ''}
          <button type="button" class="${danger ? 'cta-btn danger' : 'bl-warn-btn-close'}" data-v="1">${esc(confirm)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-v]');
      if (btn) { overlay.remove(); resolve(btn.dataset.v === '1'); }
      else if (e.target === overlay && cancel) { overlay.remove(); resolve(false); }
    });
  });
}
