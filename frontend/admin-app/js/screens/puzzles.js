// Puzzles are built in - nothing to write or edit. Each checkpoint's type
// follows its number (L01 scrambled words, L02 picture, L03 rock paper
// scissors, L04 X/O, L05 riddle, L06 crossword, then again from L07), and
// every team gets its own version. This page just shows the plan.
import { api } from '../../../shared/js/api.js';
import { esc } from '../../../shared/js/ui.js';
import { pill } from '../common.js';

export function renderPuzzles(main, ctx) {
  main.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Puzzles</h1></div>
    <div id="puzzles"><div class="spinner"></div></div>`;
  const box = main.querySelector('#puzzles');

  api.admin.puzzles(ctx.eventId).then(({ types, checkpoints }) => {
    box.innerHTML = `
      <div class="dash-card" style="margin-bottom:16px;">
        <div class="section-header"><span class="mi">extension</span> Built in - nothing to set up</div>
        <p class="r2-hint-text" style="margin:0 0 12px;">Each checkpoint's puzzle follows its number and repeats every six.
          Every team gets its own version (its own words, riddle, crossword and picture shuffle), so answers can't be
          passed between teams. The two games are played against the server, so results can't be faked. If a team is
          stuck, <strong>Unlock puzzle</strong> on its dashboard card lets it through.</p>
        <div class="r2-puzzle-types">${types.map((t, i) => `
          <div><span class="r2-puzzle-num">${i + 1}</span><strong>${esc(t.label)}</strong>
            <span class="muted">L${String(i + 1).padStart(2, '0')}, L${String(i + 7).padStart(2, '0')}</span>
            <small>${esc(t.instructions)}</small></div>`).join('')}</div>
      </div>
      <div class="dash-card">
        <div class="section-header"><span class="mi">format_list_numbered</span> Your checkpoints</div>
        ${checkpoints.length ? `
          <table class="dtable">
            <thead><tr><th>Code</th><th>Name</th><th>Puzzle</th><th></th></tr></thead>
            <tbody>${checkpoints.map((c) => `
              <tr class="${c.is_selected ? '' : 'unselected'}">
                <td class="mono"><strong>${esc(c.code)}</strong></td>
                <td>${esc(c.name)}</td>
                <td>${esc(c.label)}</td>
                <td>${c.is_selected ? '' : pill('ENDED', 'spare')}</td>
              </tr>`).join('')}</tbody>
          </table>` : '<div class="empty-state">No checkpoints yet - add them in <a href="#/setup-routes">Setup Routes</a>.</div>'}
      </div>`;
  }).catch((err) => {
    box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
  });
}
