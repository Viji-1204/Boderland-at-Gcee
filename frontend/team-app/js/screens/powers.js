// Powers (spec section 18): buy before the start, use during the game.
// Defence is used from the "under attack" prompt, not from here.
import { api } from '../../../shared/js/api.js';
import { HEADERS, POWERS } from '../../../shared/js/copy.js';
import { glyphSVG } from '../../../shared/js/suit-icons.js';
import { dialog, esc, toast } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState, refresh } from '../live.js';

const ICON = { HELP: 'help', ATTACK: 'attack', DEFENCE: 'defence' };
const ATTACK_STATUS = { PENDING: 'waiting for their answer', CONFIRMED: 'frozen them', CANCELLED: 'blocked by Defence', EXPIRED: 'frozen them (no answer)' };
const HELP_STATUS = { PENDING: 'Sent - waiting for a volunteer', ACKNOWLEDGED: 'A volunteer is on the way', RESOLVED: 'Resolved' };

export function renderPowers(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.powers)}
    <div class="r2-body" id="powers-body"><div class="spinner" style="margin:40px auto;"></div></div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#powers-body');
  let busy = false;

  async function act(fn) {
    if (busy) return;
    busy = true;
    try {
      const res = await fn();
      if (res && res.message) toast(res.message, { success: true });
    } catch (err) {
      toast(err.message, { error: true });
    } finally {
      busy = false;
      refresh().catch(() => {});
    }
  }

  async function pickTarget() {
    let targets;
    try {
      targets = await api.team.targets();
    } catch (err) { toast(err.message, { error: true }); return; }
    const overlay = document.createElement('div');
    overlay.className = 'rules-modal-overlay';
    overlay.innerHTML = `
      <div class="rules-modal-dialog">
        <div class="rules-modal-header">
          <div class="rules-modal-title"><span class="jp">攻撃</span><span class="en">Choose a team to attack</span></div>
          <button class="rules-modal-close" type="button" aria-label="Close">✕</button>
        </div>
        <div class="rules-modal-body">
          ${targets.length ? targets.map((t) => `
            <button class="r2-target" type="button" data-id="${t.id}" data-name="${esc(t.team_name)}" ${t.finished ? 'disabled' : ''}>
              <span>${esc(t.team_name)}</span><span class="muted" style="font-size:.75rem;">${t.finished ? 'finished' : 'ATTACK →'}</span>
            </button>`).join('') : '<p class="muted">No other teams.</p>'}
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('.rules-modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelectorAll('[data-id]').forEach((b) => b.addEventListener('click', async () => {
      close();
      const ok = await dialog({
        titleJp: '攻撃しますか？',
        titleEn: 'SEND THE ATTACK?',
        message: `<strong>${esc(b.dataset.name)}</strong> will have a few seconds to block it with a Defence. If they can't, they're frozen.`,
        confirm: 'ATTACK',
        cancel: 'Cancel',
        danger: true,
      });
      if (ok) act(() => api.team.attack(b.dataset.id));
    }));
  }

  function render(s) {
    const live = s.event.status === 'LIVE';
    const shop = s.powers.purchase_open;
    const t = s.team;
    const helpOpen = s.help && ['PENDING', 'ACKNOWLEDGED'].includes(s.help.status);
    const tiles = s.powers.items.map((p) => {
      const meta = POWERS[p.kind];
      let button = '';
      if (shop) {
        const cantAfford = p.cost > t.power_points;
        const full = p.owned >= p.max_per_team;
        button = `<button type="button" class="primary" data-buy="${p.kind}" ${!p.available || cantAfford || full ? 'disabled' : ''}>
          ${full ? 'MAX' : `BUY · ${p.cost} pts`}</button>`;
      } else if (live && p.kind === 'ATTACK') {
        button = `<button type="button" class="primary" data-use="ATTACK" ${p.remaining < 1 || t.status === 'FROZEN' ? 'disabled' : ''}>ATTACK</button>`;
      } else if (live && p.kind === 'HELP') {
        button = `<button type="button" class="primary" data-use="HELP" ${p.remaining < 1 || helpOpen ? 'disabled' : ''}>${helpOpen ? 'SENT' : 'CALL'}</button>`;
      } else if (p.kind === 'DEFENCE') {
        button = '<span class="muted" style="font-size:.68rem;">Used when you\'re attacked</span>';
      }
      return `
        <div class="r2-power ${p.kind}">
          ${glyphSVG(ICON[p.kind], { size: 30, stroke: 1.8 })}
          <div class="r2-power-name">${meta.en}</div>
          <div class="r2-power-qty">${p.remaining} left${p.used ? ` · ${p.used} used` : ''}</div>
          ${button}
        </div>`;
    }).join('');
    const outgoing = s.outgoing_attacks.length
      ? `<div class="r2-panel"><h3>Your attacks</h3>${s.outgoing_attacks.map((a) => `
          <div class="r2-row" style="padding:6px 0;border-bottom:1px solid var(--bl-hairline);">
            <span>${esc(a.target_name)}</span><span class="muted" style="font-size:.78rem;">${ATTACK_STATUS[a.status] || a.status}</span>
          </div>`).join('')}</div>`
      : '';
    body.innerHTML = `
      <div class="r2-panel r2-row">
        <div><div class="r2-eyebrow">Power points</div><div class="r2-big-number">${t.power_points}</div></div>
        <div class="muted" style="font-size:.78rem;max-width:55%;text-align:right;">
          ${shop ? 'The shop is open until the game starts.' : 'The shop closed when the game started.'}
        </div>
      </div>
      <div class="r2-power-grid">${tiles}</div>
      ${s.help ? `<div class="r2-panel r2-row"><div><div class="r2-eyebrow">Help request</div><div>${HELP_STATUS[s.help.status] || s.help.status}</div></div><span class="r2-pill ${s.help.status === 'RESOLVED' ? 'COMPLETED' : 'WAITING'}">${s.help.status}</span></div>` : ''}
      ${outgoing}
      <div class="r2-panel">
        ${Object.entries(POWERS).map(([k, m]) => `<p style="margin:0 0 6px;font-size:.85rem;"><strong>${m.en}</strong> - ${m.desc}</p>`).join('')}
      </div>`;

    body.querySelectorAll('[data-buy]').forEach((b) => b.addEventListener('click', () => act(() => api.team.purchase(b.dataset.buy, 1))));
    const attackBtn = body.querySelector('[data-use="ATTACK"]');
    if (attackBtn) attackBtn.addEventListener('click', pickTarget);
    const helpBtn = body.querySelector('[data-use="HELP"]');
    if (helpBtn) helpBtn.addEventListener('click', async () => {
      const ok = await dialog({ titleJp: '救援を呼ぶ', titleEn: 'CALL FOR HELP?', message: 'This uses one Help power. A volunteer will come to your team.', confirm: 'CALL A VOLUNTEER', cancel: 'Cancel' });
      if (ok) act(() => api.team.help(''));
    });
  }

  const unsubscribe = onState(render);
  refresh().catch((err) => { body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  return unsubscribe;
}
