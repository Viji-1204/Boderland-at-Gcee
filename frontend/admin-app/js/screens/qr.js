// Printable QR sheet (spec section 11, design doc 5.7). Each code encodes a
// link to the team app (…/team-app/#/scan?c=TOKEN), so the in-app scanner and
// a phone's normal camera both work. The token is printed underneath as a
// typed fallback. The QR renderer (qrcode-generator) loads from a CDN, so
// printing needs internet.
import { api } from '../../../shared/js/api.js';
import { esc } from '../../../shared/js/ui.js';
import { pill } from '../common.js';

const QR_LIB = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.js';

function loadQrLib() {
  if (window.qrcode) return Promise.resolve(window.qrcode);
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = QR_LIB;
    s.onload = () => resolve(window.qrcode);
    s.onerror = () => reject(new Error('Could not load the QR generator (no internet?). The tokens below still work when typed.'));
    document.head.appendChild(s);
  });
}

export function renderQr(main, ctx) {
  main.innerHTML = `
    <div class="admin-topline no-print">
      <h1 class="admin-h1">QR Codes</h1>
      <div class="btn-row">
        <label style="font-size:.8rem;display:flex;gap:6px;align-items:center;"><input type="checkbox" id="only-selected" checked /> Only checkpoints in the game</label>
        <button class="btn primary" id="print"><span class="mi">print</span> Print</button>
      </div>
    </div>
    <div class="r2-banner-note info no-print">
      Stick each code at its checkpoint. They open <code id="base-url"></code>, so check that address
      works on a phone before printing (use the address teams will actually use, not <code>localhost</code>).
    </div>
    <div id="qr-note" class="no-print"></div>
    <div id="app-link" class="r2-applink no-print"></div>
    <div id="sheet" class="r2-qr-sheet"><div class="spinner"></div></div>`;
  const sheet = main.querySelector('#sheet');
  const note = main.querySelector('#qr-note');
  const appUrl = `${location.origin}/team-app/`;
  const base = `${appUrl}#/scan?c=`;
  main.querySelector('#base-url').textContent = appUrl;
  const onLocalhost = /localhost|127\.0\.0\.1/.test(location.hostname);
  const phoneReady = location.protocol === 'https:' && !onLocalhost;
  if (onLocalhost) {
    note.innerHTML = '<div class="r2-banner-note warn">You opened the console on <strong>localhost</strong> - codes printed now would point phones at localhost. Open the console via the LAN/https address first (the README explains how).</div>';
  } else if (!phoneReady) {
    note.innerHTML = '<div class="r2-banner-note warn">This is an <strong>http://</strong> address: phones can open it, but their camera and GPS stay blocked. Open the console through an <strong>https://</strong> address first (run <code>python dev_https.py</code>; the README explains how).</div>';
  }
  let data = null;
  let qrcode = null;

  // A phone's normal camera opens the team app from this - no typing the address.
  function renderAppLink() {
    if (!qrcode || !phoneReady) return;
    const qr = qrcode(0, 'M');
    qr.addData(appUrl);
    qr.make();
    main.querySelector('#app-link').innerHTML = `
      <img alt="QR that opens the team app" src="${qr.createDataURL(4, 2)}" />
      <div>
        <strong>Phones: scan this to open the team app</strong>
        <code>${esc(appUrl)}</code>
        <span class="muted">Use the phone's normal camera. Test-server warning? Tap Advanced → Proceed.</span>
      </div>`;
  }

  function render() {
    const only = main.querySelector('#only-selected').checked;
    const codes = data.codes.filter((c) => !only || c.is_selected);
    sheet.innerHTML = codes.map((c) => {
      let img = '<span class="muted">QR unavailable</span>';
      if (qrcode) {
        const qr = qrcode(0, 'M');
        qr.addData(base + c.token);
        qr.make();
        img = `<img alt="QR for ${esc(c.code)}" src="${qr.createDataURL(6, 2)}" />`;
      }
      return `
        <div class="r2-qr-card">
          <div class="code">${esc(c.code)}</div>
          <div class="name">${esc(c.name)} ${c.is_selected ? '' : pill('ENDED', 'not in game')}</div>
          <div class="img">${img}</div>
          <div class="token">${esc(c.token)}</div>
          <div class="brand-line">Borderland @ GCEE · Round 2 · ${esc(data.event_name)}</div>
        </div>`;
    }).join('') || '<div class="empty-state">No locations yet.</div>';
  }

  main.querySelector('#only-selected').addEventListener('change', () => data && render());
  main.querySelector('#print').addEventListener('click', () => window.print());

  Promise.all([api.admin.qrCodes(ctx.eventId), loadQrLib().catch((err) => { note.innerHTML += `<div class="r2-banner-note bad">${esc(err.message)}</div>`; return null; })])
    .then(([codes, lib]) => { data = codes; qrcode = lib; renderAppLink(); render(); })
    .catch((err) => { sheet.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
}
