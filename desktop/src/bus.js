// The main process's subscription to the backend's event bus (/ws).
//
// The backend publishes desktop_notify {title, body, action} and
// desktop_command {action, ...} on its process-wide broadcast when
// NAMMA_DESKTOP=1; every /ws client gets them. We connect like the web UI does,
// "resume" from the hello's sequence number (so replay and live events can't
// interleave), and reconnect with backoff while the backend is alive, resuming
// from the last sequence we saw so nothing is shown twice or missed.
"use strict";

const WebSocketImpl = globalThis.WebSocket || require("ws");

class Bus {
  constructor({ url, token, onEvent, isAlive, log = () => {} }) {
    this.url = `${url.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(token)}`;
    this.onEvent = onEvent;
    this.isAlive = isAlive || (() => true);
    this.log = log;
    this.boot = null;
    this.seq = null;
    this.ws = null;
    this.closed = false;
    this.delay = 500;
  }

  start() { this.closed = false; this._connect(); }

  stop() {
    this.closed = true;
    try { this.ws && this.ws.close(); } catch { /* already closed */ }
    this.ws = null;
  }

  _connect() {
    if (this.closed) return;
    let ws;
    try { ws = new WebSocketImpl(this.url); } catch (e) { this.log(`bus: ${e.message}`); return this._retry(); }
    this.ws = ws;
    ws.onopen = () => { this.delay = 500; };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(typeof ev.data === "string" ? ev.data : ev.data.toString()); } catch { return; }
      if (msg.type === "hello") {
        // Same boot → resume where we left off; a restarted backend → from now.
        const from = msg.boot === this.boot && this.seq != null ? this.seq : msg.seq;
        this.boot = msg.boot;
        ws.send(JSON.stringify({ type: "resume", from_seq: from, boot: msg.boot }));
        return;
      }
      if (msg.type === "resync_required") {
        ws.send(JSON.stringify({ type: "resume", from_seq: msg.seq, boot: msg.boot }));
        return;
      }
      if (typeof msg.seq === "number") this.seq = msg.seq;
      if (msg.type === "desktop_notify" || msg.type === "desktop_command") {
        try { this.onEvent(msg); } catch (e) { this.log(`bus handler: ${e.message}`); }
      }
    };
    ws.onclose = () => { if (this.ws === ws) this.ws = null; this._retry(); };
    ws.onerror = () => { /* onclose follows */ };
  }

  _retry() {
    if (this.closed || !this.isAlive()) return;
    setTimeout(() => this._connect(), this.delay);
    this.delay = Math.min(this.delay * 2, 8000);
  }
}

module.exports = { Bus };
