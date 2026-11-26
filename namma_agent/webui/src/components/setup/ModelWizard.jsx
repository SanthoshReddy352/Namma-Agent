import { useEffect, useMemo, useState } from "react";
import { IconArrowLeft, IconCheck, IconCircleCheck, IconCloud, IconCreditCard, IconExternalLink, IconKey, IconLogin2, IconSearch, IconServer2, IconStack2, IconStar, IconWorld } from "@tabler/icons-react";
import { SecretField } from "../SetupUI.jsx";
import { PROVIDER_GROUPS, connectProvider, listModels, loadCatalog, startOAuth } from "../../providerContract.js";

// Phase 9 W1: the model wizard — first-run onboarding AND Settings → Model use
// this one component (plan: "the same component is reused in Settings → Model").
//   1 Provider  — a searchable grid, grouped (Popular / Aggregators / Cloud / Local)
//   2 Sign in   — a key field with "Get a key", or "Sign in with OpenRouter"
//   3 Model     — the provider's live model list, searchable
//   4 Test      — Connect & test (a real round trip before anything is saved)
//   5 Done
// Built on src/providerContract.js, so it already speaks W2's contract.
export const WIZARD_STEPS = ["Provider", "Sign in", "Model", "Test", "Done"];
// Icons per catalogue group (W2's names + the fallback ones); unknown groups get a generic one.
const GROUP_ICON = {
  Popular: IconStar, Aggregators: IconStack2, Gateways: IconStack2, Subscriptions: IconCreditCard,
  China: IconWorld, Cloud: IconCloud, Local: IconServer2,
};

// Hyphens, dots, underscores and spaces count as the same thing ("llama32" finds "llama-3.2").
export const looseKey = (s) => String(s || "").toLowerCase().replace(/[\s._\-/:]+/g, "");
export const looseMatch = (hay, q) => !q || looseKey(hay).includes(looseKey(q));

export default function ModelWizard({ variant = "onboarding", onDone, onCancel }) {
  const [providers, setProviders] = useState(null);
  const [groupList, setGroupList] = useState(PROVIDER_GROUPS);
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState(null);
  const [step, setStep] = useState(0);
  const [keySaved, setKeySaved] = useState(false);
  const [models, setModels] = useState({ loading: false, models: [], live: false, error: "" });
  const [mq, setMq] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [oauthMsg, setOauthMsg] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  useEffect(() => { loadCatalog().then((c) => { setProviders(c.providers); setGroupList(c.groups); }); }, []);

  const needsAuth = provider && provider.auth !== "none";
  const needsEndpoint = !!provider?.needs_base_url;
  const authed = provider && (!needsAuth || keySaved) && (!needsEndpoint || !!baseUrl.trim());
  // The provider as the server should see it: with the endpoint the user typed.
  const target = provider && { ...provider, base_url: baseUrl.trim() || provider.base_url };

  function choose(p) {
    setProvider(p); setKeySaved(!!p.key_set); setModel(""); setMq(""); setResult(null); setOauthMsg("");
    setBaseUrl(p.base_url || "");
    setStep((p.auth === "none" || p.key_set) && !p.needs_base_url ? 2 : 1);
  }

  // Load the model list once the provider can be asked.
  useEffect(() => {
    if (!provider || !authed || step < 2) return;
    let live = true;
    setModels({ loading: true, models: [], live: false, error: "" });
    listModels(target).then((r) => {
      if (!live) return;
      setModels({ loading: false, ...r });
      setModel((m) => m || r.models[0] || "");
    });
    return () => { live = false; };
  }, [provider, authed, step >= 2]); // eslint-disable-line react-hooks/exhaustive-deps

  async function signIn() {
    setOauthMsg("");
    const url = await startOAuth(provider.id);
    if (url) window.open(url, "_blank", "noopener");
    else setOauthMsg("Sign-in isn't available on this server yet. Paste a key instead.");
  }

  async function test() {
    setBusy(true); setResult(null);
    const r = await connectProvider(target, model);
    setBusy(false);
    const res = r || { ok: false, message: "No response from the server." };
    setResult(res);
    if (res.ok) setStep(4);
  }

  const groups = useMemo(() => {
    const list = (providers || []).filter((p) => looseMatch(`${p.label} ${p.id} ${p.group}`, query));
    return groupList.map((g) => ({ g, items: list.filter((p) => p.group === g) })).filter((x) => x.items.length);
  }, [providers, query, groupList]);
  const shownModels = useMemo(() => models.models.filter((m) => looseMatch(m, mq)).slice(0, 200), [models.models, mq]);

  return (
    <div className="space-y-5" data-testid="model-wizard" data-step={WIZARD_STEPS[step]}>
      <Stepper step={step} />

      {step === 0 && (
        <section aria-label="Choose a provider" className="space-y-4">
          <label className="relative block">
            <IconSearch size={15} stroke={1.8} aria-hidden="true" className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} autoFocus={variant === "onboarding"}
                   aria-label="Search providers" placeholder="Search providers"
                   className="w-full h-9 rounded-md border border-border bg-surface pl-9 pr-3 text-sm text-fg placeholder:text-fg-subtle outline-none focus:border-accent" />
          </label>
          {providers === null && <p className="text-sm text-fg-muted">Loading providers…</p>}
          {providers && groups.length === 0 && <p className="text-sm text-fg-muted">No provider matches “{query}”.</p>}
          {groups.map(({ g, items }) => {
            const GIcon = GROUP_ICON[g] || IconStack2;
            return (
              <div key={g}>
                <div className="flex items-center gap-1.5 mb-2 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">
                  <GIcon size={13} stroke={1.8} aria-hidden="true" />{g}
                </div>
                <div role="radiogroup" aria-label={`${g} providers`} className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {items.map((p) => (
                    <button key={p.id} type="button" role="radio" aria-checked={provider?.id === p.id} onClick={() => choose(p)}
                            className={`text-left rounded-lg border px-3 py-2.5 transition-colors ${provider?.id === p.id ? "border-accent ring-2 ring-accent/30 bg-surface-raised" : "border-border bg-surface hover:border-accent/50"}`}>
                      <div className="text-base font-medium text-fg truncate">{p.short}</div>
                      <div className="text-xs text-fg-muted">
                        {p.needs_base_url ? "your own endpoint" : p.auth === "none" ? "runs locally, no key" : p.key_set ? <span className="text-success">connected ✓</span> : p.oauth ? "sign in or paste a key" : "needs an API key"}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {step === 1 && provider && (
        <section aria-label="Sign in" className="space-y-4">
          <StepHead provider={provider} onBack={() => setStep(0)} />
          {(provider.oauth || provider.id === "openrouter") && (
            <div className="rounded-lg border border-border bg-surface p-4 space-y-2">
              <button type="button" onClick={signIn}
                      className="inline-flex items-center gap-2 h-9 px-3.5 rounded-md bg-accent text-accent-fg text-sm font-medium hover:opacity-90">
                <IconLogin2 size={16} stroke={1.8} aria-hidden="true" />Sign in with {provider.short}
              </button>
              <p className="text-xs text-fg-muted">Opens {provider.short} in your browser. You approve access there; no key to copy.</p>
              {oauthMsg && <p role="status" className="text-xs text-warning">{oauthMsg}</p>}
            </div>
          )}
          {needsEndpoint && (
            <label className="block rounded-lg border border-border bg-surface p-4 space-y-2">
              <span className="block text-sm font-medium text-fg">Endpoint</span>
              <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://host/v1"
                     aria-label="Endpoint URL" spellCheck={false}
                     className="w-full h-9 rounded-md border border-border bg-bg px-3 text-sm font-mono text-fg placeholder:text-fg-subtle outline-none focus:border-accent" />
              <span className="block text-xs text-fg-muted">Any OpenAI-compatible base URL (it usually ends in /v1).</span>
            </label>
          )}
          {needsAuth && <div className="rounded-lg border border-border bg-surface p-4">
            <div className="flex items-center gap-1.5 mb-2 text-sm font-medium text-fg"><IconKey size={15} stroke={1.8} aria-hidden="true" />API key</div>
            <SecretField name={provider.key_env} label={`${provider.short} API key`} url={provider.key_url}
                         isSet={keySaved} onSaved={() => { setKeySaved(true); if (!needsEndpoint || baseUrl.trim()) setStep(2); }} />
          </div>}
          {authed && (
            <button type="button" onClick={() => setStep(2)} className="h-9 px-3.5 rounded-md bg-accent text-accent-fg text-sm font-medium">Continue</button>
          )}
        </section>
      )}

      {step >= 2 && step <= 3 && provider && (
        <section aria-label="Pick a model" className="space-y-3">
          <StepHead provider={provider} onBack={() => setStep(needsAuth ? 1 : 0)} />
          <label className="relative block">
            <IconSearch size={15} stroke={1.8} aria-hidden="true" className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input value={mq} onChange={(e) => setMq(e.target.value)} aria-label="Search models"
                   placeholder={models.models.length ? `Search ${models.models.length} models` : "Type a model id"}
                   className="w-full h-9 rounded-md border border-border bg-surface pl-9 pr-3 text-sm font-mono text-fg placeholder:text-fg-subtle outline-none focus:border-accent" />
          </label>
          <div role="listbox" aria-label="Models" className="max-h-64 overflow-y-auto rounded-lg border border-border bg-surface divide-y divide-border">
            {models.loading && <p className="p-3 text-sm text-fg-muted">Asking {provider.short} for its models…</p>}
            {!models.loading && shownModels.map((m) => (
              <button key={m} type="button" role="option" aria-selected={model === m} onClick={() => { setModel(m); setStep(3); }}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm font-mono ${model === m ? "bg-accent-wash text-fg" : "text-fg-muted hover:bg-surface-sunken hover:text-fg"}`}>
                <span className="truncate flex-1">{m}</span>
                {model === m && <IconCheck size={14} stroke={2.2} className="text-accent shrink-0" aria-hidden="true" />}
              </button>
            ))}
            {!models.loading && mq && !shownModels.includes(mq) && (
              <button type="button" onClick={() => { setModel(mq.trim()); setStep(3); }}
                      className="w-full px-3 py-2 text-left text-sm text-fg-muted hover:bg-surface-sunken">
                Use “<span className="font-mono text-fg">{mq.trim()}</span>” as the model id
              </button>
            )}
          </div>
          <p className="text-xs text-fg-subtle">
            {models.error ? `${models.error}${models.models.length ? " Showing suggested models." : ""}` : models.live ? "Live from the provider." : ""}
          </p>
          <div className="flex items-center gap-3">
            <button type="button" onClick={test} disabled={busy || !model.trim()}
                    className="h-9 px-3.5 rounded-md bg-accent text-accent-fg text-sm font-medium disabled:opacity-50">
              {busy ? "Testing…" : "Connect & test"}
            </button>
            {model && <span className="text-sm text-fg-muted truncate">with <span className="font-mono text-fg">{model}</span></span>}
          </div>
          {result && !result.ok && <p role="status" className="text-sm text-danger">✗ {result.message || result.error || "That didn't work."}</p>}
        </section>
      )}

      {step === 4 && (
        <section aria-label="Done" className="rounded-lg border border-success/40 bg-surface p-5 text-center space-y-2">
          <IconCircleCheck size={36} stroke={1.6} className="mx-auto text-success" aria-hidden="true" />
          <p className="text-md font-medium text-fg">{provider?.short} is connected.</p>
          <p className="text-sm text-fg-muted">{result?.message || <>Chats now use <span className="font-mono">{model}</span>.</>}</p>
          <div className="flex justify-center gap-2 pt-1">
            {variant === "settings" && (
              <button type="button" onClick={() => { setProvider(null); setStep(0); setResult(null); }}
                      className="h-9 px-3.5 rounded-md border border-border text-sm text-fg hover:bg-surface-sunken">Add another</button>
            )}
            <button type="button" onClick={() => onDone?.(result)} className="h-9 px-3.5 rounded-md bg-accent text-accent-fg text-sm font-medium">
              {variant === "onboarding" ? "Start chatting" : "Done"}
            </button>
          </div>
        </section>
      )}

      {onCancel && step < 4 && (
        <button type="button" onClick={onCancel} className="text-sm text-fg-muted hover:underline">Cancel</button>
      )}
    </div>
  );
}

function Stepper({ step }) {
  return (
    <ol aria-label="Steps" className="flex items-center gap-1.5 text-xs">
      {WIZARD_STEPS.map((s, i) => (
        <li key={s} aria-current={i === step ? "step" : undefined} className="flex items-center gap-1.5 min-w-0">
          <span className={`grid place-items-center h-5 w-5 rounded-full text-2xs font-semibold shrink-0 ${i < step ? "bg-accent text-accent-fg" : i === step ? "ring-2 ring-accent text-accent" : "bg-surface-sunken text-fg-subtle"}`}>
            {i < step ? <IconCheck size={11} stroke={3} aria-hidden="true" /> : i + 1}
          </span>
          <span className={`truncate ${i === step ? "text-fg font-medium" : "text-fg-subtle"} max-sm:hidden`}>{s}</span>
          {i < WIZARD_STEPS.length - 1 && <span className="w-4 h-px bg-border shrink-0" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

function StepHead({ provider, onBack }) {
  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={onBack} aria-label="Back" title="Back"
              className="grid place-items-center h-7 w-7 rounded-md text-fg-muted hover:text-fg hover:bg-surface-sunken">
        <IconArrowLeft size={15} stroke={1.8} aria-hidden="true" />
      </button>
      <span className="text-base font-medium text-fg">{provider.label}</span>
      {provider.docs_url && (
        <a href={provider.docs_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-accent hover:underline">
          Docs<IconExternalLink size={12} stroke={1.8} aria-hidden="true" />
        </a>
      )}
    </div>
  );
}
