// Shared screen chrome: Round 1's header bar (back + 【bracket header】) and
// the diamond bottom nav. Round 1 locked the camera button with "only after
// Round 1" - in Round 2 it opens the QR scanner.

import { glyphSVG } from '../../shared/js/suit-icons.js';

export function headerHTML(entry, { back = '#/home', backLabel = 'HOME' } = {}) {
  return `
    <div class="screen-header-bar">
      <button class="screen-back-btn" id="hdr-back" type="button" data-href="${back}" aria-label="Back">
        ${glyphSVG('back', { size: 18, stroke: 2.5 })}<span>${backLabel}</span>
      </button>
      <div class="bracket-header"><span class="jp">${entry.jp}</span><span class="en">${entry.en}</span></div>
      <div class="screen-header-placeholder"></div>
    </div>`;
}

export function navHTML(active) {
  const btn = (name, icon, label) => `
    <button class="diamond-btn ${active === name ? 'active' : ''}" data-nav="${name}" type="button" aria-label="${label}">
      <span class="diamond-icon">${glyphSVG(icon)}</span>
    </button>`;
  return `
    <nav class="diamond-nav r2-nav">
      ${btn('home', 'home', 'Home')}
      ${btn('scan', 'camera', 'Scan a QR code')}
      ${btn('leaderboard', 'trophy', 'Leaderboard')}
      ${btn('account', 'user', 'Account')}
    </nav>`;
}

const NAV_ROUTES = { home: '#/home', scan: '#/scan', leaderboard: '#/leaderboard', account: '#/account' };

export function bindChrome(root, navigate) {
  const back = root.querySelector('#hdr-back');
  if (back) back.addEventListener('click', () => navigate(back.dataset.href || '#/home'));
  root.querySelectorAll('[data-nav]').forEach((b) => {
    b.addEventListener('click', () => navigate(NAV_ROUTES[b.dataset.nav]));
  });
}
