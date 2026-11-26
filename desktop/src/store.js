// A tiny JSON settings file in userData (no dependency). Writes are atomic
// (temp file + rename) so a crash mid-write never leaves a corrupt file.
"use strict";

const fs = require("fs");
const path = require("path");

class Store {
  constructor(file, defaults = {}) {
    this.file = file;
    this.defaults = defaults;
    this.data = { ...defaults };
    try {
      const raw = JSON.parse(fs.readFileSync(file, "utf8"));
      if (raw && typeof raw === "object") this.data = { ...defaults, ...raw };
    } catch { /* first run or unreadable: defaults */ }
  }

  get(key) { return this.data[key]; }

  set(key, value) {
    this.data[key] = value;
    this.save();
  }

  save() {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      const tmp = `${this.file}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2));
      fs.renameSync(tmp, this.file);
    } catch { /* best-effort: settings are a convenience */ }
  }
}

module.exports = { Store };
