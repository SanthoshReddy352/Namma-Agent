// Thin wrapper over the pywebview js_api bridge (window.pywebview.api.*), with a
// browser dev-mock so `npm run dev` previews the full flow without Python.

const hasBridge = () =>
  typeof window !== "undefined" &&
  window.pywebview &&
  window.pywebview.api &&
  typeof window.pywebview.api.get_defaults === "function";

// True only under `npm run dev` (vite). Vite statically replaces import.meta.env.DEV,
// so the whole dev-mock is dead code — and tree-shaken out — in the packaged build.
const DEV = !!(import.meta && import.meta.env && import.meta.env.DEV);

// Resolves once the REAL pywebview bridge is fully injected (its methods registered).
// In the packaged app we WAIT for the bridge indefinitely (polling) and NEVER fall back
// to the mock: the mock's placeholder install path (C:\Users\you\…) would otherwise be
// shown in the Welcome field and then handed to the real installer → "access denied" on
// a path that doesn't exist. The browser mock is reserved strictly for vite dev, where
// no pywebview will ever appear.
export function ready() {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const poll = () => {
      if (hasBridge()) return resolve("bridge");
      // Only ever use the mock under vite dev (DEV), and only once it's clear there's
      // no real bridge coming (no window.pywebview after a short grace).
      if (DEV && !window.pywebview && Date.now() - t0 > 1500) {
        installDevMock();
        return resolve("mock");
      }
      setTimeout(poll, 80);
    };
    poll();
  });
}

const api = (name, ...args) => {
  if (hasBridge()) return window.pywebview.api[name](...args);
  if (DEV && window.__devApi) return window.__devApi[name](...args);
  // Packaged app, bridge not ready yet: reject (recoverable — callers retry) rather
  // than reach into an undefined mock.
  return Promise.reject(new Error("installer bridge not ready"));
};

export const Installer = {
  getDefaults: () => api("get_defaults"),
  chooseDir: () => api("choose_dir"),
  resolveDir: (d) => api("resolve_dir", d),
  startInstall: (d) => api("start_install", d),
  saveProvider: (d, p) => api("save_provider", d, p),
  saveOnboarding: (d, a) => api("save_onboarding", d, a),
  verify: (d) => api("verify", d),
  launch: (d) => api("launch", d),
  close: () => api("close"),
};

// Register the inbound event handlers the Python bridge calls via evaluate_js.
export function onEvents({ onSteps, onLog, onInstallDone, onInstallError }) {
  window.__installer = { onSteps, onLog, onInstallDone, onInstallError };
}

// ── browser dev mock (no pywebview) ────────────────────────────────────────
function installDevMock() {
  if (window.__devApi) return;
  const steps = [
    ["python", "Verifying Python 3.10+"],
    ["tools", "Checking Git & Node.js"],
    ["source", "Getting the app files"],
    ["venv", "Creating the Python environment"],
    ["deps", "Installing Python dependencies"],
    ["ui", "Building the interface"],
    ["shortcuts", "Creating shortcuts"],
  ].map(([key, label]) => ({ key, label, status: "pending" }));

  window.__devApi = {
    get_defaults: async () => ({
      version: "dev",
      os: "Windows",
      default_install_dir: "C:\\Users\\Example\\Desktop\\Namma-Agent",
      providers: [
        { id: "anthropic", label: "Anthropic (Claude)", model: "claude-opus-4-8", needs_key: true, base_url: "" },
        { id: "openai", label: "OpenAI (GPT)", model: "gpt-4o", needs_key: true, base_url: "" },
        { id: "google", label: "Google (Gemini)", model: "gemini-2.0-flash", needs_key: true, base_url: "" },
        { id: "ollama", label: "Ollama (local, no key)", model: "llama3.1", needs_key: false, base_url: "http://localhost:11434/v1" },
        { id: "openai_compat", label: "OpenAI-compatible (custom URL)", model: "", needs_key: true, base_url: "" },
      ],
      onboarding_fields: [
        { key: "name", label: "Your name" },
        { key: "date_of_birth", label: "Date of birth (optional)" },
        { key: "occupation", label: "What do you do (work / study)" },
        { key: "location", label: "Where are you based" },
        { key: "interests", label: "A few interests or hobbies" },
      ],
      steps: steps.map((s) => ({ ...s })),
    }),
    choose_dir: async () => "C:\\Apps",
    resolve_dir: async (d) => (d ? d + "\\Namma-Agent" : "C:\\Users\\Example\\Desktop\\Namma-Agent"),
    start_install: async () => {
      const local = steps.map((s) => ({ ...s }));
      const I = () => window.__installer;
      let i = 0;
      const tick = () => {
        if (i > 0) local[i - 1].status = "done";
        if (i < local.length) {
          local[i].status = "active";
          I() && I().onSteps([...local.map((s) => ({ ...s }))]);
          I() && I().onLog(`  $ running ${local[i].label} …`);
          i += 1;
          setTimeout(tick, 700);
        } else {
          I() && I().onSteps([...local.map((s) => ({ ...s }))]);
          I() && I().onInstallDone({ install_dir: "C:\\Users\\Example\\Desktop\\Namma-Agent" });
        }
      };
      tick();
    },
    save_provider: async () => ({ ok: true }),
    save_onboarding: async () => ({ ok: true }),
    verify: async () => ({ ok: true }),
    launch: async () => ({ ok: true }),
    close: async () => {},
  };
}
