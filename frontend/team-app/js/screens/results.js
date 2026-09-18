// Final results (spec section 21): rank, team name and time only.
// HARD RULE: this public screen never shows fouls - the coordinator export does.
import { api } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { esc, formatClock } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { currentState } from '../live.js';

const MEDALS = { 1: '🥇', 2: '🥈', 3: '🥉' };

export function renderResults(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.results)}
    <div class="r2-body" id="results-body"><div class="spinner" style="margin:40px auto;"></div></div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#results-body');

  api.team.results().then((data) => {
    const myName = currentState()?.team.team_name;
    body.innerHTML = `
      <div class="r2-panel" style="text-align:center;">
        <div class="r2-eyebrow">${esc(data.event_name)}</div>
        <h3 style="margin:6px 0 0;font-size:1.3rem;">FINAL STANDINGS</h3>
      </div>
      <div class="r2-panel">
        ${data.rows.map((r) => `
          <div class="r2-row" style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,.12);${r.team_name === myName ? 'color:#fbbf24;' : ''}">
            <span style="font-size:1.1rem;font-weight:800;min-width:48px;">${MEDALS[r.rank] || `#${r.rank}`}</span>
            <span style="flex:1;font-weight:700;">${esc(r.team_name)}${r.team_name === myName ? ' <span class="bl-you-badge">[ YOU ]</span>' : ''}</span>
            <span class="mono">${r.finished ? formatClock(r.elapsed_s) : `${r.checkpoints} cp`}</span>
          </div>`).join('')}
      </div>
      <p class="muted" style="text-align:center;font-size:.78rem;">Ranking: found the Joker, then fewest fouls, then fastest time.</p>`;
  }).catch((err) => {
    body.innerHTML = `<div class="r2-empty"><p>${esc(err.message)}</p></div>`;
  });
}
