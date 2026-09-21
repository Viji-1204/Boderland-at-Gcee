// Setup Routes: the checkpoint library - the spots teams walk between.
// They outlive any single run of the game. Stand at a spot, tap +, and its GPS point (plus an
// optional photo) is saved. The list below is the database's view, with edit
// and delete. The set of checkpoints is frozen while an event is locked or
// running (its routes depend on it); names, GPS points and photos can always
// be fixed. (The Jack, Queen and King aren't set here: each team gets its
// own, dealt at random on the Routes page.) Works on a phone - that's how
// it's meant to be used.
import { api } from '../../../shared/js/api.js';
import { esc, toast } from '../../../shared/js/ui.js';
import { confirmModal, guarded, openModal, pill } from '../common.js';

const CODES = Array.from({ length: 15 }, (_, i) => `L${String(i + 1).padStart(2, '0')}`);
const MIN_IN_GAME = 7;
const MAX_IN_GAME = 9;

// --- GPS -------------------------------------------------------------------

/** Watch the GPS and report the most accurate fix so far. Returns stop(). */
function watchBestFix(onFix, onError) {
  if (!window.isSecureContext) {
    onError('Location needs a secure link: open this console on https:// or localhost (README section 3). You can type the coordinates instead.');
    return () => {};
  }
  if (!navigator.geolocation) {
    onError('This browser has no location support. Type the coordinates instead.');
    return () => {};
  }
  let best = null;
  const id = navigator.geolocation.watchPosition(
    (p) => {
      const fix = { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy, at: Date.now() };
      // Keep the sharpest fix, but let a fresh one replace a stale best.
      if (!best || fix.accuracy <= best.accuracy || fix.at - best.at > 30000) best = fix;
      onFix(best);
    },
    (err) => onError(err.code === 1
      ? 'Location is blocked for this site. Allow it in the browser settings, then close and reopen this form.'
      : 'Still looking for a GPS fix - stay still, or step into the open.'),
    { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
  );
  return () => navigator.geolocation.clearWatch(id);
}

function gpsBoxHTML(waitingText) {
  return `
    <div class="r2-gps" data-gps>
      <span class="mi">my_location</span>
      <div>
        <div class="r2-gps-main" data-gps-main>${esc(waitingText)}</div>
        <div class="r2-gps-sub" data-gps-sub>Allow location if asked. Accuracy gets better over a few seconds.</div>
      </div>
    </div>`;
}

/** Fill the form's latitude/longitude from the GPS until the user types their own. */
function followGps(el, form) {
  const box = el.querySelector('[data-gps]');
  const mainLine = el.querySelector('[data-gps-main]');
  const subLine = el.querySelector('[data-gps-sub]');
  let typed = false;
  const onType = () => { typed = true; };
  form.latitude.addEventListener('input', onType);
  form.longitude.addEventListener('input', onType);
  return watchBestFix((fix) => {
    const m = Math.round(fix.accuracy);
    box.dataset.quality = m <= 15 ? 'good' : m <= 35 ? 'ok' : 'poor';
    mainLine.textContent = `${fix.lat.toFixed(6)}, ${fix.lng.toFixed(6)}`;
    subLine.textContent = m <= 35 ? `±${m} m - good` : `±${m} m - wait a moment or step into the open for a better fix`;
    if (!typed) {
      form.latitude.value = fix.lat.toFixed(6);
      form.longitude.value = fix.lng.toFixed(6);
    }
  }, (message) => {
    box.dataset.quality = 'poor';
    mainLine.textContent = 'No location yet';
    subLine.textContent = message;
  });
}

// --- photos ----------------------------------------------------------------

function toJpeg(img, maxSide, quality) {
  const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('encode'))), 'image/jpeg', quality);
  });
}

/** Phone photos are several MB: send ~1600 px for viewing plus a small thumbnail. */
async function preparePhoto(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const [full, thumb] = await Promise.all([toJpeg(img, 1600, 0.82), toJpeg(img, 320, 0.72)]);
    return {
      full: new File([full], 'photo.jpg', { type: 'image/jpeg' }),
      thumb: new File([thumb], 'thumb.jpg', { type: 'image/jpeg' }),
      previewUrl: URL.createObjectURL(thumb),
    };
  } catch (_) {
    throw new Error("Couldn't read that photo - try again, or pick a JPEG or PNG.");
  } finally {
    URL.revokeObjectURL(url);
  }
}

function photoPickerHTML(hasPhoto) {
  return `
    <div class="r2-photo-pick">
      <div class="r2-photo-label">Photo of the spot <span class="muted">(shown to a team as a photo hint when it is standing here but can't find the sticker - and helps coordinators find it)</span></div>
      <input type="file" accept="image/*" capture="environment" hidden data-photo-input />
      <div class="r2-photo-preview" data-photo-preview hidden><img alt="Photo preview" /></div>
      <div class="btn-row">
        <button type="button" class="btn" data-photo-take><span class="mi">photo_camera</span> <span data-photo-take-label>${hasPhoto ? 'Replace photo' : 'Take photo'}</span></button>
        <button type="button" class="btn danger" data-photo-remove ${hasPhoto ? '' : 'hidden'}><span class="mi">hide_image</span> Remove photo</button>
      </div>
    </div>`;
}

/**
 * Wires the picker. `current` is the existing photo's URL (or null).
 * Returns get() -> { photo: {full, thumb} | null, remove: boolean }.
 */
function wirePhotoPicker(el, current) {
  const input = el.querySelector('[data-photo-input]');
  const preview = el.querySelector('[data-photo-preview]');
  const previewImg = preview.querySelector('img');
  const takeBtn = el.querySelector('[data-photo-take]');
  const takeLabel = el.querySelector('[data-photo-take-label]');
  const removeBtn = el.querySelector('[data-photo-remove]');
  const choice = { photo: null, remove: false };
  let previewUrl = null; // a newly taken photo
  let savedUrl = null; // the one already on the server

  const show = (url) => {
    preview.hidden = !url;
    if (url) previewImg.src = url;
    removeBtn.hidden = !url;
    takeLabel.textContent = url ? 'Retake photo' : 'Take photo';
  };
  if (current) {
    current.then((url) => { savedUrl = url; if (!choice.photo && !choice.remove) show(url); }).catch(() => {});
  }

  takeBtn.addEventListener('click', () => input.click());
  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    takeBtn.disabled = true;
    takeLabel.textContent = 'Processing...';
    try {
      const prepared = await preparePhoto(file);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = prepared.previewUrl;
      choice.photo = { full: prepared.full, thumb: prepared.thumb };
      choice.remove = false;
      show(previewUrl);
    } catch (err) {
      toast(err.message, { error: true });
      show(choice.photo ? previewUrl : (choice.remove ? null : savedUrl));
    } finally {
      takeBtn.disabled = false;
    }
  });
  removeBtn.addEventListener('click', () => {
    choice.photo = null;
    choice.remove = true;
    show(null);
  });
  return {
    get: () => choice,
    dispose: () => { if (previewUrl) URL.revokeObjectURL(previewUrl); },
  };
}

// --- screen ----------------------------------------------------------------

export function renderSetupRoutes(main, ctx) {
  main.innerHTML = `
    <div class="r2-setup-routes">
      <div class="admin-topline">
        <div>
          <h1 class="admin-h1">Setup Routes</h1>
          <p class="r2-hint-text" style="margin:2px 0 0;">The checkpoints teams walk between. Stand at a spot and tap <strong>+</strong> to save its GPS point, with an optional photo. They stay from run to run - restart the game and reuse them.</p>
        </div>
        <div id="status"></div>
      </div>
      <div id="box"><div class="spinner"></div></div>
    </div>
    <button class="r2-fab" id="add" type="button" hidden aria-label="Add a checkpoint at my current location" title="Add a checkpoint here"><span class="mi">add</span></button>`;
  const box = main.querySelector('#box');
  const addBtn = main.querySelector('#add');
  const photoUrls = new Map(); // "id|version|size" -> object URL
  let inUse = null; // the event whose routes lock the set of checkpoints, if any
  let locations = [];

  function photoUrl(loc, thumb) {
    const key = `${loc.id}|${loc.photo_updated_at}|${thumb ? 't' : 'f'}`;
    if (!photoUrls.has(key)) {
      photoUrls.set(key, api.admin.checkpointPhoto(loc.id, { thumb, version: loc.photo_updated_at })
        .then((blob) => URL.createObjectURL(blob))
        .catch((err) => { photoUrls.delete(key); throw err; }));
    }
    return photoUrls.get(key);
  }

  async function load() {
    try {
      const [usage, locs] = await Promise.all([api.admin.checkpointsInUse(), api.admin.checkpoints()]);
      inUse = usage.event;
      locations = locs;
      render();
    } catch (err) {
      box.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  function card(l, draft) {
    const hasGps = !(l.latitude === 0 && l.longitude === 0);
    const coords = `${l.latitude.toFixed(6)}, ${l.longitude.toFixed(6)}`;
    return `
      <div class="r2-ckpt ${l.is_selected ? '' : 'out'}">
        <button type="button" class="r2-ckpt-photo" data-photo="${l.id}" ${l.has_photo ? '' : 'disabled'} aria-label="${l.has_photo ? `View photo of ${esc(l.code)}` : 'No photo yet'}">
          ${l.has_photo ? '<img alt="" />' : '<span class="mi">no_photography</span>'}
        </button>
        <div class="r2-ckpt-body">
          <div class="r2-ckpt-title"><strong class="mono">${esc(l.code)}</strong> ${esc(l.name)}</div>
          <div class="r2-ckpt-coords">${hasGps
            ? `<a href="https://www.google.com/maps/search/?api=1&query=${l.latitude},${l.longitude}" target="_blank" rel="noopener" title="Open in Google Maps"><span class="mi mi-sm">map</span> ${coords}</a>`
            : '<span class="bad">No GPS point yet</span>'} · radius ${Math.round(l.geofence_radius_m)} m</div>
          <div class="r2-ckpt-flags">
            ${l.is_selected ? pill('LIVE', 'In the game') : pill('ENDED', 'Spare')}
            ${pill('COMPLETED', `Puzzle: ${l.puzzle_label}`)}
          </div>
        </div>
        <div class="r2-ckpt-actions">
          <button class="btn tiny" type="button" data-edit="${l.id}"><span class="mi mi-sm">edit</span> Edit</button>
          ${draft ? `<button class="btn tiny danger" type="button" data-del="${l.id}" aria-label="Delete ${esc(l.code)}"><span class="mi mi-sm">delete</span> Delete</button>` : ''}
        </div>
      </div>`;
  }

  function render() {
    const draft = !inUse; // no locked or running event: the set of checkpoints may change
    const inGame = locations.filter((l) => l.is_selected);
    const freeCodes = CODES.filter((c) => !locations.some((l) => l.code === c));
    const countOk = inGame.length >= MIN_IN_GAME && inGame.length <= MAX_IN_GAME;
    main.querySelector('#status').innerHTML = inUse ? pill(inUse.status, `Locked: game ${inUse.status}`) : pill('DRAFT', 'Editable');
    addBtn.hidden = !(draft && freeCodes.length);

    box.innerHTML = `
      ${draft ? '' : `<div class="r2-banner-note warn">
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
          <div style="flex:1;min-width:220px;">The game is <strong>${esc(inUse.status)}</strong> and its routes are built on these checkpoints, so none can be added, deleted or moved in or out of the game right now. Names, GPS points and photos can still be fixed.</div>
          ${inUse.status === 'CONFIGURED'
            ? '<button class="btn primary" type="button" id="unlock-game"><span class="mi">lock_open</span> Unlock the game</button>'
            : '<a class="btn" href="#/dashboard"><span class="mi">restart_alt</span> Restart it on the dashboard first</a>'}
        </div></div>`}
      ${draft && !freeCodes.length ? '<div class="r2-banner-note info">All 15 checkpoint codes are used. Delete one to add another.</div>' : ''}
      <div class="r2-ckpt-summary">
        ${pill(countOk ? 'LIVE' : 'DISQUALIFIED', `${inGame.length} in the game`)}
        <span class="muted">need ${MIN_IN_GAME}-${MAX_IN_GAME}</span>
        <span>${locations.length}/15 checkpoints</span>
      </div>
      ${locations.length ? `<div class="r2-ckpt-list">${locations.map((l) => card(l, draft)).join('')}</div>` : `
        <div class="empty-state"><div class="empty-icon"><span class="mi mi-xl">add_location_alt</span></div>
          No checkpoints yet. Go to the first spot and tap <strong>+</strong>.</div>`}
      <p class="r2-hint-text" style="margin-top:14px;">These checkpoints outlive any single run: if a game goes wrong, <em>Restart game</em> on the dashboard (then <em>Unlock</em> if the set-up needs changing) and generate routes again - the same spots and the QR stickers already on the walls carry over. The Jack, Queen and King are dealt to each team separately when routes are generated on the <a href="#/routes">Routes</a> page.</p>`;

    box.querySelectorAll('[data-photo]').forEach((btn) => {
      const loc = locations.find((l) => l.id === btn.dataset.photo);
      if (!loc.has_photo) return;
      photoUrl(loc, true)
        .then((url) => { const img = btn.querySelector('img'); if (img) img.src = url; })
        .catch(() => { btn.innerHTML = '<span class="mi">broken_image</span>'; });
      btn.addEventListener('click', () => showPhoto(loc));
    });
    box.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', () => openEdit(locations.find((l) => l.id === b.dataset.edit))));
    box.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => remove(locations.find((l) => l.id === b.dataset.del))));
    const unlock = box.querySelector('#unlock-game');
    if (unlock) unlock.addEventListener('click', async () => {
      if (!(await confirmModal('Unlock the game and go back to DRAFT? Teams keep their logins; routes are kept until you regenerate them, and you will need to Lock again before starting.', { okLabel: 'Unlock' }))) return;
      if (await guarded(() => api.admin.transition(inUse.id, 'unlock'), 'Game unlocked - checkpoints can be changed')) load();
    });
  }

  function openAdd() {
    const freeCodes = CODES.filter((c) => !locations.some((l) => l.code === c));
    if (!freeCodes.length) return;
    let stopGps = () => {};
    let picker = null;
    const { el } = openModal('Add checkpoint', `
      ${gpsBoxHTML('Finding your location...')}
      <div class="r2-form-grid" style="margin-top:12px;">
        <label>Code<select name="code">${freeCodes.map((c) => `<option>${c}</option>`).join('')}</select></label>
        <label>Name<input name="name" required maxlength="120" placeholder="e.g. Library steps" autocomplete="off" /></label>
        <label>Latitude<input name="latitude" type="number" step="any" min="-90" max="90" required /></label>
        <label>Longitude<input name="longitude" type="number" step="any" min="-180" max="180" required /></label>
        <label>Radius (m)<input name="geofence_radius_m" type="number" min="5" max="500" value="40" /></label>
        <label class="r2-check"><input type="checkbox" name="is_selected" checked /> In the game</label>
      </div>
      ${photoPickerHTML(false)}`, {
      submitLabel: 'Add',
      onClose: () => { stopGps(); if (picker) picker.dispose(); },
      onSubmit: async (fd) => {
        const created = await guarded(() => api.admin.createCheckpoint({
          code: fd.get('code'),
          name: String(fd.get('name')).trim(),
          latitude: Number(fd.get('latitude')),
          longitude: Number(fd.get('longitude')),
          geofence_radius_m: Number(fd.get('geofence_radius_m') || 40),
          is_selected: fd.get('is_selected') === 'on',
        }));
        if (!created) return false;
        const { photo } = picker.get();
        if (photo) {
          try {
            await api.admin.setCheckpointPhoto(created.id, photo.full, photo.thumb);
          } catch (err) {
            toast(`${created.code} was added, but the photo didn't upload (${err.message}). Add it with Edit.`, { error: true, duration: 7000 });
            load();
            return true;
          }
        }
        toast(`${created.code} · ${created.name} added${photo ? ' with a photo' : ''}`, { success: true });
        load();
        return true;
      },
    });
    const form = el.querySelector('#modal-form');
    stopGps = followGps(el, form);
    picker = wirePhotoPicker(el, null);
  }

  function openEdit(loc) {
    const draft = !inUse;
    let stopGps = () => {};
    let picker = null;
    const { el } = openModal(`Edit ${loc.code}`, `
      <div class="r2-form-grid">
        <label>Name<input name="name" required maxlength="120" value="${esc(loc.name)}" autocomplete="off" /></label>
        <label>Radius (m)<input name="geofence_radius_m" type="number" min="5" max="500" value="${loc.geofence_radius_m}" /></label>
        <label>Latitude<input name="latitude" type="number" step="any" min="-90" max="90" required value="${loc.latitude}" /></label>
        <label>Longitude<input name="longitude" type="number" step="any" min="-180" max="180" required value="${loc.longitude}" /></label>
        <label class="r2-check"><input type="checkbox" name="is_selected" ${loc.is_selected ? 'checked' : ''} ${draft ? '' : 'disabled'} /> In the game</label>
      </div>
      <div data-gps-slot style="margin-top:10px;">
        <button type="button" class="btn" data-here><span class="mi">my_location</span> Use my current location</button>
      </div>
      ${photoPickerHTML(loc.has_photo)}`, {
      submitLabel: 'Save',
      onClose: () => { stopGps(); if (picker) picker.dispose(); },
      onSubmit: async (fd) => {
        const patch = {};
        const name = String(fd.get('name')).trim();
        const latitude = Number(fd.get('latitude'));
        const longitude = Number(fd.get('longitude'));
        const radius = Number(fd.get('geofence_radius_m'));
        if (name !== loc.name) patch.name = name;
        if (latitude !== loc.latitude) patch.latitude = latitude;
        if (longitude !== loc.longitude) patch.longitude = longitude;
        if (radius !== loc.geofence_radius_m) patch.geofence_radius_m = radius;
        if (draft && (fd.get('is_selected') === 'on') !== loc.is_selected) patch.is_selected = fd.get('is_selected') === 'on';
        if (Object.keys(patch).length && !(await guarded(() => api.admin.updateCheckpoint(loc.id, patch)))) return false;
        const { photo, remove: dropPhoto } = picker.get();
        try {
          if (photo) await api.admin.setCheckpointPhoto(loc.id, photo.full, photo.thumb);
          else if (dropPhoto && loc.has_photo) await api.admin.deleteCheckpointPhoto(loc.id);
        } catch (err) {
          toast(`Saved, but the photo change failed (${err.message}).`, { error: true, duration: 6000 });
          load();
          return true;
        }
        toast(`${loc.code} saved`, { success: true });
        load();
        return true;
      },
    });
    const form = el.querySelector('#modal-form');
    el.querySelector('[data-here]').addEventListener('click', () => {
      el.querySelector('[data-gps-slot]').innerHTML = gpsBoxHTML('Finding your location...');
      stopGps = followGps(el, form);
    });
    picker = wirePhotoPicker(el, loc.has_photo ? photoUrl(loc, true) : null);
  }

  async function remove(loc) {
    const ok = await confirmModal(`Delete ${loc.code} · ${loc.name} from the library? Its photo goes with it, and every draft event's routes must be regenerated.`, { okLabel: 'Delete', danger: true });
    if (ok && (await guarded(() => api.admin.deleteCheckpoint(loc.id), `${loc.code} deleted`))) load();
  }

  function showPhoto(loc) {
    const { el } = openModal(`${loc.code} · ${loc.name}`, '<div class="r2-photo-full"><div class="spinner"></div></div>', { wide: true });
    const slot = el.querySelector('.r2-photo-full');
    photoUrl(loc, false)
      .then((url) => { slot.innerHTML = `<img src="${url}" alt="Photo of ${esc(loc.code)}" />`; })
      .catch((err) => { slot.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  }

  addBtn.addEventListener('click', openAdd);
  load();
  return () => {
    photoUrls.forEach((p) => p.then((url) => URL.revokeObjectURL(url)).catch(() => {}));
    photoUrls.clear();
  };
}
