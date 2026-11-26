// The Python backend as a supervised child process.
//
//   python -m namma_agent serve --host 127.0.0.1 --port <free port>
//
// with NAMMA_DESKTOP=1 (so notifications/updates/uninstall route to this shell),
// a per-launch NAMMA_AUTH_TOKEN (so no other local program or web page can drive
// the agent), and the per-user data dir. Its output is kept in a ring buffer for
// the error page and appended to logs/backend.log.
"use strict";

const { spawn, execFile } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

const IS_WIN = process.platform === "win32";
const PREFERRED_PORT = 47821;   // stable, so the page's origin (localStorage) is too

// ── locating Python and the app ─────────────────────────────────────────────

// Where the app source and the interpreter are. Packaged: both ship inside
// resources/ (see scripts/stage.js). Dev: the repo this folder lives in, and the
// nearest .venv walking up (a git worktree borrows the main checkout's venv).
function locate({ packaged, resourcesPath, repoRoot, env = process.env, exists = fs.existsSync }) {
  if (env.NAMMA_DESKTOP_PYTHON) {
    return { python: env.NAMMA_DESKTOP_PYTHON, appRoot: env.NAMMA_DESKTOP_APP_ROOT || repoRoot, bundled: false };
  }
  if (packaged) {
    const appRoot = path.join(resourcesPath, "backend");
    const python = IS_WIN ? path.join(resourcesPath, "python", "python.exe")
      : path.join(resourcesPath, "python", "bin", "python3");
    return { python, appRoot, bundled: true };
  }
  const rel = IS_WIN ? [".venv", "Scripts", "python.exe"] : [".venv", "bin", "python3"];
  let dir = repoRoot;
  for (let i = 0; i < 6; i++) {
    const cand = path.join(dir, ...rel);
    if (exists(cand)) return { python: cand, appRoot: repoRoot, bundled: false };
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return { python: IS_WIN ? "python" : "python3", appRoot: repoRoot, bundled: false };
}

// ── ports ───────────────────────────────────────────────────────────────────

function portFree(port, host = "127.0.0.1") {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.listen(port, host, () => srv.close(() => resolve(true)));
  });
}

// The last port we used, else a stable preferred one, else any free port.
async function pickPort(last) {
  const tries = [];
  if (Number.isInteger(last) && last > 1024) tries.push(last);
  for (let p = PREFERRED_PORT; p < PREFERRED_PORT + 20; p++) if (!tries.includes(p)) tries.push(p);
  for (const p of tries) if (await portFree(p)) return p;
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => { const { port } = srv.address(); srv.close(() => resolve(port)); });
  });
}

// ── HTTP helpers ────────────────────────────────────────────────────────────

function request(url, { method = "GET", token, body, timeout = 3000 } = {}) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const req = http.request(url, {
      method, timeout,
      headers: {
        ...(token ? { "X-Namma-Token": token } : {}),
        ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}),
      },
    }, (res) => {
      let buf = "";
      res.setEncoding("utf8");
      res.on("data", (c) => { buf += c; });
      res.on("end", () => {
        let json = null;
        try { json = JSON.parse(buf); } catch { /* not JSON */ }
        resolve({ status: res.statusCode, json, text: buf });
      });
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

// ── the supervisor ──────────────────────────────────────────────────────────

class Backend {
  constructor({ python, appRoot, bundled, dataRoot, logDir, env = {}, onExit }) {
    this.python = python;
    this.appRoot = appRoot;
    this.bundled = bundled;
    this.dataRoot = dataRoot;
    this.logDir = logDir;
    this.extraEnv = env;
    this.onExit = onExit;
    this.token = crypto.randomBytes(24).toString("hex");
    this.proc = null;
    this.port = null;
    this.lines = [];
    this.exitInfo = null;
    this.stopping = false;
  }

  get url() { return `http://127.0.0.1:${this.port}`; }
  get logFile() { return path.join(this.logDir, "backend.log"); }

  _log(chunk) {
    const text = chunk.toString();
    for (const line of text.split(/\r?\n/)) if (line.trim()) this.lines.push(line);
    if (this.lines.length > 400) this.lines.splice(0, this.lines.length - 400);
    try { fs.appendFileSync(this.logFile, text); } catch { /* logs are best-effort */ }
  }

  tail(n = 80) { return this.lines.slice(-n).join("\n"); }

  _rotateLog() {
    try {
      fs.mkdirSync(this.logDir, { recursive: true });
      const st = fs.statSync(this.logFile);
      if (st.size > 5 * 1024 * 1024) fs.renameSync(this.logFile, `${this.logFile}.1`);
    } catch { /* no log yet */ }
  }

  async start(port) {
    this.port = port;
    this.exitInfo = null;
    this.stopping = false;
    this.lines = [];
    this._rotateLog();
    fs.mkdirSync(this.dataRoot, { recursive: true });
    const env = {
      ...process.env,
      NAMMA_DESKTOP: "1",
      NAMMA_AUTH_TOKEN: this.token,
      NAMMA_HOST: "127.0.0.1",
      NAMMA_PORT: String(port),
      PORT: String(port),
      NAMMA_APP_URL: this.url,
      NAMMA_DESKTOP_PARENT_PID: String(process.pid),
      // Respect an explicit data dir (scratch runs, power users); else userData/data.
      NAMMA_DATA_DIR: process.env.NAMMA_DATA_DIR || path.join(this.dataRoot, "data"),
      PYTHONPATH: [this.appRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      PYTHONUNBUFFERED: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
      ...(this.bundled ? { NAMMA_NO_REEXEC: "1", PYTHONNOUSERSITE: "1" } : {}),
      ...this.extraEnv,
    };
    this._log(`\n===== ${new Date().toISOString()} starting backend on ${this.url} (${this.python}) =====\n`);
    const args = ["-m", "namma_agent", "serve", "--host", "127.0.0.1", "--port", String(port)];
    this.proc = spawn(this.python, args, {
      cwd: this.dataRoot,   // relative paths (logs/) land in the user's data, not the install dir
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.proc.stdout.on("data", (c) => this._log(c));
    this.proc.stderr.on("data", (c) => this._log(c));
    this.proc.on("error", (err) => { this._log(`spawn failed: ${err.message}\n`); this.exitInfo = { error: err.message }; });
    this.proc.on("exit", (code, signal) => {
      this.exitInfo = this.exitInfo || { code, signal };
      this._log(`backend exited (code=${code}, signal=${signal})\n`);
      const expected = this.stopping;
      this.proc = null;
      if (this.onExit) this.onExit({ code, signal, expected });
    });
  }

  alive() { return !!this.proc && this.exitInfo == null; }

  async waitHealthy(timeoutMs = 90000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (!this.alive()) return false;
      try {
        const r = await request(`${this.url}/api/health`, { timeout: 1500 });
        if (r.status === 200) return true;
      } catch { /* not up yet */ }
      await new Promise((r) => setTimeout(r, 250));
    }
    return false;
  }

  api(pathname, opts = {}) {
    return request(`${this.url}${pathname}`, { token: this.token, ...opts });
  }

  // Graceful first (POST /api/shutdown runs the service's cleanup: comms, browser,
  // shells), then the whole process tree, so MCP servers and other grandchildren
  // never outlive the app.
  async stop(graceMs = 6000) {
    const proc = this.proc;
    if (!proc) return;
    this.stopping = true;
    const exited = new Promise((resolve) => proc.once("exit", resolve));
    try { await this.api("/api/shutdown", { method: "POST", timeout: 2000 }); } catch { /* already down */ }
    const done = await Promise.race([exited.then(() => true), new Promise((r) => setTimeout(() => r(false), graceMs))]);
    await killTree(proc.pid);
    if (!done) await Promise.race([exited, new Promise((r) => setTimeout(r, 3000))]);
  }
}

function killTree(pid) {
  return new Promise((resolve) => {
    if (!pid) return resolve();
    if (IS_WIN) {
      execFile("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true }, () => resolve());
    } else {
      try { process.kill(-pid, "SIGTERM"); } catch { /* not a group leader */ }
      try { process.kill(pid, "SIGKILL"); } catch { /* gone */ }
      resolve();
    }
  });
}

module.exports = { Backend, locate, pickPort, portFree, request, killTree, PREFERRED_PORT };
