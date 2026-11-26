// Unit tests for the shell's pure logic (node --test; no Electron needed).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const net = require("net");

const { parseDeepLink, findDeepLink, safeRoute } = require("../src/deeplink");
const { restoreBounds } = require("../src/windowState");
const { locate, pickPort, PREFERRED_PORT } = require("../src/backend");

test("deep links map to safe in-app actions", () => {
  assert.deepEqual(parseDeepLink("namma://"), { type: "show" });
  assert.deepEqual(parseDeepLink("namma://new"), { type: "new-chat" });
  assert.deepEqual(parseDeepLink("namma://chat/new"), { type: "new-chat" });
  assert.deepEqual(parseDeepLink("namma://settings/notifications"), { type: "navigate", route: "/settings/notifications" });
  assert.deepEqual(parseDeepLink("NAMMA://projects/abc-1"), { type: "navigate", route: "/projects/abc-1" });
  assert.deepEqual(parseDeepLink("namma://memory/"), { type: "navigate", route: "/memory" });
});

test("deep links reject anything outside the allowlist", () => {
  for (const bad of ["namma://evil.com/x", "namma://settings/../../etc", "namma://projects/a/b",
    "http://settings", "namma://settings/<script>", "", null, "namma://javascript:alert(1)"]) {
    const r = parseDeepLink(bad);
    assert.ok(r === null, `${bad} → ${JSON.stringify(r)}`);
  }
});

test("finds the deep link in a second instance's argv", () => {
  assert.equal(findDeepLink(["C:\\app.exe", "--hidden", "namma://new"]), "namma://new");
  assert.equal(findDeepLink(["C:\\app.exe"]), null);
});

test("notification actions are limited to in-app routes", () => {
  assert.equal(safeRoute("/settings/notifications?x=1"), "/settings/notifications");
  assert.equal(safeRoute("/"), "/");
  assert.equal(safeRoute("https://evil.example"), null);
  assert.equal(safeRoute("/../x"), null);
  assert.equal(safeRoute(null), null);
});

test("window bounds are restored only when visible", () => {
  const primary = { x: 0, y: 0, width: 1920, height: 1040 };
  const ok = restoreBounds({ x: 100, y: 80, width: 1300, height: 900, maximized: true }, [primary], primary);
  assert.deepEqual(ok, { x: 100, y: 80, width: 1300, height: 900, maximized: true });
  // On a monitor that's gone: centred on the primary display instead.
  const gone = restoreBounds({ x: 4000, y: 100, width: 1200, height: 800 }, [primary], primary);
  assert.equal(gone.x, Math.round((1920 - 1200) / 2));
  assert.ok(gone.y >= 0);
  // First run: a sensible default, clamped to the screen.
  const small = { x: 0, y: 0, width: 1024, height: 700 };
  const first = restoreBounds(undefined, [small], small);
  assert.ok(first.width <= 1024 && first.height <= 700);
  // Never smaller than the minimum.
  const tiny = restoreBounds({ x: 10, y: 10, width: 100, height: 100 }, [primary], primary);
  assert.ok(tiny.width >= 720 && tiny.height >= 560);
});

test("locate: packaged builds use the bundled runtime", () => {
  const r = locate({ packaged: true, resourcesPath: path.join("R"), repoRoot: "X", env: {} });
  assert.equal(r.bundled, true);
  assert.equal(r.appRoot, path.join("R", "backend"));
  assert.ok(r.python.startsWith(path.join("R", "python")));
});

test("locate: dev runs find the nearest .venv walking up", () => {
  const repo = path.join(path.sep, "a", "b", "worktree");
  const venv = path.join(path.sep, "a", process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python3");
  const r = locate({ packaged: false, resourcesPath: "", repoRoot: repo, env: {}, exists: (p) => p === venv });
  assert.equal(r.python, venv);
  assert.equal(r.appRoot, repo);
  const forced = locate({ packaged: true, resourcesPath: "", repoRoot: repo, env: { NAMMA_DESKTOP_PYTHON: "py" } });
  assert.equal(forced.python, "py");
});

test("pickPort prefers the last port, then the stable one, skipping busy ports", async () => {
  // If something (a running dev app) already holds the stable port, it is the blocker.
  const blocker = net.createServer();
  const owned = await new Promise((r) => {
    blocker.once("error", () => r(false));
    blocker.listen(PREFERRED_PORT, "127.0.0.1", () => r(true));
  });
  try {
    const p = await pickPort(null);
    assert.notEqual(p, PREFERRED_PORT);
    assert.ok(p > 1024);
    const again = await pickPort(p);
    assert.equal(again, p);
  } finally {
    if (owned) await new Promise((r) => blocker.close(r));
  }
});

test("every icon main.js loads ships in resources/ and in the packaged files", () => {
  const fs = require("fs");
  const dir = path.join(__dirname, "..");
  const main = fs.readFileSync(path.join(dir, "src", "main.js"), "utf8");
  const builder = fs.readFileSync(path.join(dir, "electron-builder.yml"), "utf8");
  const names = new Set([...main.matchAll(/"((?:icon|tray)[^"]*\.(?:ico|png))"/g)].map((m) => m[1]));
  assert.ok(names.has("tray.ico"), "Windows tray uses its own high-contrast icon");
  for (const n of names) {
    assert.ok(fs.existsSync(path.join(dir, "resources", n)), `resources/${n} exists`);
    const listed = builder.includes(`resources/${n}`) || (n.startsWith("tray") && n.endsWith(".png") && builder.includes("resources/tray*.png"));
    assert.ok(listed, `resources/${n} is packaged`);
  }
});
