// Radar (spec section 13, design doc 4.5 / 6.2). The phone sends its GPS
// position; the server answers with a rounded distance and bearing to the
// current target only - never its name or coordinates. With a compass the
// needle turns with the phone; without one, the dial is north-up.
//
// Two powers change the picture: a Guide (the server also sends the target's
// name and position, shown here with a Google Maps walking route) and a
// rival's Jam (the dial goes dark until the timer runs out).
import { api } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { glyphSVG, needleSVG } from '../../../shared/js/suit-icons.js';
import { esc, formatClock } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState } from '../live.js';

export function renderRadar(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.radar)}
    <div class="r2-body">
      <div class="r2-radar-wrap">
        <div class="r2-eyebrow" id="target-label">Radar</div>
        <div class="r2-dial locked" id="dial">
          <div class="r2-dial-ring" id="ring"><span>N</span></div>
          <div class="r2-needle-box" id="needle">${needleSVG()}</div>
          <div class="r2-dial-lock" id="lock">${glyphSVG('lock', { size: 44, stroke: 1.8 })}</div>
        </div>
        <div class="r2-distance" id="distance">--</div>
        <div class="r2-proximity" id="proximity">Starting the radar...</div>
        <div class="status-note" id="note"></div>
        <div class="r2-guide" id="guide" hidden>
          <div class="r2-eyebrow" id="guide-head">GUIDE · ends in <span id="guide-left">--:--</span></div>
          <div class="r2-guide-name" id="guide-name"></div>
          <div class="r2-guide-meta" id="guide-meta"></div>
          <a class="cta-btn" id="guide-maps" href="#" target="_blank" rel="noopener">${glyphSVG('map', { size: 18, stroke: 2 })} OPEN IN GOOGLE MAPS</a>
        </div>
        <div style="display:grid;gap:10px;width:100%;max-width:340px;">
          <button class="cta-btn" id="locate-btn" type="button" hidden>ALLOW LOCATION</button>
          <button class="cta-btn ghost" id="compass-btn" type="button" hidden>ENABLE COMPASS</button>
          <button class="cta-btn ghost" id="scan-btn" type="button">I FOUND IT - SCAN THE QR</button>
        </div>
      </div>
    </div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);

  const $ = (id) => root.querySelector(id);
  const dial = $('#dial');
  const ring = $('#ring');
  const needle = $('#needle');
  const lock = $('#lock');
  const distanceEl = $('#distance');
  const proximityEl = $('#proximity');
  const noteEl = $('#note');
  const labelEl = $('#target-label');
  const locateBtn = $('#locate-btn');
  const compassBtn = $('#compass-btn');
  const guideEl = $('#guide');
  const guideHead = $('#guide-head');
  const guideName = $('#guide-name');
  const guideMeta = $('#guide-meta');
  const guideMaps = $('#guide-maps');
  $('#scan-btn').addEventListener('click', () => navigate('#/scan'));

  let pos = null;
  let heading = null;
  let last = null;
  let watchId = null;
  let pollTimer = null;
  let stopped = false;
  let geoError = '';

  function applyRotation() {
    if (!last || last.locked || last.needs_location) return;
    const h = heading ?? 0;
    ring.style.transform = `rotate(${-h}deg)`;
    needle.style.transform = `rotate(${(last.bearing_deg - h + 360) % 360}deg)`;
  }

  function guideClock() {
    if (!last || !last.guided || !last.guide_until) return;
    const left = (Date.parse(last.guide_until) - api.getServerNow()) / 1000;
    const el = guideEl.querySelector('#guide-left');
    if (el) el.textContent = left > 0 ? formatClock(left) : '00:00';
    if (left <= 0) poll();
  }

  function render() {
    const r = last;
    if (!r) return;
    const guided = Boolean(r.guided && r.target && !r.locked);
    dial.classList.toggle('locked', Boolean(r.locked || r.needs_location));
    dial.classList.toggle('near', Boolean(r.near));
    dial.classList.toggle('jammed', Boolean(r.locked && r.jammed));
    dial.classList.toggle('guided', guided);
    lock.hidden = !(r.locked || r.needs_location);
    needle.hidden = Boolean(r.locked || r.needs_location);
    labelEl.textContent = guided && !r.is_start ? `GUIDE · ${r.target_label || ''}` : (r.target_label || 'Radar');
    proximityEl.classList.toggle('near', Boolean(r.near));
    locateBtn.hidden = !r.needs_location;
    guideEl.hidden = !guided;
    if (guided) {
      if (r.is_start && !r.guide_until) guideHead.textContent = 'START HERE · your first checkpoint';
      else guideHead.innerHTML = 'GUIDE · ends in <span id="guide-left">--:--</span>';
      guideName.textContent = r.target.name || 'Your next checkpoint';
      guideMeta.textContent = `${r.target.latitude.toFixed(5)}, ${r.target.longitude.toFixed(5)}` + (r.needs_location ? '' : ` · ${r.distance_m} m · bearing ${r.bearing_deg}°`);
      guideMaps.href = r.target.maps_url;
      guideClock();
    }

    if (r.locked) {
      distanceEl.textContent = '--';
      proximityEl.textContent = r.reason;
      const until = r.frozen_until || r.jammed_until;
      noteEl.textContent = until ? `${r.jammed ? 'Radar back' : 'Unfreezes'} in ${formatClock((Date.parse(until) - api.getServerNow()) / 1000)}` : '';
      return;
    }
    if (r.needs_location) {
      distanceEl.textContent = '--';
      proximityEl.textContent = geoError || r.reason;
      noteEl.textContent = window.isSecureContext ? '' : 'Location needs a secure (https://) link - or localhost when testing.';
      return;
    }
    distanceEl.innerHTML = r.near && !guided ? 'HERE' : `${r.distance_m}<small>m</small>`;
    proximityEl.textContent = guided && !r.near ? `Exact: ${r.distance_m} m, ${r.bearing_deg}° - or follow the map` : r.proximity;
    const acc = pos && pos.accuracy ? `GPS ±${Math.round(pos.accuracy)} m` : '';
    noteEl.textContent = [acc, heading == null ? 'No compass: the top of the dial is North' : ''].filter(Boolean).join(' · ');
    applyRotation();
  }

  async function poll() {
    if (stopped) return;
    try {
      last = await api.team.radar(pos?.lat, pos?.lng, pos?.accuracy);
      render();
    } catch (err) {
      proximityEl.textContent = err.message;
    }
  }

  function startGps() {
    if (!navigator.geolocation) {
      geoError = 'This browser has no location support.';
      return;
    }
    watchId = navigator.geolocation.watchPosition(
      (p) => {
        const first = !pos;
        geoError = '';
        pos = { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
        if (first) poll();
      },
      (err) => {
        geoError = err.code === 1 ? 'Location permission denied - allow it in the browser settings.' : 'Waiting for a GPS fix...';
        render();
      },
      { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 },
    );
  }

  function onOrientation(e) {
    let h = null;
    if (typeof e.webkitCompassHeading === 'number') h = e.webkitCompassHeading; // iOS
    else if (e.absolute && typeof e.alpha === 'number') h = (360 - e.alpha) % 360; // Android
    if (h != null) {
      heading = h;
      compassBtn.hidden = true;
      applyRotation();
    }
  }

  function startCompass() {
    window.addEventListener('deviceorientationabsolute', onOrientation, true);
    window.addEventListener('deviceorientation', onOrientation, true);
  }

  if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
    compassBtn.hidden = false; // iOS asks for permission on a tap
    compassBtn.addEventListener('click', async () => {
      try {
        if ((await DeviceOrientationEvent.requestPermission()) === 'granted') startCompass();
      } catch (_) { /* denied */ }
    });
  } else {
    startCompass();
  }

  locateBtn.addEventListener('click', () => {
    if (watchId != null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    startGps();
  });

  startGps();
  poll();
  pollTimer = setInterval(poll, 3000);
  const clockTimer = setInterval(() => { guideClock(); if (last && last.locked) render(); }, 1000);
  const unsubscribe = onState(() => poll()); // puzzle solved / frozen / jammed / guided -> re-check at once

  return () => {
    stopped = true;
    unsubscribe();
    clearInterval(pollTimer);
    clearInterval(clockTimer);
    if (watchId != null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    window.removeEventListener('deviceorientationabsolute', onOrientation, true);
    window.removeEventListener('deviceorientation', onOrientation, true);
  };
}
