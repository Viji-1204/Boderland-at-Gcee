// My Route: checkpoint timeline, Jack/Queen/King tracker, private foul count.
// Only checkpoints already cleared are named; the next one is radar-only.
import { FACES, HEADERS, TEAM_STATUS } from '../../../shared/js/copy.js';
import { esc } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState, refresh } from '../live.js';

export function renderRoute(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.route)}
    <div class="r2-body" id="route-body"><div class="spinner" style="margin:40px auto;"></div></div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#route-body');

  function render(s) {
    const t = s.team;
    const stops = s.checkpoints.map((c) => `
      <li class="r2-stop ${c.state}">
        <span class="r2-stop-num">${c.state === 'DONE' ? '✓' : c.seq}</span>
        <div>
          <div class="r2-stop-name">${c.state === 'DONE' ? esc(c.name) : c.state === 'CURRENT' ? 'Next target - follow the radar' : '? ? ?'}</div>
          <div class="muted" style="font-size:.75rem;">Checkpoint ${c.seq}${c.seq === 1 ? ' · your start' : ''}</div>
        </div>
      </li>`).join('');
    const faces = Object.keys(FACES).map((k) => `
      <div class="r2-face ${s.face_cards[k] ? 'found' : ''}">
        <div class="r2-face-letter">${FACES[k].short}</div>
        <small>${FACES[k].en.toUpperCase()}${s.face_cards[k] ? ' ✓' : ''}</small>
      </div>`).join('');
    const final = ['FINAL', 'COMPLETED'].includes(t.status)
      ? `<div class="r2-panel"><h3>🃏 Final destination</h3><p style="margin:0;">${t.status === 'COMPLETED' ? 'Joker found - well played!' : `Every checkpoint is cleared. Follow the radar to <strong>${esc(s.event.final_location_name || "the coordinators' bench")}</strong> and find the Joker.`}</p></div>`
      : '';
    body.innerHTML = `
      <div class="r2-panel">
        <div class="r2-row">
          <div><div class="r2-eyebrow">Checkpoints cleared</div><div class="r2-big-number">${t.progress}<span class="muted" style="font-size:1rem;"> / ${t.total_checkpoints}</span></div></div>
          <span class="r2-pill ${t.status}">${esc((TEAM_STATUS[t.status] || { en: t.status }).en)}</span>
        </div>
      </div>
      ${final}
      <div class="r2-panel"><h3>Face cards</h3><p class="muted" style="margin:0 0 10px;font-size:.8rem;">Met in order: Jack → Queen → King.</p><div class="r2-faces">${faces}</div></div>
      <div class="r2-panel"><h3>Your route</h3><ul class="r2-timeline">${stops}</ul></div>
      <div class="r2-panel r2-row">
        <div><div class="r2-eyebrow">Fouls (only you can see this)</div><div class="muted" style="font-size:.78rem;">Fewer fouls win ties.</div></div>
        <div class="r2-big-number" style="color:${t.foul_count ? 'var(--bl-red)' : 'inherit'}">${t.foul_count}</div>
      </div>`;
  }

  const unsubscribe = onState(render);
  refresh().catch((err) => { body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  return unsubscribe;
}
