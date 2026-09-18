// Round 1's account screen, adapted: profile card, event status, log out.
import { EVENT_STATUS, HEADERS, TEAM_STATUS } from '../../../shared/js/copy.js';
import { dialog, esc } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { logout, onState, refresh } from '../live.js';

export function renderAccount(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.account)}
    <div class="scroll-area" id="account-body" style="padding-bottom: 110px;">
      <div style="display:flex;justify-content:center;align-items:center;height:40vh;"><div class="spinner"></div></div>
    </div>
    ${navHTML('account')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#account-body');

  function render(s) {
    const t = s.team;
    const initials = t.team_name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
    body.innerHTML = `
      <div style="max-width:480px;margin:0 auto;display:flex;flex-direction:column;gap:16px;">
        <div class="r2-panel" style="text-align:center;">
          <div style="width:64px;height:64px;background:#0f172a;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 12px;font-size:1.5rem;font-weight:900;">${esc(initials)}</div>
          <h2 style="font-size:1.35rem;font-weight:900;margin:0 0 4px;">${esc(t.team_name)}</h2>
          <div style="display:inline-flex;gap:6px;background:#f1f5f9;padding:4px 12px;border-radius:20px;font-size:.85rem;font-weight:700;color:#475569;font-family:var(--font-mono);">
            <span>ID:</span><strong>${esc(t.team_code)}</strong>
          </div>
          ${t.leader_name ? `<div class="muted" style="margin-top:8px;font-size:.85rem;">Leader: ${esc(t.leader_name)}</div>` : ''}
        </div>
        <div class="r2-panel">
          <div class="r2-row" style="margin-bottom:10px;"><span class="r2-eyebrow">Event</span><span>${esc(s.event.name)}</span></div>
          <div class="r2-row" style="margin-bottom:10px;"><span class="r2-eyebrow">Game</span><span class="r2-pill ${s.event.status}">${esc(EVENT_STATUS[s.event.status].en)}</span></div>
          <div class="r2-row"><span class="r2-eyebrow">Your team</span><span class="r2-pill ${t.status}">${esc((TEAM_STATUS[t.status] || { en: t.status }).en)}</span></div>
        </div>
        <div class="r2-panel" style="font-size:.85rem;">
          Several phones can use the same team login - every action is applied in order on the server, so nothing gets lost or doubled.
        </div>
        <button id="logout-btn" class="cta-btn ghost" style="color:var(--bl-red);border:1.5px solid rgba(229,57,53,.3);background:#fff;" type="button">ログアウト / Log Out</button>
      </div>`;
    body.querySelector('#logout-btn').addEventListener('click', async () => {
      const ok = await dialog({ titleJp: 'ログアウトしますか？', titleEn: 'LOG OUT?', message: 'You can log back in with your team code and password.', confirm: 'Log out', cancel: 'Stay' });
      if (ok) logout();
    });
  }

  const unsubscribe = onState(render);
  refresh().catch((err) => { body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  return unsubscribe;
}
