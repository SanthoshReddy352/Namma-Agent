#!/usr/bin/env node
// Stage what the installer bundles next to the Electron app (see electron-builder.yml):
//
//   stage/backend/namma_agent   the Python app from this checkout (tracked and new
//                               files, so uncommitted work is included), minus
//                               tests, web UI sources and anything machine-specific,
//                               plus the built web UI (webui/dist)
//   stage/python                a relocatable CPython with every app dependency:
//                               the same python-build-standalone runtime the
//                               self-contained 2.3.1 installer bundles
//                               (installers/native/build.py stage_runtime), copied,
//                               then topped up to the current requirements.txt
//
// The runtime is reused from a cache:  $NAMMA_RUNTIME_CACHE, else
// installers/native/runtime-win-x64 in this checkout or the main checkout (a git
// worktree shares it). With no cache, build.py's stage_runtime() downloads it.
//
// Usage: node scripts/stage.js [--skip-webui-build] [--skip-runtime]
"use strict";

const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const DESKTOP = path.resolve(__dirname, "..");
const REPO = path.resolve(DESKTOP, "..");
const STAGE = path.join(DESKTOP, "stage");
const IS_WIN = process.platform === "win32";
const args = new Set(process.argv.slice(2));

const log = (m) => console.log(`[stage] ${m}`);
const run = (cmd, argv, opts = {}) => execFileSync(cmd, argv, { stdio: "inherit", ...opts });
const out = (cmd, argv, opts = {}) => execFileSync(cmd, argv, { encoding: "utf8", maxBuffer: 64 << 20, ...opts });

// Never ship tests, sources the server doesn't need, runtime state or secrets.
const EXCLUDE = [
  /^namma_agent\/tests\//,
  /^namma_agent\/webui\/(?!dist\/)/,      // only the built UI ships
  /^namma_agent\/tui\/.*\.tcss$/,
  /(^|\/)__pycache__\//,
  /(^|\/)\.env$/,
  /(^|\/)config\.local\.yaml$/,
  /^data\//,
];

function stageWebui() {
  const webui = path.join(REPO, "namma_agent", "webui");
  const dist = path.join(webui, "dist", "index.html");
  if (!args.has("--skip-webui-build") || !fs.existsSync(dist)) {
    log("building the web UI");
    if (!fs.existsSync(path.join(webui, "node_modules"))) run(IS_WIN ? "npm.cmd" : "npm", ["ci"], { cwd: webui, shell: IS_WIN });
    run(IS_WIN ? "npm.cmd" : "npm", ["run", "build"], { cwd: webui, shell: IS_WIN });
  }
}

function stageBackend() {
  const dst = path.join(STAGE, "backend");
  fs.rmSync(dst, { recursive: true, force: true });
  const files = out("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "namma_agent"], { cwd: REPO })
    .split("\0").filter(Boolean)
    .filter((f) => !EXCLUDE.some((re) => re.test(f)))
    .filter((f) => fs.existsSync(path.join(REPO, f)));          // skip deleted-but-tracked
  for (const f of files) {
    const to = path.join(dst, f);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(path.join(REPO, f), to);
  }
  const dist = path.join(REPO, "namma_agent", "webui", "dist");
  fs.cpSync(dist, path.join(dst, "namma_agent", "webui", "dist"), { recursive: true });
  for (const f of ["LICENSE"]) if (fs.existsSync(path.join(REPO, f))) fs.copyFileSync(path.join(REPO, f), path.join(dst, f));
  log(`backend: ${files.length} files + webui/dist`);
}

function mainCheckout() {
  try {
    const common = out("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: REPO }).trim();
    return path.dirname(common);
  } catch { return REPO; }
}

function runtimeCache() {
  const cands = [process.env.NAMMA_RUNTIME_CACHE,
    path.join(REPO, "installers", "native", "runtime-win-x64"),
    path.join(mainCheckout(), "installers", "native", "runtime-win-x64")].filter(Boolean);
  for (const c of cands) if (fs.existsSync(path.join(c, "python.exe"))) return c;
  log("no cached runtime: building one with installers/native/build.py stage_runtime()");
  const py = IS_WIN ? "python" : "python3";
  const res = out(py, ["-c", "import sys; sys.path.insert(0, r'installers/native'); import build; print(build.stage_runtime())"], { cwd: REPO });
  return res.trim().split(/\r?\n/).pop();
}

function stageRuntime() {
  if (!IS_WIN) {
    log("non-Windows: no bundled runtime (the app uses python3 from PATH); see PROGRESS.md");
    fs.mkdirSync(path.join(STAGE, "python"), { recursive: true });
    return;
  }
  const src = runtimeCache();
  const dst = path.join(STAGE, "python");
  log(`runtime: copying ${src}`);
  fs.rmSync(dst, { recursive: true, force: true });
  // robocopy is far faster than fs.cpSync for ~40k files; exit codes < 8 are success.
  try { execFileSync("robocopy", [src, dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD", "__pycache__"], { stdio: "inherit" }); } catch (e) {
    if (typeof e.status !== "number" || e.status >= 8) throw e;
  }
  const py = path.join(dst, "python.exe");
  log("runtime: topping up dependencies to namma_agent/requirements.txt");
  run(py, ["-m", "pip", "install", "--no-cache-dir", "--no-warn-script-location", "--disable-pip-version-check",
    "-r", path.join(REPO, "namma_agent", "requirements.txt")]);
  // Smoke test: the staged interpreter can import the staged app.
  run(py, ["-I", "-c", "import sys; sys.path.insert(0, r'" + path.join(STAGE, "backend") + "'); import namma_agent.server.api, namma_agent.service; print('backend imports OK')"]);
}

fs.mkdirSync(STAGE, { recursive: true });
stageWebui();
stageBackend();
if (!args.has("--skip-runtime")) stageRuntime();
log("done");
