// Rules and VISA popups, reusing Round 1's rules-modal and visa-card styles.
import { FACES, RULES } from '../../../shared/js/copy.js';
import { esc } from '../../../shared/js/ui.js';
import { currentState, refresh } from '../live.js';

export function showRules() {
  const overlay = document.createElement('div');
  overlay.className = 'rules-modal-overlay';
  overlay.innerHTML = `
    <div class="rules-modal-dialog">
      <div class="rules-modal-header">
        <div class="rules-modal-title"><span class="jp">ルール</span><span class="en">Round 2 - How to Play</span></div>
        <button class="rules-modal-close" type="button" aria-label="Close">✕</button>
      </div>
      <div class="rules-modal-body">
        <ol class="instr-steps">
          ${RULES.map((s, i) => `
            <li style="--stagger-i:${i}">
              <div class="instr-step-num">${i + 1}</div>
              <div class="instr-step-text"><span class="en">${s.en}</span><span class="jp">${s.jp}</span></div>
            </li>`).join('')}
        </ol>
      </div>
      <div class="rules-modal-footer">
        <button class="rules-modal-dismiss-btn" type="button">閉じる / Close Rules</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector('.rules-modal-close').addEventListener('click', close);
  overlay.querySelector('.rules-modal-dismiss-btn').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}

export async function showVisa() {
  let s = currentState();
  if (!s) {
    try { s = await refresh(); } catch (_) { return; }
  }
  const t = s.team;
  const faces = Object.entries(s.face_cards).map(([k, v]) => `${FACES[k].short}${v ? '✓' : '·'}`).join('  ');
  const done = t.status === 'COMPLETED';
  const modal = document.createElement('div');
  modal.className = 'bl-warn-popup-overlay';
  modal.innerHTML = `
    <div class="visa-card-container qualified-glow">
      <div class="visa-extension-stamp">
        <span class="stamp-en">EXTENDED</span><span class="stamp-jp">延長</span><span class="stamp-sub">ROUND 2</span>
      </div>
      <div class="visa-card-topbar">
        <div class="visa-gov-tag"><span class="jp">今際の国 滞在許可証</span><span class="en">IMMIGRATION BUREAU OF BORDERLAND</span></div>
        <div class="visa-gothic-badge">V</div>
      </div>
      <div class="visa-bio-grid">
        <div class="visa-bio-cell full-width"><span class="visa-label">TEAM NAME / チーム名</span><span class="visa-value highlight">${esc(t.team_name)}</span></div>
        <div class="visa-bio-cell"><span class="visa-label">TEAM ID / 識別番号</span><span class="visa-value mono">${esc(t.team_code)}</span></div>
        <div class="visa-bio-cell"><span class="visa-label">CHECKPOINTS</span><span class="visa-value mono">${t.progress} / ${t.total_checkpoints}</span></div>
        <div class="visa-bio-cell full-width"><span class="visa-label">FACE CARDS / 絵札</span><span class="visa-value mono">${faces}</span></div>
      </div>
      <div class="visa-status-box qualified">
        <div class="visa-status-header">
          <span class="visa-status-title">VISA STATUS / 滞在資格</span>
          <span class="visa-status-pill qualified">● ${done ? 'CLEARED' : 'EXTENDED'}</span>
        </div>
        <div class="visa-status-main">
          <div class="visa-validity-text qualified">${done ? 'ROUND 2 CLEARED - JOKER FOUND' : 'VISA EXTENDED FOR ROUND 2'}</div>
          <div class="visa-validity-jp">${done ? '第2ラウンド クリア' : '第2ラウンド進行中'}</div>
        </div>
      </div>
      <div class="visa-footer-section">
        <div class="visa-barcode-graphic"></div>
        <div class="visa-serial-code">VISA-AUTH // R2-${esc(t.team_code)}</div>
        <button class="visa-btn-dismiss" type="button">閉じる / CLOSE</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelector('.visa-btn-dismiss').addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
}
