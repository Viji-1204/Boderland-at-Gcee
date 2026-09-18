// Results (spec section 21): the public view (rank / name / time - no fouls)
// and the coordinator-only view (everything, plus .xlsx export).
import { api } from '../../../shared/js/api.js';
import { esc, formatClock } from '../../../shared/js/ui.js';
import { fmtTime, guarded, pill } from '../common.js';

const MEDALS = { 1: '🥇', 2: '🥈', 3: '🥉' };

export function renderResults(main, ctx) {
  let tab = 'coordinator';
  main.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Results</h1>
      <div class="btn-row"><button class="btn primary" id="export"><span class="mi">download</span> Export full results (.xlsx)</button></div></div>
    <div class="r2-tabs">
      <button class="btn active" data-tab="coordinator"><span class="mi">lock</span> Coordinator view (with fouls)</button>
      <button class="btn" data-tab="public"><span class="mi">public</span> Public view (what teams see)</button>
    </div>
    <div id="res"><div class="spinner"></div></div>`;
  const box = main.querySelector('#res');
  let data = null;

  function render() {
    const note = data.event_status === 'ENDED'
      ? '<div class="r2-banner-note info">The game has ended - these results are final and teams can see the public view.</div>'
      : '<div class="r2-banner-note warn">Provisional - teams see results only after you end the game.</div>';
    if (tab === 'public') {
      box.innerHTML = `${note}<div class="dash-card"><table class="dtable">
        <thead><tr><th>Rank</th><th>Team</th><th>Time</th></tr></thead>
        <tbody>${data.public.map((r) => `<tr><td>${MEDALS[r.rank] || r.rank}</td><td>${esc(r.team_name)}</td>
          <td class="mono">${r.finished ? formatClock(r.elapsed_s) : `DNF (${r.checkpoints} checkpoints)`}</td></tr>`).join('')}</tbody>
      </table><p class="r2-hint-text">No foul column, ever - by design.</p></div>`;
      return;
    }
    box.innerHTML = `${note}<div class="dash-card" style="overflow-x:auto;"><table class="dtable">
      <thead><tr><th>#</th><th>Team</th><th>Status</th><th>Time</th><th>Fouls</th><th>Checkpoints</th><th>J Q K</th><th>Atk / Def / Help</th><th>Finished</th></tr></thead>
      <tbody>${data.coordinator.map((r) => `
        <tr>
          <td>${MEDALS[r.rank] || r.rank}</td>
          <td><strong>${esc(r.team_name)}</strong><div class="r2-hint-text mono">${esc(r.team_code)}</div></td>
          <td>${pill(r.status)}</td>
          <td class="mono">${r.elapsed_s != null ? formatClock(r.elapsed_s) : '-'}</td>
          <td class="mono" style="color:${r.foul_count ? '#dc2626' : 'inherit'}">${r.foul_count}</td>
          <td class="mono">${r.checkpoints}/${r.total_checkpoints}</td>
          <td class="mono">${['JACK', 'QUEEN', 'KING'].map((f) => (r.face_cards[f] ? f[0] : '·')).join(' ')}</td>
          <td class="mono">${r.attacks_used} / ${r.defences_used} / ${r.help_used}</td>
          <td class="mono">${fmtTime(r.completed_at)}</td>
        </tr>`).join('')}</tbody>
    </table><p class="r2-hint-text">Ranking: found the Joker, then fewest fouls, then fastest time. Unfinished teams follow, by checkpoints reached.</p></div>`;
  }

  main.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => {
    tab = b.dataset.tab;
    main.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('active', x === b));
    if (data) render();
  }));
  main.querySelector('#export').addEventListener('click', () => guarded(() => api.admin.exportResults(ctx.eventId), 'Downloaded'));

  api.admin.results(ctx.eventId).then((d) => { data = d; render(); })
    .catch((err) => { box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
}
