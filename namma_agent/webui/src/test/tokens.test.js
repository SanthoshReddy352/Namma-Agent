// Phase 6 acceptance guard: components use the design tokens — no arbitrary
// font sizes (text-[13px]) and no hex colour literals. Colours belong in
// src/index.css as tokens; sizes in the tailwind fontSize scale.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");

function sourceFiles(dir) {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) {
      if (name !== "test") out.push(...sourceFiles(p));
    } else if (/\.(jsx?|tsx?)$/.test(name) && !/\.test\./.test(name)) {
      out.push(p);
    }
  }
  return out;
}

function offenders(re) {
  const hits = [];
  for (const f of sourceFiles(SRC)) {
    fs.readFileSync(f, "utf8").split("\n").forEach((line, i) => {
      // HTML entities (&#8203;) are not colours.
      const clean = line.replace(/&#x?[0-9a-f]+;/gi, "");
      if (re.test(clean)) hits.push(`${path.relative(SRC, f)}:${i + 1}: ${line.trim().slice(0, 100)}`);
    });
  }
  return hits;
}

describe("design tokens", () => {
  it("has no arbitrary font sizes in components", () => {
    expect(offenders(/\btext-\[\d+(\.\d+)?(px|rem|em)\]/)).toEqual([]);
  });

  it("has no hex colour literals in components", () => {
    expect(offenders(/(["'`(\s:]|^)#[0-9a-fA-F]{3,8}\b(?![-\w])/)).toEqual([]);
  });

  it("defines every semantic token in light and dark", () => {
    const css = fs.readFileSync(path.join(SRC, "index.css"), "utf8");
    const tokens = ["bg", "surface", "surface-raised", "fg", "fg-muted", "fg-subtle", "border",
      "accent", "accent-fg", "danger", "warning", "success", "focus"];
    const light = css.slice(css.indexOf(":root, .theme-default, .theme-slate"));
    const dark = css.slice(css.indexOf(".dark, .dark .theme-default"));
    for (const t of tokens) expect(light).toMatch(new RegExp(`--${t}:`));
    for (const t of ["bg", "surface", "fg", "border", "danger", "focus"]) expect(dark).toMatch(new RegExp(`--${t}:`));
  });

  it("honours prefers-reduced-motion and has a focus-visible ring", () => {
    const css = fs.readFileSync(path.join(SRC, "index.css"), "utf8");
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/:focus-visible\s*\{[^}]*outline: 2px solid rgb\(var\(--focus\)\)/);
  });

  it("gives every titled button an aria-label", () => {
    // Icon-only buttons carry their name in title; the accessible name must be
    // an aria-label. Text buttons with a title tooltip are listed here by line.
    const allowed = ["Test connection"];
    const hits = offenders(/<button\b[^>]*\btitle=/).filter((h) => !/aria-label=/.test(h)
      && !allowed.some((a) => h.includes(a)));
    expect(hits).toEqual([]);
  });
});
