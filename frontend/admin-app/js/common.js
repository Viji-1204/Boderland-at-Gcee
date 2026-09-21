// Small helpers shared by the coordinator screens.
import { esc, toast } from '../../shared/js/ui.js';

export const STATUS_LABEL = {
  DRAFT: 'Draft', CONFIGURED: 'Configured', LIVE: 'Live', PAUSED: 'Paused', ENDED: 'Ended',
  NOT_STARTED: 'Not started', WAITING: 'Waiting', ACTIVE: 'Hunting', PUZZLE_LOCKED: 'Puzzle',
  FROZEN: 'Frozen', FINAL: 'Joker hunt', COMPLETED: 'Finished', DISQUALIFIED: 'Disqualified',
  PENDING: 'Pending', ACKNOWLEDGED: 'On the way', RESOLVED: 'Resolved',
};

export function pill(status, text) {
  return `<span class="pill ${esc(status)}">${esc(text || STATUS_LABEL[status] || status)}</span>`;
}

export function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function fmtDateTime(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

/** Run an API call with toasts; returns the result (true for an empty 204 reply) or null on failure. */
export async function guarded(fn, success) {
  try {
    const res = await fn();
    if (success) toast(typeof success === 'function' ? success(res) : success, { success: true });
    return res ?? true; // deletes answer 204 with no body - still a success
  } catch (err) {
    toast(err.message, { error: true, duration: 5000 });
    return null;
  }
}

/** Round 1's modal chrome. `onSubmit(formData, close)` may return false to keep it open.
 *  `onClose` runs however it closes (e.g. to stop a GPS watch). */
export function openModal(title, bodyHTML, { submitLabel = 'Save', onSubmit = null, wide = false, onClose = null } = {}) {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `
    <div class="modal" style="${wide ? 'max-width:760px;' : ''}max-height:90vh;overflow-y:auto;">
      <h3>${esc(title)}</h3>
      <form id="modal-form">
        ${bodyHTML}
        <div class="btn-row" style="margin-top:16px;">
          ${onSubmit ? `<button type="submit" class="btn primary">${esc(submitLabel)}</button>` : ''}
          <button type="button" class="btn" id="modal-cancel">${onSubmit ? 'Cancel' : 'Close'}</button>
        </div>
      </form>
    </div>`;
  document.body.appendChild(backdrop);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    backdrop.remove();
    if (onClose) onClose();
  };
  backdrop.querySelector('#modal-cancel').addEventListener('click', close);
  backdrop.querySelector('#modal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!onSubmit) return;
    const btn = backdrop.querySelector('button[type="submit"]');
    btn.disabled = true;
    const keepOpen = (await onSubmit(new FormData(e.target), close)) === false;
    btn.disabled = false;
    if (!keepOpen) close();
  });
  return { el: backdrop, close };
}

/** In-page replacement for window.confirm (Round 1 modal look). Resolves true/false. */
export function confirmModal(message, { okLabel = 'Confirm', danger = false, title = 'Are you sure?' } = {}) {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal" role="alertdialog" aria-modal="true">
        <h3>${esc(title)}</h3>
        <p style="font-size:.85rem;color:#334155;line-height:1.5;">${esc(message)}</p>
        <div class="btn-row" style="margin-top:16px;">
          <button type="button" class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(okLabel)}</button>
          <button type="button" class="btn" data-cancel>Cancel</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    const done = (value) => { backdrop.remove(); resolve(value); };
    backdrop.querySelector('[data-ok]').addEventListener('click', () => done(true));
    backdrop.querySelector('[data-cancel]').addEventListener('click', () => done(false));
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) done(false); });
    backdrop.querySelector('[data-ok]').focus();
  });
}

/** In-page replacement for window.prompt for a new password. Resolves the value or null. */
export function passwordModal(title, minLength = 4) {
  return new Promise((resolve) => {
    let value = null;
    const { el } = openModal(title, `
      <div class="field"><label class="tier-label"><span class="primary">New password</span><span class="secondary">At least ${minLength} characters</span></label>
      <input name="pw" type="text" minlength="${minLength}" required autocomplete="off" /></div>`, {
      submitLabel: 'Set password',
      onSubmit: (fd) => { value = String(fd.get('pw')); },
    });
    const observer = new MutationObserver(() => {
      if (!document.body.contains(el)) { observer.disconnect(); resolve(value); }
    });
    observer.observe(document.body, { childList: true });
  });
}

export function noEventHTML() {
  return `<div class="empty-state"><div class="empty-icon"><span class="mi mi-xl">event_busy</span></div>
    The game could not be loaded. Check the server and refresh.</div>`;
}
