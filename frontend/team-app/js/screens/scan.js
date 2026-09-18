// QR scanner (design doc 6.1). Uses the browser's BarcodeDetector where it
// exists (Chrome/Android), otherwise jsQR from a CDN (iOS Safari, desktop).
// Manual entry is the fallback. Camera access needs HTTPS - or localhost.
import { api } from '../../../shared/js/api.js';
import { FACES, HEADERS } from '../../../shared/js/copy.js';
import { sound } from '../../../shared/js/sound.js';
import { esc, toast, vibrate } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { currentState, refresh } from '../live.js';

const JSQR_URL = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js';

function loadJsQR() {
  if (window.jsQR) return Promise.resolve(window.jsQR);
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = JSQR_URL;
    s.onload = () => resolve(window.jsQR);
    s.onerror = () => reject(new Error('Could not load the QR decoder (no internet?). Type the code instead.'));
    document.head.appendChild(s);
  });
}

function position(timeoutMs) {
  return new Promise((resolve) => {
    if (!navigator.geolocation) { resolve({}); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
      () => resolve({}),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 10000 },
    );
  });
}

export function renderScan(root, navigate, params) {
  root.innerHTML = `
    ${headerHTML(HEADERS.scanner)}
    <div class="r2-scanner" id="scanner">
      <video id="video" playsinline muted></video>
      <div class="r2-scan-frame"><span></span></div>
      <div class="r2-scan-line" id="scan-line"></div>
      <div class="r2-scan-overlay-msg" id="scan-msg" hidden></div>
    </div>
    <p class="r2-scan-hint" id="scan-hint">Point the camera at the checkpoint's QR code.</p>
    <div id="result"></div>
    <button class="r2-linkish" id="manual-toggle" type="button">Can't scan? Type the code printed under the QR</button>
    <form class="r2-manual" id="manual" hidden>
      <input id="manual-code" placeholder="BL2-..." autocomplete="off" autocapitalize="off" spellcheck="false" />
      <button type="submit">SCAN</button>
    </form>
    <div style="height:120px"></div>
    ${navHTML('scan')}
  `;
  bindChrome(root, navigate);

  const video = root.querySelector('#video');
  const scanner = root.querySelector('#scanner');
  const msg = root.querySelector('#scan-msg');
  const hint = root.querySelector('#scan-hint');
  const resultBox = root.querySelector('#result');
  const manual = root.querySelector('#manual');
  let stream = null;
  let stopped = false;
  let busy = false;
  let pausedUntil = 0;
  let loopTimer = null;

  function showMessage(html) {
    msg.innerHTML = html;
    msg.hidden = false;
    root.querySelector('#scan-line').hidden = true;
  }

  function flash(kind) {
    scanner.classList.remove('flash-ok', 'flash-bad');
    scanner.classList.add(kind);
    setTimeout(() => scanner.classList.remove(kind), 900);
  }

  function renderResult(res) {
    const s = currentState();
    const total = res.total || (s && s.team.total_checkpoints) || '?';
    let cls = 'info';
    let title = '';
    let extra = '';
    if (res.result === 'VALID') {
      cls = 'ok';
      title = `CHECKPOINT ${res.checkpoint} / ${total} VERIFIED ✓`;
      if (res.location_name) extra += `<div class="r2-result-sub">${esc(res.location_name)}</div>`;
      if (res.fragment) extra += `<div class="r2-fragment-reveal">Fragment ${res.fragment.seq}: “${esc(res.fragment.text)}”</div>`;
      if (res.face_card) extra += `<div class="r2-face-found">${FACES[res.face_card].short} · YOU FOUND THE ${FACES[res.face_card].en.toUpperCase()}</div>`;
      if (res.geofence_warning) extra += '<div class="r2-result-sub">Location check: you seemed far from this checkpoint. The coordinators can see this.</div>';
      if (res.puzzle) extra += '<button class="cta-btn" id="go-puzzle" type="button" style="margin-top:14px;background:#fff;color:#111;">SOLVE THE PUZZLE →</button>';
      sound.scanSuccess();
      vibrate(90);
      flash('flash-ok');
    } else if (res.result === 'WRONG_QR') {
      cls = 'bad';
      title = '❌ THIS IS NOT YOUR QR';
      extra = '<div class="r2-result-sub">FOUL +1 - this checkpoint isn\'t your current target.</div>';
      sound.error();
      vibrate([220, 100, 220]);
      flash('flash-bad');
    } else {
      title = {
        REPEAT: 'ALREADY CLEARED',
        INVALID: 'NOT A GAME CODE',
        LOCKED: 'PUZZLE FIRST',
        BLOCKED: 'LOCATION CHECK FAILED',
      }[res.result] || res.result;
      extra = `<div class="r2-result-sub">${esc(res.message)}</div>`;
      if (res.puzzle) extra += '<button class="cta-btn" id="go-puzzle" type="button" style="margin-top:14px;background:#fff;color:#111;">OPEN THE PUZZLE →</button>';
      sound.click();
    }
    resultBox.innerHTML = `<div class="r2-result ${cls}"><div class="r2-result-title">${title}</div>${extra}</div>`;
    const go = resultBox.querySelector('#go-puzzle');
    if (go) go.addEventListener('click', () => navigate('#/puzzle'));
  }

  async function submit(code) {
    if (busy || !code) return;
    busy = true;
    pausedUntil = Date.now() + 4000; // don't re-read the same sticker straight away
    hint.textContent = 'Checking...';
    const s = currentState();
    const gps = s && s.event.settings.geofence_mode !== 'off' ? await position(5000) : {};
    try {
      const res = await api.team.scan(code, gps);
      renderResult(res);
      refresh().catch(() => {});
    } catch (err) {
      resultBox.innerHTML = `<div class="r2-result bad"><div class="r2-result-title">CAN'T SCAN RIGHT NOW</div><div class="r2-result-sub">${esc(err.message)}</div></div>`;
      sound.error();
    } finally {
      busy = false;
      hint.textContent = 'Point the camera at the checkpoint\'s QR code.';
    }
  }

  async function startCamera() {
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showMessage('The camera needs a secure (https://) link - or localhost when testing.<br/>Type the code printed under the QR instead.');
      manual.hidden = false;
      return;
    }
    let detect = null;
    try {
      if ('BarcodeDetector' in window && (await window.BarcodeDetector.getSupportedFormats()).includes('qr_code')) {
        const detector = new window.BarcodeDetector({ formats: ['qr_code'] });
        detect = async () => {
          const codes = await detector.detect(video);
          return codes.length ? codes[0].rawValue : null;
        };
      }
    } catch (_) { detect = null; }

    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    } catch (err) {
      showMessage(`Camera unavailable (${esc(err.name || 'blocked')}). Allow camera access in the browser, or type the code instead.`);
      manual.hidden = false;
      return;
    }
    if (stopped) { stream.getTracks().forEach((t) => t.stop()); return; }
    video.srcObject = stream;
    await video.play().catch(() => {});

    if (!detect) {
      try {
        const jsQR = await loadJsQR();
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        detect = async () => {
          const w = video.videoWidth;
          const h = video.videoHeight;
          if (!w || !h) return null;
          const scale = Math.min(1, 640 / Math.max(w, h));
          canvas.width = Math.round(w * scale);
          canvas.height = Math.round(h * scale);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const hit = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
          return hit ? hit.data : null;
        };
      } catch (err) {
        showMessage(esc(err.message));
        manual.hidden = false;
        return;
      }
    }

    const loop = async () => {
      if (stopped) return;
      if (!busy && Date.now() > pausedUntil && video.readyState >= 2) {
        try {
          const value = await detect();
          if (value) submit(value);
        } catch (_) { /* frame not ready */ }
      }
      loopTimer = setTimeout(loop, 180);
    };
    loop();
  }

  root.querySelector('#manual-toggle').addEventListener('click', () => {
    manual.hidden = !manual.hidden;
    if (!manual.hidden) root.querySelector('#manual-code').focus();
  });
  manual.addEventListener('submit', (e) => {
    e.preventDefault();
    const input = root.querySelector('#manual-code');
    const code = input.value.trim();
    if (!code) { toast('Type the code first', { error: true }); return; }
    submit(code);
    input.value = '';
  });

  // Opened from a sticker via the phone's normal camera: #/scan?c=BL2-...
  // Ask before submitting: a rival could post a link to a wrong code in a
  // group chat, and opening it must not cost this team a foul by itself.
  const deepLink = params.get('c');
  if (deepLink) {
    history.replaceState(null, '', '#/scan');
    resultBox.innerHTML = `
      <div class="r2-result info">
        <div class="r2-result-title">SCAN THIS CHECKPOINT CODE?</div>
        <div class="r2-result-sub">You opened a checkpoint link. Only scan codes you found at a checkpoint yourself - a wrong code costs a foul.</div>
        <button class="cta-btn" id="link-yes" type="button" style="margin-top:14px;background:#fff;color:#111;">YES, SCAN IT</button>
        <button class="r2-linkish" id="link-no" type="button" style="padding:10px 0 0;">No, cancel</button>
      </div>`;
    resultBox.querySelector('#link-yes').addEventListener('click', () => submit(deepLink));
    resultBox.querySelector('#link-no').addEventListener('click', () => { resultBox.innerHTML = ''; });
  }
  startCamera();

  return () => {
    stopped = true;
    clearTimeout(loopTimer);
    if (stream) stream.getTracks().forEach((t) => t.stop());
  };
}
