// Shared REST client for team-app and admin-app (Round 1's client, Round 2 endpoints).
// The API is served same-origin by the backend, so the base URL is derived
// from the page's own origin - no host setting to get wrong on event day.

const DEFAULT_BASE = typeof window !== 'undefined' && window.location && window.location.origin
  ? `${window.location.origin}/api/v1`
  : '/api/v1';

export function getApiBase() {
  return DEFAULT_BASE;
}

export function getWsBase() {
  const api = getApiBase();
  const wsScheme = api.startsWith('https') ? 'wss' : 'ws';
  const host = api.replace(/^https?:\/\//, '').replace(/\/api\/v1\/?$/, '');
  return `${wsScheme}://${host}/ws`;
}

const TOKEN_KEY_TEAM = 'bl2_team_token';
const TOKEN_KEY_ADMIN = 'bl2_admin_token';

let serverTimeOffset = 0;
let preciseTimeSynced = false;

export function getServerNow() {
  return Date.now() + serverTimeOffset;
}

/** RTT-compensated clock sync, so every countdown ticks from server time. */
export async function syncServerTime() {
  try {
    const t0 = Date.now();
    const res = await fetch(`${getApiBase()}/time`, { cache: 'no-store' });
    const t1 = Date.now();
    if (res.ok) {
      const data = await res.json();
      if (data && typeof data.server_time_ms === 'number') {
        serverTimeOffset = Math.round(data.server_time_ms + (t1 - t0) / 2 - t1);
        preciseTimeSynced = true;
      }
    }
  } catch (_) { /* offline - keep the previous offset */ }
}

if (typeof window !== 'undefined') {
  syncServerTime();
  setInterval(syncServerTime, 30000);
}

export function getToken(kind) {
  return localStorage.getItem(kind === 'admin' ? TOKEN_KEY_ADMIN : TOKEN_KEY_TEAM);
}
export function setToken(kind, token) {
  localStorage.setItem(kind === 'admin' ? TOKEN_KEY_ADMIN : TOKEN_KEY_TEAM, token);
}
export function clearToken(kind) {
  localStorage.removeItem(kind === 'admin' ? TOKEN_KEY_ADMIN : TOKEN_KEY_TEAM);
}

export class ApiError extends Error {
  constructor(status, detail, body = null) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
    this.body = body || {};
  }
}

/** Unique key per user action, so a retried request never applies twice. */
export function newIdempotencyKey(prefix = 'act') {
  const rand = (crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${rand}`.slice(0, 80);
}

let unauthorizedHandler = null;
export function onUnauthorized(fn) { unauthorizedHandler = fn; }

/**
 * @param {string} path  e.g. '/me/state'
 * @param {object} opts  { method, body, kind: 'team'|'admin', auth: bool, retries }
 */
export async function apiFetch(path, opts = {}) {
  const { method = 'GET', body, kind = 'team', auth = true, retries = method === 'GET' ? 1 : 0 } = opts;
  const headers = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = getToken(kind);
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let res;
  for (let attempt = 0; ; attempt += 1) {
    try {
      res = await fetch(`${getApiBase()}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      break;
    } catch (networkErr) {
      // Mutations carry idempotency keys, so callers may safely retry them too.
      if (attempt >= retries) {
        throw new ApiError(0, 'Could not reach the server. Check your connection and try again.');
      }
      await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
    }
  }

  const dateHeader = res.headers.get('date');
  if (dateHeader && !preciseTimeSynced) {
    const serverMs = Date.parse(dateHeader);
    if (!Number.isNaN(serverMs)) serverTimeOffset = serverMs - Date.now();
  }

  if (res.status === 204) return null;
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  if (res.status === 401 && auth) {
    clearToken(kind);
    if (unauthorizedHandler) unauthorizedHandler(kind);
    throw new ApiError(401, (data && data.detail) || 'Session expired. Please log in again.', data);
  }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : res.statusText), data);
  }
  return data;
}

export async function apiUpload(path, file, fields = {}, opts = {}) {
  const { kind = 'admin', files = {} } = opts;
  const form = new FormData();
  form.append('file', file, file.name || 'file');
  for (const [k, f] of Object.entries(files)) {
    if (f) form.append(k, f, f.name || k);
  }
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== null && String(v).trim() !== '') form.append(k, String(v));
  }
  const headers = {};
  const token = getToken(kind);
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, { method: 'POST', headers, body: form });
  } catch {
    throw new ApiError(0, 'Could not reach the server.');
  }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = null; } }
  if (res.status === 401) { clearToken(kind); if (unauthorizedHandler) unauthorizedHandler(kind); }
  if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText, data);
  return data;
}

/** Fetch a file (e.g. a photo) with the auth header, as a Blob for an object URL. */
export async function apiBlob(path, { kind = 'admin' } = {}) {
  const headers = {};
  const token = getToken(kind);
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, { headers });
  } catch {
    throw new ApiError(0, 'Could not reach the server.');
  }
  if (res.status === 401) { clearToken(kind); if (unauthorizedHandler) unauthorizedHandler(kind); }
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.blob();
}

/** Fetch a file with the auth header and hand it to the browser as a download. */
export async function apiDownload(path, { method = 'GET', body, kind = 'admin', fallbackName = 'download.xlsx' } = {}) {
  const headers = {};
  const token = getToken(kind);
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError(0, 'Could not reach the server.');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { const d = JSON.parse(await res.text()); if (d && d.detail) detail = d.detail; } catch (_) {}
    throw new ApiError(res.status, detail);
  }
  let filename = fallbackName;
  const disposition = res.headers.get('content-disposition');
  const match = disposition && /filename="?([^";]+)"?/i.exec(disposition);
  if (match) filename = match[1];
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

const T = { kind: 'team' };
const A = { kind: 'admin' };
const ev = (id) => `/admin/events/${encodeURIComponent(id)}`;

export const api = {
  getServerNow,

  team: {
    login: (team_code, password) => apiFetch('/auth/team/login', { method: 'POST', body: { team_code, password }, auth: false }),
    me: () => apiFetch('/teams/me', T),
    state: () => apiFetch('/me/state', T),
    scan: (code, gps = {}) => apiFetch('/scan', { ...T, method: 'POST', body: { code, idempotency_key: newIdempotencyKey('scan'), ...gps }, retries: 1 }),
    currentPuzzle: () => apiFetch('/puzzle/current', T),
    answer: (answer, key) => apiFetch('/puzzle/answer', { ...T, method: 'POST', body: { answer, idempotency_key: key || newIdempotencyKey('ans') }, retries: 1 }),
    // A move on the open built-in puzzle: {answer} | {move} | {swaps} | {grid}
    play: (move, key) => apiFetch('/puzzle/play', { ...T, method: 'POST', body: { ...move, idempotency_key: key || newIdempotencyKey('play') }, retries: 1 }),
    radar: (lat, lng, accuracy) => {
      const q = new URLSearchParams();
      if (lat != null && lng != null) { q.set('lat', lat); q.set('lng', lng); }
      if (accuracy != null) q.set('accuracy', Math.round(accuracy));
      return apiFetch(`/radar?${q.toString()}`, T);
    },
    leaderboard: () => apiFetch('/leaderboard', T),
    results: () => apiFetch('/results/public', T),
    targets: () => apiFetch('/powers/targets', T),
    purchase: (kind, quantity = 1) => apiFetch('/powers/purchase', { ...T, method: 'POST', body: { kind, quantity, idempotency_key: newIdempotencyKey('buy') }, retries: 1 }),
    // kind: FREEZE | JAM | TRAP
    attack: (kind, target_team_id) => apiFetch('/powers/attack', { ...T, method: 'POST', body: { kind, target_team_id, idempotency_key: newIdempotencyKey('atk') }, retries: 1 }),
    // defence: SHIELD | REFLECT | null (accept the attack)
    defend: (usage_id, defence) => apiFetch('/powers/defend', { ...T, method: 'POST', body: { usage_id, defence, idempotency_key: newIdempotencyKey('def') }, retries: 1 }),
    guide: () => apiFetch('/powers/guide', { ...T, method: 'POST', body: { idempotency_key: newIdempotencyKey('guide') }, retries: 1 }),
    // Standing at the checkpoint but can't find the sticker: ask for its photo.
    photoHint: (gps = {}) => apiFetch('/me/photo-hint', { ...T, method: 'POST', body: { ...gps, idempotency_key: newIdempotencyKey('hint') }, retries: 1 }),
    photoHintImage: () => apiBlob(`/me/photo-hint/image?v=${Date.now()}`, { kind: 'team' }),
    ward: () => apiFetch('/powers/ward', { ...T, method: 'POST', body: { idempotency_key: newIdempotencyKey('ward') }, retries: 1 }),
  },

  admin: {
    login: (username, password) => apiFetch('/auth/admin/login', { method: 'POST', body: { username, password }, auth: false }),
    me: () => apiFetch('/auth/admin/me', A),

    // The app runs one game: this returns it (created on first use), with its id for the calls below.
    theEvent: () => apiFetch('/admin/event', A),
    event: (id) => apiFetch(ev(id), A),
    updateEvent: (id, body) => apiFetch(ev(id), { ...A, method: 'PATCH', body }),
    readiness: (id) => apiFetch(`${ev(id)}/readiness`, A),
    transition: (id, action) => apiFetch(`${ev(id)}/${action}`, { ...A, method: 'POST' }),
    // LIVE / PAUSED / ENDED -> CONFIGURED, discarding the run. refund: teams shop again from scratch.
    restart: (id, refund_powers = false) => apiFetch(`${ev(id)}/restart`, { ...A, method: 'POST', body: { refund_powers } }),

    dashboard: (id) => apiFetch(`${ev(id)}/dashboard`, A),
    leaderboard: (id) => apiFetch(`${ev(id)}/leaderboard`, A),
    teamAction: (id, teamId, action, body) => apiFetch(`${ev(id)}/teams/${teamId}/${action}`, { ...A, method: 'POST', body: body || {} }),
    logs: (id, log = 'game', limit = 300) => apiFetch(`${ev(id)}/logs?log=${log}&limit=${limit}`, A),
    results: (id) => apiFetch(`${ev(id)}/results`, A),
    exportResults: (id) => apiDownload(`${ev(id)}/results/export`, { fallbackName: 'round2-results.xlsx' }),

    // The checkpoint library is shared by every event (no event id).
    checkpoints: () => apiFetch('/admin/checkpoints', A),
    checkpointsInUse: () => apiFetch('/admin/checkpoints/in-use', A),
    createCheckpoint: (body) => apiFetch('/admin/checkpoints', { ...A, method: 'POST', body }),
    updateCheckpoint: (locId, body) => apiFetch(`/admin/checkpoints/${locId}`, { ...A, method: 'PATCH', body }),
    deleteCheckpoint: (locId) => apiFetch(`/admin/checkpoints/${locId}`, { ...A, method: 'DELETE' }),
    regenerateQr: (locId) => apiFetch(`/admin/checkpoints/${locId}/regenerate-qr`, { ...A, method: 'POST' }),
    setCheckpointPhoto: (locId, photo, thumb) => apiUpload(`/admin/checkpoints/${locId}/photo`, photo, {}, { files: { thumb } }),
    deleteCheckpointPhoto: (locId) => apiFetch(`/admin/checkpoints/${locId}/photo`, { ...A, method: 'DELETE' }),
    checkpointPhoto: (locId, { thumb = false, version = '' } = {}) =>
      apiBlob(`/admin/checkpoints/${locId}/photo?thumb=${thumb ? 1 : 0}&v=${encodeURIComponent(version || '')}`),
    puzzles: () => apiFetch('/admin/checkpoints/puzzles', A),
    qrCodes: () => apiFetch('/admin/checkpoints/qr-codes', A),
    powers: (id) => apiFetch(`${ev(id)}/powers`, A),
    setPowers: (id, items) => apiFetch(`${ev(id)}/powers`, { ...A, method: 'PUT', body: items }),
    routes: (id) => apiFetch(`${ev(id)}/routes`, A),
    generateRoutes: (id) => apiFetch(`${ev(id)}/routes/generate`, { ...A, method: 'POST' }),
    // face_cards: { JACK, QUEEN, KING } -> location id; omit to keep the team's current cards.
    setRoute: (id, teamId, location_ids, face_cards = null) => apiFetch(`${ev(id)}/teams/${teamId}/route`, { ...A, method: 'PUT', body: { location_ids, face_cards } }),

    teams: {
      list: (id) => apiFetch(`${ev(id)}/teams`, A),
      create: (id, body) => apiFetch(`${ev(id)}/teams`, { ...A, method: 'POST', body }),
      update: (id, teamId, body) => apiFetch(`${ev(id)}/teams/${teamId}`, { ...A, method: 'PATCH', body }),
      setPassword: (id, teamId, new_password) => apiFetch(`${ev(id)}/teams/${teamId}/password`, { ...A, method: 'PATCH', body: { new_password } }),
      remove: (id, teamId) => apiFetch(`${ev(id)}/teams/${teamId}`, { ...A, method: 'DELETE' }),
      dealSentences: (id) => apiFetch(`${ev(id)}/teams/deal-sentences`, { ...A, method: 'POST' }),
      importTemplate: () => apiDownload('/admin/teams/import/template', { fallbackName: 'team-import-template.xlsx' }),
      importPreview: (id, file, overrides = {}) => apiUpload(`${ev(id)}/teams/import/preview`, file, {
        team_name_column: overrides.team_name,
        leader_name_column: overrides.leader_name,
        leader_phone_column: overrides.leader_phone,
        leader_email_column: overrides.leader_email,
        team_code_column: overrides.team_code,
        sentence_column: overrides.sentence,
      }),
      importCommit: (id, rows) => apiFetch(`${ev(id)}/teams/import`, { ...A, method: 'POST', body: { rows } }),
      credentialsExport: (result) => apiDownload('/admin/teams/credentials-export', { method: 'POST', body: result, fallbackName: 'team-logins.xlsx' }),
    },

    admins: {
      list: () => apiFetch('/admin/admins', A),
      create: (username, password, role) => apiFetch('/admin/admins', { ...A, method: 'POST', body: { username, password, role } }),
      setPassword: (adminId, new_password) => apiFetch(`/admin/admins/${adminId}/password`, { ...A, method: 'PATCH', body: { new_password } }),
      remove: (adminId) => apiFetch(`/admin/admins/${adminId}`, { ...A, method: 'DELETE' }),
      activate: (adminId) => apiFetch(`/admin/admins/${adminId}/activate`, { ...A, method: 'POST' }),
    },
  },
};
