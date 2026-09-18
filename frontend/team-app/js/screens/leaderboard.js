// Live leaderboard in Round 1's HUD style - checkpoint progress only
// (spec section 17: no fouls, positions, routes, powers or freezes).
import { api } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { esc } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onLive } from '../live.js';

export function renderLeaderboard(root, navigate) {
  root.classList.add('has-leaderboard');
  root.innerHTML = `
    ${headerHTML(HEADERS.leaderboard)}
    <div class="bl-lb-wrapper">
      <div class="bl-lb-scroll-area">
        <div id="lb-area"><div class="spinner" style="margin: 40px auto;"></div></div>
      </div>
    </div>
    ${navHTML('leaderboard')}
  `;
  bindChrome(root, navigate);
  const area = root.querySelector('#lb-area');
  let timer = null;
  let stopped = false;

  function render(board) {
    const me = board.rows.find((r) => r.is_you);
    const total = board.total_checkpoints || 0;
    area.innerHTML = `
      <div class="bl-lb-hud-header">
        <div class="bl-hud-top-bar">
          <div class="bl-hud-beacon"><span class="bl-beacon-dot"></span><span class="bl-beacon-tag">LIVE FEED // 生存順位</span></div>
          <div class="bl-hud-total-tag"><span class="bl-hud-count-val">${board.rows.length}</span> TEAMS IN BORDERLAND</div>
        </div>
        <div class="bl-hud-title-row">
          <div class="bl-hud-main-title">ROUND 2 - THE HUNT</div>
          <div class="bl-hud-sub-title">今際の国 // チェックポイント進捗</div>
        </div>
      </div>
      ${me ? `
        <div class="bl-my-status-card">
          <div class="bl-my-status-left">
            <div class="bl-my-status-badge">▶ YOUR TEAM / 参加チーム</div>
            <div class="bl-my-status-name">${esc(me.team_name)}</div>
            <div class="bl-my-status-metrics">
              <span class="bl-my-stat-pill">POS <strong class="val">#${me.position}</strong></span>
              <span class="bl-my-stat-pill">CHECKPOINTS <strong class="val">${me.checkpoints}/${total}</strong></span>
            </div>
          </div>
        </div>` : ''}
      <div class="bl-lb-list">
        ${board.rows.map((r) => `
          <div class="bl-lb-row ${r.position === 1 ? 'rank-1' : r.position <= 3 ? 'rank-top3' : ''} ${r.is_you ? 'me' : ''}">
            <div class="bl-col-rank"><span class="bl-rank-tag">${String(r.position).padStart(2, '0')}</span></div>
            <div class="bl-col-team">
              <div class="bl-team-label-wrap">
                <span class="bl-team-name">${esc(r.team_name)}</span>
                ${r.is_you ? '<span class="bl-you-badge">[ YOU ]</span>' : ''}
                ${r.finished ? '<span class="r2-finished">🃏 FINISHED</span>' : ''}
              </div>
              <div class="r2-lb-bar"><span style="width:${total ? Math.round((r.checkpoints / total) * 100) : 0}%"></span></div>
            </div>
            <div class="bl-col-pts"><span class="bl-pts-num">${r.checkpoints}</span><span class="bl-pts-unit">/ ${total}</span></div>
          </div>`).join('')}
      </div>
      <div class="bl-lb-end-marker"><span class="bl-end-line"></span><span class="bl-end-text">END OF STANDINGS</span><span class="bl-end-line"></span></div>`;
  }

  async function load() {
    if (stopped) return;
    try {
      render(await api.team.leaderboard());
    } catch (err) {
      area.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  let debounce = null;
  const unsubscribe = onLive('leaderboard', () => {
    clearTimeout(debounce);
    debounce = setTimeout(load, 400);
  });
  load();
  timer = setInterval(load, 15000);

  return () => {
    stopped = true;
    unsubscribe();
    clearInterval(timer);
    clearTimeout(debounce);
    root.classList.remove('has-leaderboard');
  };
}
