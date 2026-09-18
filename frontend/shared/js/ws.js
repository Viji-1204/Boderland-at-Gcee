// Reconnecting WebSocket (Round 1's LiveChannel) with a resync hook.
// The token travels as ?token=<jwt> (browsers can't set WS headers). The
// server closes with 4001 on a bad token, and that is not retried.
// `onOpen` fires on every (re)connect: callers use it to resync with
// GET /me/state, so nothing missed while offline stays missed.

import { getWsBase, getToken } from './api.js';

const WS_AUTH_FAILURE_CODE = 4001;
const WS_FORBIDDEN_CODE = 4003;

export class LiveChannel {
  /**
   * @param {string} path     '/team' or '/admin?event_id=...'
   * @param {(data:any)=>void} onMessage
   * @param {'team'|'admin'} [tokenKind]
   * @param {{onOpen?:(reconnected:boolean)=>void, onStatus?:(status:string)=>void, onAuthError?:()=>void}} [hooks]
   */
  constructor(path, onMessage, tokenKind = 'team', hooks = {}) {
    this.path = path;
    this.onMessage = onMessage;
    this.tokenKind = tokenKind;
    this.hooks = hooks;
    this.sock = null;
    this.closedByUser = false;
    this.authFailed = false;
    this.attempt = 0;
    this.everConnected = false;
    this.keepAliveTimer = null;
    this.connect();
  }

  status(s) {
    if (this.hooks.onStatus) this.hooks.onStatus(s);
  }

  connect() {
    if (this.authFailed || this.closedByUser) return;
    const token = getToken(this.tokenKind);
    const sep = this.path.includes('?') ? '&' : '?';
    const url = `${getWsBase()}${this.path}${token ? `${sep}token=${encodeURIComponent(token)}` : ''}`;
    this.status('connecting');
    try {
      this.sock = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.sock.onopen = () => {
      const reconnected = this.everConnected;
      this.everConnected = true;
      this.attempt = 0;
      this.status('open');
      clearInterval(this.keepAliveTimer);
      this.keepAliveTimer = setInterval(() => {
        if (this.sock && this.sock.readyState === WebSocket.OPEN) this.sock.send('ping');
      }, 25000);
      if (this.hooks.onOpen) this.hooks.onOpen(reconnected);
    };

    this.sock.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch { return; } // "pong" and other non-JSON frames
      try { this.onMessage(data); } catch (err) { console.error(err); }
    };

    this.sock.onclose = (evt) => {
      clearInterval(this.keepAliveTimer);
      if (evt.code === WS_AUTH_FAILURE_CODE || evt.code === WS_FORBIDDEN_CODE) {
        this.authFailed = true;
        this.status('auth-failed');
        if (this.hooks.onAuthError) this.hooks.onAuthError(evt.code, evt.reason);
        return;
      }
      this.status('closed');
      if (!this.closedByUser) this.scheduleReconnect();
    };

    this.sock.onerror = () => {
      if (this.sock) this.sock.close();
    };
  }

  scheduleReconnect() {
    this.attempt += 1;
    const delay = Math.min(1000 * 2 ** this.attempt, 15000);
    setTimeout(() => { if (!this.closedByUser && !this.authFailed) this.connect(); }, delay);
  }

  close() {
    this.closedByUser = true;
    clearInterval(this.keepAliveTimer);
    if (this.sock) this.sock.close();
  }
}
