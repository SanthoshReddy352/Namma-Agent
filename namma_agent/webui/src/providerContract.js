// Phase 9 W1 ↔ W2: the provider contract the onboarding wizard and Settings →
// Model are built on (plan/2026-11-25_23-20-00_plan.md, "Shared contract").
//
//   GET  /api/providers                  → {providers: [{id, label, group, auth, key_env,
//                                            key_url, base_url, needs_base_url, key_set,
//                                            connected, docs_url}]}
//   POST /api/providers/{id}/oauth/start → {authorize_url}
//   GET/POST /api/active_model           → {model_id}
//
// W2 implements it. Until W2 lands, today's server answers a narrower shape
// (`type`, `needs_key`, no groups, no OAuth, no active_model), so every call
// here normalises the reply and falls back to today's behaviour. When W2
// merges, nothing in the UI changes.
import { fetchConfiguredModels, listProviderModels, onboardProvider, saveConfiguredModels } from "./api.js";

const LOCAL = new Set(["ollama", "lmstudio"]);
const AGGREGATORS = new Set(["openrouter", "together", "opencode"]);
export const PROVIDER_GROUPS = ["Popular", "Aggregators", "Cloud", "Local"];
const POPULAR = ["openai", "anthropic", "google", "openrouter"];

export function normaliseProvider(p) {
  const id = p.id || p.type;
  const auth = p.auth || (p.needs_key === false ? "none" : "api_key");
  const group = p.group || (POPULAR.includes(id) ? "Popular" : LOCAL.has(id) ? "Local"
    : AGGREGATORS.has(id) ? "Aggregators" : "Cloud");
  return {
    id, type: p.type || id,
    label: p.label || id,
    short: String(p.label || id).split(" (")[0],
    group, auth,
    key_env: p.key_env || "", key_url: p.key_url || "", key_prefix: p.key_prefix || "",
    base_url: p.base_url || "", needs_base_url: !!p.needs_base_url,
    key_set: !!p.key_set,
    connected: p.connected ?? (auth === "none" || !!p.key_set),
    docs_url: p.docs_url || "",
    // OAuth: W2 marks it with auth "oauth" (or lists it in `auths`); OpenRouter's
    // PKCE sign-in is the one the plan names.
    oauth: auth === "oauth" || (Array.isArray(p.auths) && p.auths.includes("oauth")),
  };
}

async function json(url, opts) {
  try {
    const r = await fetch(url, opts);
    const type = r.headers.get("content-type") || "";
    if (!r.ok || !type.includes("json")) return null;          // missing endpoint → SPA HTML
    return await r.json();
  } catch { return null; }
}

export async function loadProviders() {
  const r = await json("/api/providers");
  return (r?.providers || []).map(normaliseProvider);
}

// OpenRouter PKCE (W2). Returns the URL to open, or null when the server can't.
export async function startOAuth(id) {
  const r = await json(`/api/providers/${encodeURIComponent(id)}/oauth/start`, { method: "POST" });
  return r?.authorize_url || null;
}

export async function listModels(provider) {
  const r = await listProviderModels(provider.type, provider.base_url || "");
  return { models: r?.models || [], live: r?.source === "live", error: r?.source === "live" ? "" : (r?.error || "") };
}

export const connectProvider = (provider, model) =>
  onboardProvider(provider.type, String(model || "").trim(), "", provider.base_url || "");

// The default model. W2: explicit `active_model`. Today: the first entry of
// `models:` is the default, so "make default" moves it to the top.
export async function getActiveModel() {
  const r = await json("/api/active_model");
  if (r && "model_id" in r) return r.model_id || "";
  const m = await fetchConfiguredModels();
  return m?.models?.[0]?.id || "";
}

export async function setActiveModel(modelId) {
  const r = await json("/api/active_model", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: modelId }),
  });
  if (r && (r.ok || r.model_id === modelId)) return { ok: true };
  const cur = (await fetchConfiguredModels())?.models || [];
  const hit = cur.find((m) => m.id === modelId);
  if (!hit) return { ok: false, error: "That model isn't configured." };
  const res = await saveConfiguredModels([hit, ...cur.filter((m) => m.id !== modelId)]);
  return res && res.ok === false ? { ok: false, error: res.error || "Couldn't save." } : { ok: true };
}
