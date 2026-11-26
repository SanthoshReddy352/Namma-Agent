// Every relative import must match the file's exact case. Windows and macOS
// resolve "./TitleBar.jsx" to "Titlebar.jsx" anyway, but Linux (the Docker image,
// CI) doesn't: one such mismatch broke the image build.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");

function files(dir) {
  return fs.readdirSync(dir).flatMap((name) => {
    const p = path.join(dir, name);
    return fs.statSync(p).isDirectory() ? files(p) : /\.(jsx?|css)$/.test(name) ? [p] : [];
  });
}

const existsExact = (p) => {
  try { return fs.readdirSync(path.dirname(p)).includes(path.basename(p)); } catch { return false; }
};

describe("imports", () => {
  it("resolve with the exact file-name case", () => {
    const bad = [];
    const re = /(?:from\s+|import\s*\(\s*|import\s+)["'](\.[^"']+)["']/g;
    for (const file of files(SRC)) {
      const src = fs.readFileSync(file, "utf8");
      for (const m of src.matchAll(re)) {
        const t = path.join(path.dirname(file), m[1]);
        const candidates = [t, `${t}.js`, `${t}.jsx`, path.join(t, "index.js"), path.join(t, "index.jsx")];
        if (!candidates.some(existsExact)) bad.push(`${path.relative(SRC, file)} -> ${m[1]}`);
      }
    }
    expect(bad).toEqual([]);
  });
});
