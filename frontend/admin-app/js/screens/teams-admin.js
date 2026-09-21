// Round 1's Teams screen, adapted: event-scoped, sentences, Round 2 status.
import { api } from '../../../shared/js/api.js';
import { esc, toast } from '../../../shared/js/ui.js';
import { confirmModal, guarded, openModal, passwordModal, pill } from '../common.js';
import { openTeamImportModal } from './team-import.js';

export function renderTeamsAdmin(main, ctx) {
  const draft = ctx.event && ctx.event.status === 'DRAFT';
  main.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Teams</h1>
      <div class="btn-row">
        ${ctx.isSuper ? `<button id="import-teams" class="btn primary" ${draft ? '' : 'disabled'}><span class="mi">upload_file</span> Import from Sheet</button>` : ''}
        <button id="new-team" class="btn" ${draft ? '' : 'disabled'}><span class="mi">person_add</span> New Team</button>
      </div>
    </div>
    ${draft ? '' : '<div class="r2-banner-note warn">Teams can only be added or removed while the event is in DRAFT. Names, contacts and passwords can still be edited.</div>'}
    <div id="teams-body"><div class="spinner"></div></div>
  `;
  const body = main.querySelector('#teams-body');

  async function load() {
    body.innerHTML = '<div class="spinner"></div>';
    try {
      const teams = await api.admin.teams.list(ctx.eventId);
      if (!teams.length) {
        body.innerHTML = `<div class="empty-state"><div class="empty-icon"><span class="mi">group</span></div>
          No teams yet. ${ctx.isSuper ? 'Import the registration sheet (or Round 1\'s "Round 2 Qualifiers" export) to create them all at once - teams keep their Round 1 login.' : ''}</div>`;
        return;
      }
      body.innerHTML = `
        <div class="dash-card">
          <div style="font-size:.8rem;color:#64748b;margin-bottom:12px;">${teams.length} team(s)</div>
          <table class="dtable">
            <thead><tr><th>Code</th><th>Name</th><th>Leader</th><th>Phone</th><th>Sentence</th><th>Status</th><th>Progress</th><th>Actions</th></tr></thead>
            <tbody>
              ${teams.map((t) => `
                <tr>
                  <td class="mono"><strong>${esc(t.team_code)}</strong></td>
                  <td>${esc(t.team_name)}</td>
                  <td>${esc(t.leader_name) || '<span class="muted">-</span>'}</td>
                  <td class="mono">${esc(t.leader_phone) || '<span class="muted">-</span>'}</td>
                  <td style="max-width:220px;font-size:.74rem;">${t.sentence ? esc(t.sentence) : '<span style="color:#dc2626;">missing</span>'}</td>
                  <td>${pill(t.status)}</td>
                  <td class="mono">${t.progress}/${t.route_length}</td>
                  <td><div class="btn-row">
                    <button class="btn tiny" data-edit="${t.id}"><span class="mi mi-sm">edit</span> Edit</button>
                    <button class="btn tiny" data-pw="${t.id}" data-name="${esc(t.team_name)}"><span class="mi mi-sm">key</span> PW</button>
                    ${ctx.isSuper && draft ? `<button class="btn tiny danger" data-del="${t.id}" data-name="${esc(t.team_name)}"><span class="mi mi-sm">delete</span></button>` : ''}
                  </div></td>
                </tr>`).join('')}
            </tbody>
          </table>
          <p class="r2-hint-text">Every team gets a different secret sentence automatically when it is created (an Alice in Borderland line from a pool of 20) - nothing to type. You can still change one while the game is in DRAFT: put <code>|</code> between words to choose the cut points yourself. Sentences are split into one fragment per checkpoint at lock.
            ${teams.some((t) => !t.sentence) ? '<button class="btn tiny primary" id="deal-sentences" type="button" style="margin-left:8px;"><span class="mi mi-sm">auto_fix_high</span> Deal sentences to the teams missing one</button>' : ''}</p>
        </div>`;

      const deal = body.querySelector('#deal-sentences');
      if (deal) deal.addEventListener('click', async () => {
        if (await guarded(() => api.admin.teams.dealSentences(ctx.eventId), 'Sentences dealt')) load();
      });

      body.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', () => editTeam(teams.find((t) => t.id === b.dataset.edit))));
      body.querySelectorAll('[data-pw]').forEach((b) => b.addEventListener('click', async () => {
        const pw = await passwordModal(`New password for ${b.dataset.name}`, 4);
        if (!pw) return;
        await guarded(() => api.admin.teams.setPassword(ctx.eventId, b.dataset.pw, pw), 'Password updated');
      }));
      body.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
        if (!(await confirmModal(`Delete ${b.dataset.name}? This can't be undone.`, { okLabel: 'Delete team', danger: true }))) return;
        if (await guarded(() => api.admin.teams.remove(ctx.eventId, b.dataset.del), 'Team deleted')) load();
      }));
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  function field(name, label, value = '', extra = '') {
    return `<div class="field"><label class="tier-label"><span class="primary">${label}</span></label><input name="${name}" value="${esc(value || '')}" ${extra} /></div>`;
  }

  function editTeam(t) {
    openModal(`Edit ${t.team_name}`, `
      ${field('team_name', 'Team name', t.team_name, 'required maxlength="120"')}
      ${field('leader_name', 'Leader name', t.leader_name)}
      ${field('leader_phone', 'Leader phone', t.leader_phone)}
      ${field('leader_email', 'Leader email', t.leader_email)}
      <div class="field"><label class="tier-label"><span class="primary">Secret sentence</span><span class="secondary">${draft ? 'Split across the checkpoints' : 'Locked - fragments already cut'}</span></label>
      <textarea class="r2-textarea" name="sentence" ${draft ? '' : 'disabled'}>${esc(t.sentence || '')}</textarea></div>`, {
      onSubmit: async (fd) => {
        const body = { team_name: fd.get('team_name'), leader_name: fd.get('leader_name'), leader_phone: fd.get('leader_phone'), leader_email: fd.get('leader_email') };
        if (draft) body.sentence = fd.get('sentence');
        if (await guarded(() => api.admin.teams.update(ctx.eventId, t.id, body), 'Team saved')) load();
      },
    });
  }

  const newBtn = main.querySelector('#new-team');
  newBtn.addEventListener('click', () => openModal('Create a team', `
    ${field('team_name', 'Team name', '', 'required maxlength="120" placeholder="e.g. Dragon Warriors"')}
    ${field('team_code', 'Team code (optional)', '', 'placeholder="Leave empty to generate B@GCEE-####"')}
    ${field('leader_name', 'Leader name')}
    ${field('leader_phone', 'Leader phone', '', 'placeholder="Password = first 4 digits"')}
    ${field('password', 'Password (optional)', '', 'placeholder="Only if you don\'t want the phone rule"')}
    <div class="field"><label class="tier-label"><span class="primary">Secret sentence (optional)</span><span class="secondary">Leave empty - a different Alice in Borderland line is dealt to each team</span></label><textarea class="r2-textarea" name="sentence" placeholder="Dealt automatically if left empty"></textarea></div>`, {
    submitLabel: 'Create team',
    onSubmit: async (fd) => {
      const body = Object.fromEntries(Array.from(fd.entries()).map(([k, v]) => [k, String(v).trim() || null]));
      const res = await guarded(() => api.admin.teams.create(ctx.eventId, body));
      if (!res) return false;
      toast(`Created ${res.team_code} - password ${res.password}. Sentence: ${res.sentence || '-'}`, { success: true, duration: 9000 });
      load();
      return true;
    },
  }));

  const importBtn = main.querySelector('#import-teams');
  if (importBtn) importBtn.addEventListener('click', () => openTeamImportModal(ctx.eventId, load));

  load();
}
