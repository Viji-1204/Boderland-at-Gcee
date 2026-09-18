// Live control room: lifecycle, readiness, every team at a glance, help queue, live feed.
import { api } from '../../../shared/js/api.js';
import { LiveChannel } from '../../../shared/js/ws.js';
import { esc, formatClock, toast } from '../../../shared/js/ui.js';
import { confirmModal, fmtTime, guarded, openModal, pill } from '../common.js';

const STEPS = ['DRAFT', 'CONFIGURED', 'LIVE', 'PAUSED', 'ENDED'];
const ACTIONS = {
  DRAFT: [['lock', 'Lock configuration', 'primary', 'lock']],
  CONFIGURED: [['start', 'START ROUND 2', 'primary', 'play_arrow'], ['unlock', 'Unlock (back to draft)', '', 'lock_open']],
  LIVE: [['pause', 'Pause game', 'warn', 'pause'], ['end', 'End game', 'danger', 'stop']],
  PAUSED: [['resume', 'Resume game', 'primary', 'play_arrow'], ['end', 'End game', 'danger', 'stop']],
  ENDED: [],
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
    const cls = [t.status, t.help ? 'help' : '', t.incoming_attack_expires_at ? 'attacked' : ''].join(' ');
    const frozen = t.frozen_until ? `<span class="pill FROZEN" data-until="${t.frozen_until}">frozen</span>` : '';
    const target = t.target ? `${t.target.seq ? `#${t.target.seq} ` : ''}${esc(t.target.code)} · ${esc(t.target.name)}` : '-';
    const btn = (action, label, klass = '') => `<button class="btn tiny ${klass}" data-act="${action}" data-id="${t.id}" data-name="${esc(t.team_name)}">${label}</button>`;
    const actions = [
      btn('foul-add', '+ Foul', 'warn'),
      t.foul_count ? btn('foul-remove', '− Foul') : '',
      t.status === 'FROZEN' ? btn('unfreeze', 'Unfreeze', 'good') : (['ACTIVE', 'PUZZLE_LOCKED', 'FINAL'].includes(t.base_status) ? btn('freeze', 'Freeze') : ''),
      t.base_status === 'PUZZLE_LOCKED' ? btn('unlock-puzzle', 'Unlock puzzle') : '',
      t.base_status === 'FINAL' ? btn('verify-joker', '🃏 Verify Joker', 'good') : '',
      t.status === 'DISQUALIFIED' ? btn('reinstate', 'Reinstate') : btn('disqualify', 'DQ', 'danger'),
    ].join('');
    return `
      <div class="r2-team-card ${cls}">
        <div class="r2-team-head">
          <div><strong>${esc(t.team_name)}</strong><div class="r2-team-meta">${esc(t.team_code)}${t.leader_phone ? ` · ${esc(t.leader_phone)}` : ''}</div></div>
          <div style="text-align:right;">${pill(t.status)} ${frozen}</div>
        </div>
        <div class="r2-progress"><span style="width:${pct}%"></span></div>
        <div class="r2-kv">
          <span>Checkpoints <b>${t.progress}/${t.total}</b></span>
          <span>Fouls <b style="color:${t.foul_count ? '#dc2626' : 'inherit'}">${t.foul_count}</b></span>
          <span>A/D/H <b>${powers.ATTACK ?? 0}/${powers.DEFENCE ?? 0}/${powers.HELP ?? 0}</b></span>
          ${t.puzzle_attempts ? `<span>Tries <b>${t.puzzle_attempts}</b></span>` : ''}
        </div>
        <div class="r2-kv"><span>Target: ${target}</span></div>
        ${t.start_at && Date.parse(t.start_at) > serverNow ? `<div class="r2-kv"><span>Starts at <b>${fmtTime(t.start_at)}</b> (+${t.start_offset_s}s)</span></div>` : ''}
        ${t.help ? `<div class="r2-kv" style="color:#92400e;">🆘 Help ${esc(t.help.status.toLowerCase())}${t.help.message ? `: “${esc(t.help.message)}”` : ''}</div>` : ''}
        ${t.incoming_attack_expires_at ? '<div class="r2-kv" style="color:#dc2626;">⚔ Under attack - answering...</div>' : ''}
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
           ['Joker hunt', c.final, 'playing_cards'], ['Finished', c.completed, 'emoji_events'], ['Help waiting', c.pending_help, 'sos']]
          .map(([label, n, icon]) => `<div class="stat-card"><div class="section-header" style="margin:0 0 6px;"><span class="mi">${icon}</span>${label}</div><div style="font-size:1.6rem;font-weight:800;font-family:var(--font-mono);">${n}</div></div>`).join('')}
      </div>
      <div class="r2-cols">
        <div class="r2-team-grid">${data.teams.map((t) => teamCard(t, serverNow)).join('') || '<div class="empty-state">No teams yet - add them on the Teams page.</div>'}</div>
        <div style="display:flex;flex-direction:column;gap:16px;">
          <div class="dash-card"><div class="section-header"><span class="mi">sos</span> Help queue</div>
            ${data.help.length ? data.help.map((h) => `
              <div class="r2-help-item">
                <div style="display:flex;justify-content:space-between;gap:8px;"><strong>${esc(h.team_name)}</strong>${pill(h.status)}</div>
                ${h.message ? `<div>“${esc(h.message)}”</div>` : ''}
                <div class="r2-hint-text">${fmtTime(h.created_at)}${h.handled_by ? ` · ${esc(h.handled_by)}` : ''}</div>
                <div class="r2-actions" style="margin-top:6px;">
                  ${h.status === 'PENDING' ? `<button class="btn tiny" data-help="${h.id}" data-status="ACKNOWLEDGED">On my way</button>` : ''}
                  <button class="btn tiny good" data-help="${h.id}" data-status="RESOLVED">Resolved</button>
                </div>
              </div>`).join('') : '<div class="empty-state" style="padding:10px;">No open requests.</div>'}
          </div>
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
      el.textContent = left > 0 ? `frozen ${formatClock(left)}` : 'thawing...';
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
      if (!(await confirmModal(CONFIRM[action], { okLabel: DONE_LABEL[action], danger: action === 'end' }))) return;
      const res = await guarded(() => api.admin.transition(ctx.eventId, action), DONE[action]);
      if (res) { ctx.reload(); }
      return;
    }
    const help = e.target.closest('[data-help]');
    if (help) {
      await guarded(() => api.admin.updateHelp(ctx.eventId, help.dataset.help, help.dataset.status), 'Help request updated');
      load();
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
