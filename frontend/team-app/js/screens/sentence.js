// Secret sentence (spec section 14): one fragment per checkpoint, always
// revealed in route order.
import { HEADERS } from '../../../shared/js/copy.js';
import { esc } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState, refresh } from '../live.js';

export function renderSentence(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.sentence)}
    <div class="r2-body" id="sentence-body"><div class="spinner" style="margin:40px auto;"></div></div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#sentence-body');

  function render(s) {
    const total = s.fragments_total || s.team.total_checkpoints;
    const byseq = Object.fromEntries(s.fragments.map((f) => [f.seq, f.text]));
    const rows = Array.from({ length: total }, (_, i) => i + 1).map((seq) => `
      <div class="r2-fragment ${byseq[seq] ? '' : 'locked'}">
        <span class="mono">${String(seq).padStart(2, '0')}/${String(total).padStart(2, '0')}</span>
        <span class="r2-fragment-text">${byseq[seq] ? esc(byseq[seq]) : '• • • •'}</span>
      </div>`).join('');
    const complete = total > 0 && s.fragments.length === total;
    body.innerHTML = `
      <div class="r2-panel">
        <div class="r2-eyebrow">${s.fragments.length} of ${total} fragments</div>
        <p class="r2-sentence-full" style="margin:10px 0 0;">${s.fragments.length ? esc(s.fragments.map((f) => f.text).join(' ')) : '<span class="muted">Clear checkpoints to reveal your sentence.</span>'}</p>
        ${complete ? '<p class="muted" style="margin:10px 0 0;font-size:.8rem;">Complete! Keep it safe - the coordinators may ask for it.</p>' : ''}
      </div>
      <div class="r2-panel">${rows}</div>`;
  }

  const unsubscribe = onState(render);
  refresh().catch((err) => { body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  return unsubscribe;
}
