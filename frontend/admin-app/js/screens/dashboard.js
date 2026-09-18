// Live control room: lifecycle, readiness, every team at a glance, live feed.
import { api } from '../../../shared/js/api.js';
import { POWERS } from '../../../shared/js/copy.js';
import { LiveChannel } from '../../../shared/js/ws.js';
import { esc, formatClock, toast } from '../../../shared/js/ui.js';
import { confirmModal, fmtTime, guarded, openModal, pill } from '../common.js';

const STEPS = ['DRAFT', 'CONFIGURED', 'LIVE', 'PAUSED', 'ENDED'];
const ACTIONS = {
  DRAFT: [['lock', 'Lock configuration', 'primary', 'lock']],
  CONFIGURED: [['start', 'START ROUND 2', 'primary', 'play_arrow'], ['unlock', 'Unlock (back to draft)', '', 'lock_open']],
  LIVE: [['pause', 'Pause game', 'warn', 'pause'], ['end', 'End game', 'danger', 'stop'], ['restart', 'Restart game', '', 'restart_alt']],
  PAUSED: [['resume', 'Resume game', 'primary', 'play_arrow'], ['end', 'End game', 'danger', 'stop'], ['restart', 'Restart game', '', 'restart_alt']],
  ENDED: [['restart', 'Restart game', 'primary', 'restart_alt']],
};
const CONFIRM = {
  lock: 'Lock the configuration? Routes, sentences and start offsets become final.',
  start: 'Start Round 2 now? Power purchases close and every team goes live.',
  pause: 'Pause the whole game? No team can act until you resume; timers are paused too.',
  resume: 'Resume the game?',
  end: 'End the game? Results become final and teams can no longer play.',
  unlock: 'Unlock the configuration and go back to DRAFT?',
};
const DONE_LABEL = { lock: 'Lock', unlock: 'Unlock', start: 'Start Round 2', pause: 'Pause', resume: 'Resume', end: 'End the game' };
const DONE = {
  lock: 'Configuration locked', unlock: 'Back to draft', start: 'Round 2 is LIVE!',
  pause: 'Game paused', resume: 'Game resumed', end: 'Game ended - results are final',
  restart: 'Game reset - press START when you are ready',
};

export function renderDashboard(main, ctx) {
  main.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Live Dashboard</h1>
      <div class="btn-row"><span id="ws-state" class="pill NOT_STARTED">connecting</span>
      <button class="btn" id="refresh"><span class="mi">refresh</span> Refresh</button></div>
    </div>
    <div id="dash"><div class="spinner"></div></div>
  `;
  const box = main.querySelector('#dash');
  const wsState = main.querySelector('#ws-state');
  let data = null;
  let stopped = false;
  let debounce = null;

  function stepper(status) {
    const idx = STEPS.indexOf(status);
    return `<div class="r2-stepper">${STEPS.map((s, i) => {
      let cls = '';
      if (s === status) cls = s === 'PAUSED' ? 'paused' : 'current';
      else if (i < idx && !(s === 'PAUSED' && status !== 'PAUSED')) cls = 'done';
      return `<div class="r2-step ${cls}">${s}</div>`;
    }).join('')}</div>`;
  }

  function teamCard(t, serverNow) {
    const pct = t.total ? Math.round((t.progress / t.total) * 100) : 0;
    const powers = t.powers || {};
    const fx = t.effects || {};
    const cls = [t.status, t.incoming_attack_expires_at ? 'attacked' : ''].join(' ');
    const frozen = t.frozen_until ? `<span class="pill FROZEN" data-until="${t.frozen_until}" data-label="frozen">frozen</span>` : '';
    const effects = [
      fx.jammed_until ? `<span class="pill PAUSED" data-until="${fx.jammed_until}" data-label="jammed">jammed</span>` : '',
      fx.warded_until ? `<span class="pill WAITING" data-until="${fx.warded_until}" data-label="ward">ward</span>` : '',
      fx.guide_until ? `<span class="pill LIVE" data-until="${fx.guide_until}" data-label="guide">guide</span>` : '',
    ].join(' ');
    const held = Object.entries(powers).filter(([, n]) => n > 0).map(([k, n]) => `${(POWERS[k] || { en: k }).en}×${n}`).join(' · ') || 'none';
    const target = t.target ? `${t.target.seq ? `#${t.target.seq} ` : ''}${esc(t.target.code)} · ${esc(t.target.name)}` : '-';
    const btn = (action, label, klass = '') => `<button class="btn tiny ${klass}" data-act="${action}" data-id="${t.id}" data-name="${esc(t.team_name)}">${label}</button>`;
    const actions = [
      btn('foul-add', '+ Foul', 'warn'),
      t.foul_count ? btn('foul-remove', '− Foul') : '',
      t.status === 'FROZEN' || fx.jammed_until ? btn('unfreeze', fx.jammed_until && t.status !== 'FROZEN' ? 'Unjam' : 'Unfreeze', 'good') : (['ACTIVE', 'PUZZLE_LOCKED', 'FINAL'].includes(t.base_status) ? btn('freeze', 'Freeze') : ''),
      t.base_status === 'PUZZLE_LOCKED' ? btn('unlock-puzzle', 'Unlock puzzle') : '',
      t.base_status === 'FINAL' ? btn('verify-joker', '🃏 Verify Joker', 'good') : '',
      t.status === 'DISQUALIFIED' ? btn('reinstate', 'Reinstate') : btn('disqualify', 'DQ', 'danger'),
    ].join('');
    return `
      <div class="r2-team-card ${cls}">
        <div class="r2-team-head">
          <div><strong>${esc(t.team_name)}</strong><div class="r2-team-meta">${esc(t.team_code)}${t.leader_phone ? ` · ${esc(t.leader_phone)}` : ''}</div></div>
          <div style="text-align:right;">${pill(t.status)} ${frozen} ${effects}</div>
        </div>
        <div class="r2-progress"><span style="width:${pct}%"></span></div>
        <div class="r2-kv">
          <span>Checkpoints <b>${t.progress}/${t.total}</b></span>
          <span>Fouls <b style="color:${t.foul_count ? '#dc2626' : 'inherit'}">${t.foul_count}</b></span>
          <span title="Powers left">Powers <b>${esc(held)}</b></span>
          ${t.puzzle_attempts ? `<span>Tries <b>${t.puzzle_attempts}</b></span>` : ''}
        </div>
        <div class="r2-kv"><span>Target: ${target}</span></div>
        ${t.start_at && Date.parse(t.start_at) > serverNow ? `<div class="r2-kv"><span>Starts at <b>${fmtTime(t.start_at)}</b> (+${t.start_offset_s}s)</span></div>` : ''}
        ${t.incoming_attack ? `<div class="r2-kv" style="color:#dc2626;">⚔ Incoming ${esc((POWERS[t.incoming_attack.kind] || { en: 'attack' }).en)} - answering...</div>` : ''}
        ${t.disqualified_reason ? `<div class="r2-kv" style="color:#991b1b;">DQ: ${esc(t.disqualified_reason)}</div>` : ''}
        <div class="r2-actions">${actions}</div>
      </div>`;
  }

  function render() {
    const ev = data.event;
    const c = data.counts;
    const serverNow = api.getServerNow();
    const actions = (ACTIONS[ev.status] || []).map(([a, label, klass, icon]) =>
      `<button class="btn ${klass}" data-life="${a}"><span class="mi">${icon}</span> ${label}</button>`).join('');
    const readiness = ev.status === 'DRAFT' && data.readiness
      ? `<div class="dash-card" style="margin-bottom:16px;"><div class="section-header"><span class="mi">checklist</span> Ready to lock?</div>
          <ul class="r2-checklist">${data.readiness.map((r) => `<li><span class="mi ${r.ok ? 'ok' : 'bad'}">${r.ok ? 'check_circle' : 'cancel'}</span><div>${esc(r.label)}<small>${esc(r.detail)}</small></div></li>`).join('')}</ul>
          <p class="r2-hint-text">Fix anything red in <a href="#/setup">Event Setup</a>, <a href="#/setup-routes">Setup Routes</a>, <a href="#/puzzles">Puzzles</a>, <a href="#/teams">Teams</a> or <a href="#/routes">Routes</a>.</p></div>`
      : '';
    box.innerHTML = `
      <div class="dash-card" style="margin-bottom:16px;">
        <div class="r2-row" style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
          <div><div style="font-size:1.05rem;font-weight:700;">${esc(ev.name)}</div>
            <div class="r2-hint-text">${ev.started_at ? `Started ${fmtTime(ev.started_at)}` : 'Not started'}${ev.ended_at ? ` · ended ${fmtTime(ev.ended_at)}` : ''}</div></div>
          <div class="btn-row">${actions}</div>
        </div>
        ${stepper(ev.status)}
      </div>
      ${readiness}
      <div class="stats-row">
        ${[['Teams', c.teams, 'group'], ['Playing', c.playing, 'directions_run'], ['On a puzzle', c.puzzle, 'extension'], ['Frozen', c.frozen, 'ac_unit'],
           ['Jammed', c.jammed, 'radar'], ['Joker hunt', c.final, 'playing_cards'], ['Finished', c.completed, 'emoji_events']]
          .map(([label, n, icon]) => `<div class="stat-card"><div class="section-header" style="margin:0 0 6px;"><span class="mi">${icon}</span>${label}</div><div style="font-size:1.6rem;font-weight:800;font-family:var(--font-mono);">${n}</div></div>`).join('')}
      </div>
      <div class="r2-cols">
        <div class="r2-team-grid">${data.teams.map((t) => teamCard(t, serverNow)).join('') || '<div class="empty-state">No teams yet - add them on the Teams page.</div>'}</div>
        <div style="display:flex;flex-direction:column;gap:16px;">
          <div class="dash-card"><div class="section-header"><span class="mi">bolt</span> Live feed</div>
            <div class="r2-feed">${data.recent.map((e) => `<div><time>${fmtTime(e.at)}</time>${esc(e.message)}</div>`).join('') || '<div class="empty-state">Nothing yet.</div>'}</div>
          </div>
        </div>
      </div>`;
    tickTimers();
  }

  function tickTimers() {
    box.querySelectorAll('[data-until]').forEach((el) => {
      const left = (Date.parse(el.dataset.until) - api.getServerNow()) / 1000;
      const label = el.dataset.label || 'frozen';
      el.textContent = left > 0 ? `${label} ${formatClock(left)}` : (label === 'frozen' ? 'thawing...' : `${label} over`);
    });
  }

  async function load() {
    if (stopped) return;
    try {
      const [dash, full] = await Promise.all([api.admin.dashboard(ctx.eventId), api.admin.event(ctx.eventId)]);
      data = { ...dash, readiness: full.readiness };
      render();
    } catch (err) {
      box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }
  const soon = () => { clearTimeout(debounce); debounce = setTimeout(load, 350); };

  box.addEventListener('click', async (e) => {
    const life = e.target.closest('[data-life]');
    if (life) {
      const action = life.dataset.life;
      if (action === 'restart') { restartGame(); return; }
      if (!(await confirmModal(CONFIRM[action], { okLabel: DONE_LABEL[action], danger: action === 'end' }))) return;
      const res = await guarded(() => api.admin.transition(ctx.eventId, action), DONE[action]);
      if (res) { ctx.reload(); }
      return;
    }
    const act = e.target.closest('[data-act]');
    if (!act) return;
    const { id, name } = act.dataset;
    const a = act.dataset.act;
    if (a === 'foul-add' || a === 'foul-remove') {
      openModal(`${a === 'foul-add' ? 'Add a foul to' : 'Remove a foul from'} ${name}`, `
        <div class="field"><label class="tier-label"><span class="primary">Reason</span><span class="secondary">Logged in the audit trail</span></label>
        <input name="reason" required maxlength="300" /></div>`, {
        submitLabel: a === 'foul-add' ? 'Add foul' : 'Remove foul',
        onSubmit: async (fd) => { await guarded(() => api.admin.teamAction(ctx.eventId, id, 'foul', { action: a === 'foul-add' ? 'add' : 'remove', reason: fd.get('reason') }), 'Foul updated'); load(); },
      });
    } else if (a === 'freeze') {
      openModal(`Freeze ${name}`, `<div class="field"><label class="tier-label"><span class="primary">Seconds</span><span class="secondary">10 - 3600</span></label>
        <input name="duration" type="number" min="10" max="3600" value="120" required /></div>`, {
        submitLabel: 'Freeze',
        onSubmit: async (fd) => { await guarded(() => api.admin.teamAction(ctx.eventId, id, 'freeze', { duration_s: Number(fd.get('duration')) }), 'Team frozen'); load(); },
      });
    } else if (a === 'unlock-puzzle' || a === 'disqualify') {
      openModal(`${a === 'disqualify' ? 'Disqualify' : 'Unlock the puzzle for'} ${name}`, `
        <div class="field"><label class="tier-label"><span class="primary">Reason</span><span class="secondary">Logged in the audit trail</span></label>
        <input name="reason" ${a === 'disqualify' ? 'required' : ''} maxlength="300" /></div>`, {
        submitLabel: a === 'disqualify' ? 'Disqualify' : 'Unlock puzzle',
        onSubmit: async (fd) => { await guarded(() => api.admin.teamAction(ctx.eventId, id, a, { reason: fd.get('reason') }), 'Done'); load(); },
      });
    } else if (a === 'verify-joker') {
      if (!(await confirmModal(`Verify that ${name} found the Joker? This stops their clock.`, { okLabel: 'Verify Joker' }))) return;
      await guarded(() => api.admin.teamAction(ctx.eventId, id, 'verify-joker'), `${name} finished!`);
      load();
    } else {
      await guarded(() => api.admin.teamAction(ctx.eventId, id, a), 'Done');
      load();
    }
  });
  main.querySelector('#refresh').addEventListener('click', load);

  function restartGame() {
    const points = data && data.event && data.event.settings ? data.event.settings.starting_power_points : 'their starting';
    openModal('Restart the game?', `
      <p style="margin:0 0 10px;">This throws the current run away and goes back to <strong>CONFIGURED</strong>, ready to press START again - for a dry run, or a false start.</p>
      <ul class="r2-restart-list">
        <li><strong>Kept:</strong> checkpoints, routes, start order, sentences, prices, settings, the admin audit log.</li>
        <li><strong>Wiped:</strong> every team's progress, fouls, scans, puzzles, timers, face cards found, power uses and this run's game log.</li>
        <li>Disqualified teams stay disqualified - use <em>Reinstate</em> on their card if needed.</li>
      </ul>
      <label class="r2-check" style="display:flex;gap:8px;align-items:flex-start;margin-top:10px;">
        <input type="checkbox" name="refund" style="margin-top:3px;" />
        <span><strong>Refund all power purchases</strong><br><span class="r2-hint-text">Every team goes back to ${esc(String(points))} points and shops again. Leave this off to keep what they bought (with every use reset).</span></span>
      </label>
      <p class="r2-hint-text" style="margin-top:10px;">Type <strong>RESTART</strong> to confirm.</p>
      <input name="confirm" autocomplete="off" placeholder="RESTART" required pattern="RESTART" style="width:100%;" />`, {
      submitLabel: 'Restart the game',
      onSubmit: async (fd) => {
        if (fd.get('confirm') !== 'RESTART') { toast('Type RESTART to confirm', { error: true }); return false; }
        const res = await guarded(() => api.admin.restart(ctx.eventId, fd.get('refund') === 'on'), DONE.restart);
        if (res) ctx.reload();
        return Boolean(res);
      },
    });
  }

  const channel = new LiveChannel(`/admin?event_id=${encodeURIComponent(ctx.eventId)}`, (msg) => {
    if (['dashboard', 'log', 'event_status', 'leaderboard'].includes(msg.type)) soon();
  }, 'admin', {
    onStatus: (s) => {
      wsState.className = `pill ${s === 'open' ? 'LIVE' : 'PAUSED'}`;
      wsState.textContent = s === 'open' ? 'live updates on' : 'reconnecting';
    },
    onOpen: () => load(),
    onAuthError: () => toast('Live updates: session expired - log in again', { error: true }),
  });
  const poll = setInterval(load, 15000);
  const ticker = setInterval(tickTimers, 1000);
  load();

  return () => {
    stopped = true;
    channel.close();
    clearInterval(poll);
    clearInterval(ticker);
    clearTimeout(debounce);
  };
}
