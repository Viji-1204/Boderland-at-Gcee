// Powers (spec section 18). Two very different moments, two layouts:
//
// * Before the start (the shop is open): a cart. Tap + / - on any power,
//   change your mind as often as you like, then press BUY once. What the
//   team already owns sits at the top as its loadout.
// * Once the game is live: the loadout only - one card per family with big
//   buttons for the powers the team actually holds. Guide shows the way,
//   attacks pick a rival, a Ward is raised in advance; Shield and Reflect
//   are answered from the "under attack" prompt, so they only show a count.
import { api } from '../../../shared/js/api.js';
import { HEADERS, POWERS, POWER_FAMILIES, powerDesc } from '../../../shared/js/copy.js';
import { glyphSVG } from '../../../shared/js/suit-icons.js';
import { dialog, esc, formatClock, toast } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState, refresh } from '../live.js';

const FAMILY_ORDER = ['HELP', 'ATTACK', 'DEFENCE'];
const FAMILY_ICON = { HELP: 'guide', ATTACK: 'attack', DEFENCE: 'shield' };
const RESULT = {
  PENDING: 'waiting for their answer',
  CONFIRMED: 'landed - they accepted',
  EXPIRED: 'landed - no answer in time',
};
const BLOCKED = { SHIELD: 'blocked by a Shield', REFLECT: 'REFLECTED back at you!', WARD: 'bounced off a Ward' };

// The cart lives across screen changes (a team may check the rules mid-shop).
const cart = new Map(); // kind -> quantity

const name = (kind) => (POWERS[kind] || { en: kind }).en;
const icon = (kind, size = 26) => glyphSVG(kind.toLowerCase(), { size, stroke: 1.8 });

export function renderPowers(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.powers)}
    <div class="r2-body" id="powers-body"><div class="spinner" style="margin:40px auto;"></div></div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#powers-body');
  let busy = false;
  let ticker = null;

  async function act(fn, after) {
    if (busy) return;
    busy = true;
    try {
      const res = await fn();
      if (res && res.message) toast(res.message, { success: true });
      if (after) after(res);
    } catch (err) {
      toast(err.message, { error: true });
    } finally {
      busy = false;
      refresh().catch(() => {});
    }
  }

  // ---- shop -------------------------------------------------------------------

  function cartTotal(items) {
    let total = 0;
    cart.forEach((qty, kind) => { const p = items.find((i) => i.kind === kind); if (p) total += qty * p.cost; });
    return total;
  }

  function shopRow(p, s) {
    const qty = cart.get(p.kind) || 0;
    const points = s.team.power_points;
    const total = cartTotal(s.powers.items);
    const room = p.max_per_team - p.owned - qty; // how many more this team may hold
    const canAdd = p.available && room > 0 && total + p.cost <= points;
    const why = !p.available ? 'Not in this event' : room <= 0 ? `Max ${p.max_per_team} per team` : total + p.cost > points ? 'Not enough points' : '';
    return `
      <div class="r2-shop-row ${p.family} ${qty ? 'picked' : ''} ${p.available ? '' : 'off'}">
        <div class="r2-shop-icon">${icon(p.kind)}</div>
        <div class="r2-shop-text">
          <div class="r2-shop-name">${name(p.kind)} <span class="r2-shop-cost">${p.cost} pts</span></div>
          <div class="r2-shop-desc">${esc(powerDesc(p.kind, s.event.settings))}</div>
          <div class="r2-shop-meta">${p.owned ? `You own ${p.owned} · ` : ''}max ${p.max_per_team}${why && !qty ? ` · <span class="bad">${why}</span>` : ''}</div>
        </div>
        <div class="r2-qty">
          <button type="button" data-minus="${p.kind}" aria-label="Remove one ${name(p.kind)}" ${qty ? '' : 'disabled'}>−</button>
          <span class="r2-qty-n ${qty ? 'on' : ''}">${qty}</span>
          <button type="button" data-plus="${p.kind}" aria-label="Add one ${name(p.kind)}" ${canAdd ? '' : 'disabled'}>+</button>
        </div>
      </div>`;
  }

  function loadoutChips(items) {
    const owned = items.filter((p) => p.owned > 0);
    if (!owned.length) return '';
    return `<div class="r2-chips">${owned.map((p) => `<span class="r2-chip ${p.family}">${icon(p.kind, 16)} ${name(p.kind)} <b>×${p.remaining}</b></span>`).join('')}</div>`;
  }

  function renderShop(s) {
    const t = s.team;
    const items = s.powers.items;
    const total = cartTotal(items);
    const count = Array.from(cart.values()).reduce((a, b) => a + b, 0);
    const ownsAny = items.some((p) => p.owned > 0);
    const chips = loadoutChips(items);
    body.innerHTML = `
      <div class="r2-panel r2-row">
        <div><div class="r2-eyebrow">Power points</div><div class="r2-big-number">${t.power_points}</div></div>
        <div class="muted" style="font-size:.78rem;max-width:55%;text-align:right;">Spend them before the start. The shop closes when the game goes live.</div>
      </div>
      ${ownsAny ? `
        <div class="r2-panel r2-loadout">
          <div class="r2-row"><h3 style="margin:0;">Your loadout</h3><span class="r2-pill COMPLETED">READY</span></div>
          ${chips}
          <p class="muted" style="margin:8px 0 0;font-size:.78rem;">Bought and ready. Once the game starts, this page turns into your control panel for using them.</p>
        </div>` : ''}
      <div class="r2-cart-bar ${count ? '' : 'empty'}" id="cart-bar">
        <div>
          <div class="r2-eyebrow">${count ? `${count} power${count > 1 ? 's' : ''} picked` : 'Pick your powers'}</div>
          <div class="r2-cart-total">${count ? `${total} pts <span class="muted">· ${t.power_points - total} left after</span>` : `<span class="muted">Tap + to add, − to remove. Nothing is spent until you press BUY.</span>`}</div>
        </div>
        ${count ? `<button type="button" class="r2-cart-clear" id="cart-clear">CLEAR</button><button type="button" class="cta-btn r2-cart-buy" id="cart-buy">BUY · ${total} pts</button>` : ''}
      </div>
      ${FAMILY_ORDER.map((fam) => {
        const rows = items.filter((p) => p.family === fam);
        if (!rows.length) return '';
        const f = POWER_FAMILIES[fam];
        return `
          <div class="r2-power-family"><h3>${f.en.toUpperCase()} <span class="jp" style="font-weight:400;">${f.jp}</span></h3><small>${f.blurb}</small></div>
          <div class="r2-shop-list">${rows.map((p) => shopRow(p, s)).join('')}</div>`;
      }).join('')}`;

    body.querySelectorAll('[data-plus]').forEach((b) => b.addEventListener('click', () => {
      cart.set(b.dataset.plus, (cart.get(b.dataset.plus) || 0) + 1);
      renderShop(s);
    }));
    body.querySelectorAll('[data-minus]').forEach((b) => b.addEventListener('click', () => {
      const n = (cart.get(b.dataset.minus) || 0) - 1;
      if (n > 0) cart.set(b.dataset.minus, n); else cart.delete(b.dataset.minus);
      renderShop(s);
    }));
    const clear = body.querySelector('#cart-clear');
    if (clear) clear.addEventListener('click', () => { cart.clear(); renderShop(s); });
    const buy = body.querySelector('#cart-buy');
    if (buy) buy.addEventListener('click', () => checkout(s));
  }

  async function checkout(s) {
    const items = s.powers.items;
    const lines = Array.from(cart.entries()).map(([kind, qty]) => ({ kind, qty, cost: (items.find((i) => i.kind === kind) || { cost: 0 }).cost * qty }));
    if (!lines.length) return;
    const total = lines.reduce((a, l) => a + l.cost, 0);
    const ok = await dialog({
      titleJp: '購入しますか？',
      titleEn: 'BUY THESE POWERS?',
      message: `<div style="text-align:left;">${lines.map((l) => `<div class="r2-row" style="padding:3px 0;"><span>${name(l.kind)} ×${l.qty}</span><span class="mono">${l.cost} pts</span></div>`).join('')}
        <div class="r2-row" style="border-top:1px solid var(--bl-hairline);margin-top:6px;padding-top:6px;"><strong>Total</strong><strong class="mono">${total} pts</strong></div>
        <div class="muted" style="font-size:.78rem;margin-top:6px;">${s.team.power_points - total} points will remain. Purchases are final.</div></div>`,
      confirm: `BUY · ${total} pts`,
      cancel: 'Not yet',
    });
    if (!ok) return;
    if (busy) return;
    busy = true;
    const bought = [];
    try {
      for (const l of lines) {
        await api.team.purchase(l.kind, l.qty); // one call per kind, in order
        cart.delete(l.kind);
        bought.push(`${name(l.kind)} ×${l.qty}`);
      }
      toast(`Bought ${bought.join(', ')}. Your loadout is ready.`, { success: true, duration: 4200 });
    } catch (err) {
      // What went through stays bought; what didn't stays in the cart.
      toast(`${bought.length ? `Bought ${bought.join(', ')}. ` : ''}${err.message}`, { error: true, duration: 6000 });
    } finally {
      busy = false;
      refresh().catch(() => {});
      body.scrollTo({ top: 0, behavior: 'smooth' });
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  // ---- in the game --------------------------------------------------------------

  function effects(t) {
    const rows = [];
    if (t.guide_until) rows.push(['GUIDED', 'Guide active - the radar shows the exact way', t.guide_until]);
    if (t.warded_until) rows.push(['WARDED', 'Ward up - attacks bounce off', t.warded_until]);
    if (t.jammed_until) rows.push(['JAMMED', 'Radar jammed by a rival', t.jammed_until]);
    return rows.map(([cls, text, until]) => `<div class="r2-effect ${cls}"><span>${text}</span><span class="mono" data-until="${until}">--:--</span></div>`).join('');
  }

  function familyCard(fam, s, live) {
    const t = s.team;
    const held = s.powers.items.filter((p) => p.family === fam && p.owned > 0);
    const f = POWER_FAMILIES[fam];
    let actions = '';
    if (!held.length) {
      actions = '<div class="muted" style="font-size:.8rem;">Nothing bought in this family.</div>';
    } else if (fam === 'HELP') {
      actions = held.map((p) => {
        const on = Boolean(t.guide_until);
        const canUse = live && ['ACTIVE', 'FINAL'].includes(t.status) && !on && p.remaining > 0;
        const hint = on ? 'Active - the radar shows the way' : p.remaining < 1 ? 'All used' : !live ? '' : t.status === 'PUZZLE_LOCKED' ? 'Solve your puzzle first' : t.status === 'FROZEN' ? 'Frozen' : 'Shows your next checkpoint';
        return `
          <div class="r2-use">
            <div class="r2-use-text"><strong>${name(p.kind)}</strong> <span class="mono">×${p.remaining}</span><small>${hint}</small></div>
            ${on
              ? `<button type="button" class="cta-btn r2-use-btn on" data-goto="#/radar">OPEN RADAR <span class="mono" data-until="${t.guide_until}">--:--</span></button>`
              : `<button type="button" class="cta-btn r2-use-btn" data-use="GUIDE" ${canUse ? '' : 'disabled'}>SHOW THE WAY</button>`}
          </div>`;
      }).join('');
    } else if (fam === 'ATTACK') {
      const blocked = !live || t.status === 'FROZEN';
      actions = `
        <div class="r2-use-grid">${held.map((p) => `
          <button type="button" class="cta-btn r2-use-btn danger" data-use="${p.kind}" ${blocked || p.remaining < 1 ? 'disabled' : ''}>
            ${icon(p.kind, 20)} ${name(p.kind).toUpperCase()} <span class="mono">×${p.remaining}</span>
          </button>`).join('')}</div>
        <small class="muted">${t.status === 'FROZEN' ? "You're frozen - no attacks until the timer runs out." : 'Tap one, then pick the rival.'}</small>`;
    } else {
      const passive = held.filter((p) => p.kind !== 'WARD');
      const wardP = held.find((p) => p.kind === 'WARD');
      const on = Boolean(t.warded_until);
      actions = `
        ${passive.length ? `<div class="r2-use"><div class="r2-use-text">${passive.map((p) => `<strong>${name(p.kind)}</strong> <span class="mono">×${p.remaining}</span>`).join(' &nbsp;·&nbsp; ')}<small>Used from the prompt when you're attacked - nothing to press here.</small></div></div>` : ''}
        ${wardP ? `
          <div class="r2-use">
            <div class="r2-use-text"><strong>Ward</strong> <span class="mono">×${wardP.remaining}</span><small>${on ? 'Up - attacks bounce off' : 'Raise it before an attack comes'}</small></div>
            <button type="button" class="cta-btn r2-use-btn ${on ? 'on' : ''}" data-use="WARD" ${on || !live || wardP.remaining < 1 ? 'disabled' : ''}>${on ? `UP <span class="mono" data-until="${t.warded_until}">--:--</span>` : 'RAISE WARD'}</button>
          </div>` : ''}`;
    }
    return `
      <div class="r2-panel r2-family-card ${fam}">
        <div class="r2-row" style="margin-bottom:6px;"><h3 style="margin:0;display:flex;align-items:center;gap:8px;">${glyphSVG(FAMILY_ICON[fam], { size: 20, stroke: 2 })} ${f.en.toUpperCase()} <span class="jp" style="font-weight:400;font-size:.8rem;">${f.jp}</span></h3></div>
        ${actions}
      </div>`;
  }

  function renderLoadout(s) {
    const t = s.team;
    const live = s.event.status === 'LIVE';
    const note = s.event.status === 'PAUSED' ? '<div class="r2-effect JAMMED"><span>Game paused - powers are on hold.</span></div>'
      : s.event.status === 'ENDED' ? '<div class="r2-effect WARDED"><span>The game has ended.</span></div>'
        : !live ? '<div class="r2-effect WARDED"><span>Powers unlock when the game starts.</span></div>' : '';
    const outgoing = s.outgoing_attacks.length
      ? `<div class="r2-panel"><h3>Your attacks</h3>${s.outgoing_attacks.map((a) => `
          <div class="r2-row" style="padding:6px 0;border-bottom:1px solid var(--bl-hairline);">
            <span><strong>${name(a.kind)}</strong> → ${esc(a.target_name)}</span>
            <span class="muted" style="font-size:.78rem;text-align:right;">${a.status === 'CANCELLED' ? (BLOCKED[a.resolved_with] || 'blocked') : (RESULT[a.status] || a.status)}</span>
          </div>`).join('')}</div>`
      : '';
    body.innerHTML = `
      ${note}
      ${effects(t)}
      ${FAMILY_ORDER.map((fam) => familyCard(fam, s, live)).join('')}
      ${outgoing}`;
    tick();

    body.querySelectorAll('[data-goto]').forEach((b) => b.addEventListener('click', () => navigate(b.dataset.goto)));
    body.querySelectorAll('[data-use]').forEach((b) => b.addEventListener('click', async () => {
      const kind = b.dataset.use;
      if (kind === 'GUIDE') {
        const ok = await dialog({
          titleJp: '道しるべ',
          titleEn: 'SHOW THE WAY?',
          message: `This uses one Guide. For ${Math.round(s.event.settings.guide_duration_s / 60)} minutes the radar shows your next checkpoint by name, the exact distance, and a Google Maps route to it.`,
          confirm: 'USE THE GUIDE',
          cancel: 'Cancel',
        });
        if (ok) act(() => api.team.guide(), () => navigate('#/radar'));
      } else if (kind === 'WARD') {
        const ok = await dialog({
          titleJp: '結界',
          titleEn: 'RAISE A WARD?',
          message: `This uses one Ward. For ${Math.round(s.event.settings.ward_duration_s / 60)} minutes every attack on your team is blocked automatically - you won't even see a prompt.`,
          confirm: 'RAISE IT',
          cancel: 'Cancel',
        });
        if (ok) act(() => api.team.ward());
      } else {
        pickTarget(kind, s);
      }
    }));
  }

  async function pickTarget(kind, s) {
    let targets;
    try {
      targets = await api.team.targets();
    } catch (err) { toast(err.message, { error: true }); return; }
    const meta = POWERS[kind];
    const overlay = document.createElement('div');
    overlay.className = 'rules-modal-overlay';
    overlay.innerHTML = `
      <div class="rules-modal-dialog">
        <div class="rules-modal-header">
          <div class="rules-modal-title"><span class="jp">${meta.jp}</span><span class="en">${meta.en}: choose a team</span></div>
          <button class="rules-modal-close" type="button" aria-label="Close">✕</button>
        </div>
        <div class="rules-modal-body">
          <p class="muted" style="margin:0 0 10px;font-size:.8rem;">${esc(powerDesc(kind, s.event.settings))}</p>
          ${targets.length ? targets.map((t) => `
            <button class="r2-target" type="button" data-id="${t.id}" data-name="${esc(t.team_name)}" ${t.finished ? 'disabled' : ''}>
              <span>${esc(t.team_name)}</span><span class="muted" style="font-size:.75rem;">${t.finished ? 'finished' : `${meta.en.toUpperCase()} →`}</span>
            </button>`).join('') : '<p class="muted">No other teams.</p>'}
        </div>
      </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('open')); // the overlay fades in via .open
    const close = () => { overlay.classList.remove('open'); overlay.classList.add('closing'); setTimeout(() => overlay.remove(), 240); };
    overlay.querySelector('.rules-modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelectorAll('[data-id]').forEach((b) => b.addEventListener('click', async () => {
      close();
      const ok = await dialog({
        titleJp: `${meta.jp}しますか？`,
        titleEn: `SEND THE ${meta.en.toUpperCase()}?`,
        message: `<strong>${esc(b.dataset.name)}</strong> will have ${s.event.settings.attack_response_window_s}s to block it with a Shield or Reflect. If they can't, it lands. A Ward stops it cold.`,
        confirm: meta.en.toUpperCase(),
        cancel: 'Cancel',
        danger: true,
      });
      if (ok) act(() => api.team.attack(kind, b.dataset.id));
    }));
  }

  // ---- shared ------------------------------------------------------------------------

  function render(s) {
    if (s.powers.purchase_open) renderShop(s);
    else renderLoadout(s);
  }

  function tick() {
    body.querySelectorAll('[data-until]').forEach((el) => {
      const left = (Date.parse(el.dataset.until) - api.getServerNow()) / 1000;
      el.textContent = left > 0 ? formatClock(left) : '00:00';
      if (left <= 0 && !el.dataset.done) { el.dataset.done = '1'; setTimeout(() => refresh().catch(() => {}), 800); }
    });
  }

  const unsubscribe = onState(render);
  ticker = setInterval(tick, 1000);
  refresh().catch((err) => { body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  return () => { unsubscribe(); clearInterval(ticker); };
}
