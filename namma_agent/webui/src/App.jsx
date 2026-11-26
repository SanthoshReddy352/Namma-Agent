import { createContext, lazy, Suspense, useContext, useEffect, useMemo, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, Outlet, matchPath, useLocation, useNavigate } from "react-router-dom";
import { fetchConfig, fetchOnboarding, fileChat, getAuthToken, listProjects, renameSession, setAuthToken, useNammaAgent } from "./api.js";
import Logo from "./components/Logo.jsx";
import Sidebar from "./components/Sidebar.jsx";
import PasswordPrompt from "./components/PasswordPrompt.jsx";
import ImageViewer from "./components/ImageViewer.jsx";
import UpdateBanner from "./components/UpdateBanner.jsx";
import NotifyToasts from "./components/NotifyToasts.jsx";
import { installClipboardShortcuts } from "./clipboard.js";
import { setNotifyAppName } from "./notify.js";
import ChatView from "./views/ChatView.jsx";
import ChatBackdrop from "./components/ChatBackdrop.jsx";
import ErrorBoundary from "./components/ui/ErrorBoundary.jsx";
import { PanelTitlebar, TitlebarClusters } from "./components/shell/TitleBar.jsx";
import StatusBar from "./components/shell/StatusBar.jsx";
import RightPane from "./components/shell/RightPane.jsx";
import { CommandPalette, ConfirmDialog, Skeleton, Toaster, isDialogOpen } from "./components/ui/index.js";
import { SETTINGS_GROUPS, settingsPath, sectionSlug } from "./settingsSections.js";
import { MODES } from "./roles.js";

// Phase 6 code-splitting: Settings and every non-chat route load on demand, so
// the core bundle carries only the shell and the chat.
const Settings = lazy(() => import("./components/Settings.jsx"));
const ProviderOnboarding = lazy(() => import("./components/SetupUI.jsx").then((m) => ({ default: m.ProviderOnboarding })));
const ProjectsView = lazy(() => import("./views/ProjectsView.jsx"));
const ProjectDetailView = lazy(() => import("./views/ProjectDetailView.jsx"));
const LearningView = lazy(() => import("./views/LearningView.jsx"));
const LearningDetailView = lazy(() => import("./views/LearningDetailView.jsx"));
const MemoryView = lazy(() => import("./views/MemoryView.jsx"));

const RouteFallback = () => (
  <div className="p-8 max-w-3xl mx-auto w-full"><Skeleton lines={5} className="h-5 w-full" /></div>
);
const routed = (el) => <Suspense fallback={<RouteFallback />}>{el}</Suspense>;

// The real location's Settings state, resolved above the (possibly background)
// <Routes>: {open, section, background}. See AppRoutes.
const SettingsRouteContext = createContext({ open: false, section: null, background: null });

const PAGE_TITLES = [["/projects", "Projects"], ["/learning", "Learning Room"], ["/memory", "Memory"]];
const pageTitle = (path) => PAGE_TITLES.find(([p]) => path.startsWith(p))?.[1] || "";

// Prefer the stored mode; otherwise follow the OS (prefers-color-scheme).
function initialDark() {
  const stored = localStorage.getItem("namma-theme-mode") || localStorage.getItem("namma-theme");
  if (stored) return stored === "dark";
  return !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

// App shell: one WebSocket turn channel (useNammaAgent) shared by every route via the
// router Outlet context. The sidebar and global modals (approval / password /
// settings) live here so they persist across Chat / Projects / Learning views.
function Shell() {
  const namma_agent = useNammaAgent();
  const {
    passwordReq, respondPassword, shuttingDown,
    sessions, newChat, openSession, removeSession,
  } = namma_agent;

  const [config, setConfig] = useState(null);
  const settingsRoute = useContext(SettingsRouteContext);
  const showSettings = settingsRoute.open;
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [titleSlot, setTitleSlot] = useState(null);  // main panel titlebar slot (views portal into it)
  // Hermes layout: the right working-context pane (runs, plan). Remembered.
  const [rightPane, setRightPaneState] = useState(() => localStorage.getItem("namma-right-pane") === "open");
  const setRightPane = (open) => { setRightPaneState(open); localStorage.setItem("namma-right-pane", open ? "open" : "closed"); };
  const [collapsed, setCollapsed] = useState(false);
  // Theme = a named palette (default|slate|classic|mono) × light/dark mode. Migrate
  // the old binary "namma-theme" (light|dark) → mode, defaulting the palette.
  const [themeName, setThemeName] = useState(localStorage.getItem("namma-theme-name") || "default");
  const [dark, setDark] = useState(initialDark);
  const theme = dark ? "dark" : "light"; // kept for components reading a string mode
  const [projects, setProjects] = useState([]);
  const [confirmReq, setConfirmReq] = useState(null); // {message, confirmLabel, resolve}
  const navigate = useNavigate();
  const location = useLocation();

  // Settings is route-addressable: /settings/<section>. Opening it remembers
  // the page underneath (location.state.background) so the overlay sits on top
  // of whatever you were doing, and closing goes back there.
  const openSettings = (section) => {
    const tab = typeof section === "string" ? section : undefined;
    if (showSettings) {
      navigate(settingsPath(tab), { replace: true, state: { background: settingsRoute.background, fromApp: true } });
    } else {
      navigate(settingsPath(tab), { state: { background: location, fromApp: true } });
    }
  };
  const closeSettings = () => {
    const st = window.history.state?.usr;
    if (st?.fromApp && window.history.length > 1) navigate(-1);
    else navigate(settingsRoute.background || "/", { replace: true });
    checkOnboarding();
  };

  // In-app confirm — native window.confirm() is a no-op inside the pywebview
  // desktop window, so destructive actions route through this modal instead.
  const confirmAction = (message, confirmLabel = "Delete") =>
    new Promise((resolve) => setConfirmReq({ message, confirmLabel, resolve }));
  const resolveConfirm = (ok) => { confirmReq?.resolve(ok); setConfirmReq(null); };

  const refreshProjects = () => listProjects().then((r) => r?.projects && setProjects(r.projects));
  // Phase 5 first run: no model the app can call yet → the provider onboarding
  // screen (at least one provider is required). Re-checked when Settings closes.
  const [needsProvider, setNeedsProvider] = useState(false);
  const checkOnboarding = () => fetchOnboarding().then((o) => setNeedsProvider(o?.provider_ready === false));
  useEffect(() => { checkOnboarding(); }, []);
  useEffect(() => { refreshProjects(); }, []);
  // Guarantee copy/cut/paste app-wide even inside the pywebview desktop window,
  // where the native shortcuts are often not wired.
  useEffect(() => installClipboardShortcuts(), []);

  function handleRename(id, title) {
    renameSession(id, title).then(() => namma_agent.refreshSessions());
  }
  function handleFile(id, projectId) {
    fileChat(id, projectId).then(() => { namma_agent.refreshSessions(); refreshProjects(); });
  }

  // Seed the name from the last-known value cached in localStorage so a reload
  // shows the custom name immediately instead of flashing the default "Namma Agent".
  const [assistantName, setAssistantName] = useState(
    () => localStorage.getItem("namma-assistant-name") || "Namma Agent");
  useEffect(() => {
    fetchConfig().then((c) => {
      setConfig(c);
      // A new chat opens in the configured default mode (Settings → Behavior).
      if (c?.default_mode && !namma_agent.chatHasTurns) namma_agent.setMode(c.default_mode);
      if (c?.assistant_name) {
        setAssistantName(c.assistant_name);
        localStorage.setItem("namma-assistant-name", c.assistant_name);
      }
    });
  }, []);
  useEffect(() => { document.title = assistantName; setNotifyAppName(assistantName); }, [assistantName]);
  useEffect(() => {
    const el = document.documentElement;
    // One theme class + the dark flag (e.g. "theme-slate dark"); strip any prior theme-*.
    el.classList.forEach((c) => c.startsWith("theme-") && el.classList.remove(c));
    el.classList.add(`theme-${themeName}`);
    el.classList.toggle("dark", dark);
    localStorage.setItem("namma-theme-name", themeName);
  }, [themeName, dark]);
  // Until the user picks a mode, keep following the OS setting live.
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq?.addEventListener) return undefined;
    const on = (e) => { if (!localStorage.getItem("namma-theme-mode")) setDark(e.matches); };
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // An explicit toggle is a choice: persist it (it then overrides the OS).
  const toggleDark = () => setDark((d) => {
    localStorage.setItem("namma-theme-mode", d ? "light" : "dark");
    return !d;
  });

  // Global shortcuts: Ctrl/Cmd+K toggles the command palette; Escape stops a
  // running turn (unless a dialog is open — dialogs own Escape).
  const busyRef = useRef(false);
  busyRef.current = ["thinking", "queued"].includes(namma_agent.status);
  const stopRef = useRef(namma_agent.stop);
  stopRef.current = namma_agent.stop;
  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (e.key === "Escape" && !e.defaultPrevented && busyRef.current && !isDialogOpen()) {
        stopRef.current?.();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openModelPicker = () => {
    if (location.pathname !== "/") navigate("/");
    setTimeout(() => window.dispatchEvent(new Event("namma-open-model-picker")), 0);
  };
  const commands = useMemo(() => [
    { id: "new-chat", group: "Chat", label: "New chat", keywords: "start fresh conversation", run: () => { newChat(); navigate("/"); } },
    { id: "stop", group: "Chat", label: "Stop the running turn", hint: "Esc", keywords: "cancel abort", run: () => stopRef.current?.() },
    { id: "nav-chat", group: "Go to", label: "Chat", run: () => navigate("/") },
    { id: "nav-projects", group: "Go to", label: "Projects", run: () => navigate("/projects") },
    { id: "nav-learning", group: "Go to", label: "Learning Room", run: () => navigate("/learning") },
    { id: "nav-memory", group: "Go to", label: "Memory", run: () => navigate("/memory") },
    { id: "model", group: "Chat", label: "Choose a model…", keywords: "switch model provider brain", run: openModelPicker },
    { id: "side-panel", group: "View", label: rightPane ? "Hide side panel" : "Show side panel", keywords: "runs plan files preview right pane", run: () => setRightPane(!rightPane) },
    ...MODES.map((m) => ({ id: "mode-" + m.id, group: "Mode", label: m.label + " · " + m.role, keywords: m.description, run: () => namma_agent.setMode(m.id) })),
    { id: "theme", group: "Appearance", label: dark ? "Switch to light theme" : "Switch to dark theme", keywords: "dark light mode", run: toggleDark },
    ...SETTINGS_GROUPS.flatMap((g) => g.tabs.map((t) => ({
      id: "settings-" + sectionSlug(t), group: "Settings", label: "Settings: " + t,
      keywords: g.label + " preferences configure", run: () => openSettings(t),
    }))),
    ...(sessions || []).slice(0, 20).map((x) => ({
      id: "chat-" + x.id, group: "Recent chats", label: x.title || "Untitled chat",
      run: () => { openSession(x.id); navigate("/"); },
    })),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [dark, sessions, showSettings, settingsRoute.background, location.pathname, rightPane]);

  if (shuttingDown) {
    return (
      <div className="h-full grid place-items-center bg-bg text-fg">
        <div className="text-center animate-rise">
          <Logo size={56} className="mx-auto mb-4" />
          <h1 className="font-serif text-2xl">{assistantName} has shut down.</h1>
          <p className="mt-2 text-fg-muted">You can close this tab. See you next time.</p>
        </div>
      </div>
    );
  }

  const ctx = {
    ...namma_agent, config, assistantName, theme, themeName, dark, setThemeName, toggleDark, projects, refreshProjects, confirmAction,
    openChat: (id) => { openSession(id); navigate("/"); },
    openSettings, rightPane, titleSlot,
  };
  const onChatRoute = location.pathname === "/" || location.pathname.startsWith("/settings");
  const currentModelLabel = (namma_agent.configuredModels || []).find((m) => m.id === namma_agent.currentModel)?.label
    || config?.model || "";

  return (
    <div className="h-full flex flex-col bg-bg text-fg">
      <TitlebarClusters onToggleSidebar={() => window.dispatchEvent(new Event("namma-toggle-sidebar"))}
                        onOpenSettings={() => openSettings()}
                        rightPaneOpen={rightPane} onToggleRightPane={() => setRightPane(!rightPane)} />
      <div className="flex-1 flex min-h-0">
      <Sidebar
        sessions={sessions} projects={projects} busySessions={namma_agent.busySessions}
        onNew={() => { newChat(); navigate("/"); }}
        onOpen={(id) => { openSession(id); navigate("/"); }}
        onDelete={removeSession}
        onRename={handleRename}
        onFile={handleFile}
        onConfirm={confirmAction}
        onOpenSettings={() => openSettings()} onManagePersonas={() => openSettings("Persona")}
        collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)}
        name={assistantName}
      />

      <div className="relative isolate flex-1 flex flex-col min-w-0">
        {/* The painted background runs under the titlebar band too, so the band,
            transcript, composer and page cards all sit on it. Pages get a calmer,
            evenly veiled variant. */}
        <div className="absolute inset-0 -z-10" aria-hidden="true">
          <ChatBackdrop mode={namma_agent.mode} variant={onChatRoute ? "chat" : "page"}
                        busy={onChatRoute && ["thinking", "queued", "stopping"].includes(namma_agent.status)} />
        </div>
        {/* The main panel's header in the titlebar band. Chat views portal their
            title/breadcrumbs/actions into it; other pages show their name. */}
        <PanelTitlebar reserveRight={!rightPane} slotRef={setTitleSlot}>
          {location.pathname !== "/" && !location.pathname.startsWith("/settings") && (
            <span className="truncate text-sm font-medium text-fg">{pageTitle(location.pathname)}</span>
          )}
        </PanelTitlebar>
        <UpdateBanner />
        <ErrorBoundary name="page" resetKey={location.pathname} title="This page couldn't be shown.">
          <Outlet context={ctx} />
        </ErrorBoundary>
      </div>
      {rightPane && <RightPane runs={namma_agent.runs} todos={namma_agent.todos} messages={namma_agent.messages} onClose={() => setRightPane(false)} />}
      </div>
      <StatusBar connected={namma_agent.connected} mode={namma_agent.mode} modelLabel={currentModelLabel}
                 busy={["thinking", "queued"].includes(namma_agent.status)}
                 onOpenModelPicker={openModelPicker} onOpenPalette={() => setPaletteOpen(true)} />

      {/* In-app fallback banners for notifications the OS wouldn't display. */}
      <NotifyToasts />

      {/* Tool approval is no longer a global modal — it renders inline in the chat's
          activity timeline (Hermes-style), handled in Timeline/Activity. */}

      {confirmReq && (
        <ConfirmDialog message={confirmReq.message} confirmLabel={confirmReq.confirmLabel}
                       onResolve={resolveConfirm} />
      )}

      <Toaster />
      {paletteOpen && <CommandPalette commands={commands} onClose={() => setPaletteOpen(false)} />}

      <PasswordPrompt req={passwordReq} onSubmit={respondPassword} onCancel={() => respondPassword("")} />

      {/* Top-layer image viewer (zoom / pan / reset / close) — opened from inline images. */}
      <ImageViewer />

      {needsProvider && !showSettings && (
        <Suspense fallback={null}>
        <ProviderOnboarding assistantName={assistantName}
                            onOpenSettings={() => openSettings()}
                            onDone={() => { setNeedsProvider(false); namma_agent.reloadConfiguredModels?.(); }} />
        </Suspense>
      )}

      {showSettings && (
        <Suspense fallback={null}>
        <Settings onClose={closeSettings} theme={theme}
                  section={settingsRoute.section || "behavior"}
                  onSectionChange={(slug) => navigate("/settings/" + slug, { replace: true, state: window.history.state?.usr })}
                  onThemeToggle={toggleDark}
                  themeName={themeName} onThemeNameChange={setThemeName}
                  onModelsChanged={() => namma_agent.reloadConfiguredModels?.()}
                  onAssistantNameChanged={(n) => {
                    setAssistantName(n);
                    localStorage.setItem("namma-assistant-name", n);
                  }}
                  onMemoryCleared={() => { namma_agent.refreshSessions(); newChat(); }} />
        </Suspense>
      )}
    </div>
  );
}

// Phase 6a: self-hosted servers set an access token; any 401 from the API
// raises "namma-auth-required" (api.js) and this gate takes over the screen.
// Submitting stores the token and reloads so every fetch + the websocket
// reconnect carry it. Local no-token instances never see this.
function AuthGate() {
  const [needed, setNeeded] = useState(false);
  const [value, setValue] = useState("");
  useEffect(() => {
    const on = () => setNeeded(true);
    window.addEventListener("namma-auth-required", on);
    return () => window.removeEventListener("namma-auth-required", on);
  }, []);
  if (!needed) return null;
  const submit = (e) => {
    e.preventDefault();
    if (!value.trim()) return;
    setAuthToken(value.trim());
    location.reload();
  };
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg">
      <form onSubmit={submit} className="w-[360px] max-w-[90vw] rounded-2xl border border-border bg-white dark:bg-night-soft p-6 shadow-xl">
        <div className="text-lg font-semibold mb-1">Access token required</div>
        <p className="text-sm text-fg-subtle mb-4">
          This server is protected. Paste the access token from your deployment
          (printed by the installer, or <code>NAMMA_AUTH_TOKEN</code> in its .env).
          {getAuthToken() ? " The saved token was rejected — it may have changed." : ""}
        </p>
        <input autoFocus type="password" value={value} onChange={(e) => setValue(e.target.value)}
               placeholder="paste token"
               className="w-full rounded-lg border border-border bg-bg px-3 py-2 outline-none focus:border-brand mb-3" />
        <button type="submit" className="w-full rounded-lg bg-brand text-white py-2 font-medium hover:bg-brand-deep">
          Unlock
        </button>
      </form>
    </div>
  );
}

// Routes render against the background page while Settings is open (the
// "modal route" pattern), so /settings/<section> overlays whatever was there; a
// cold deep link to /settings/<section> shows the chat underneath.
function AppRoutes() {
  const location = useLocation();
  const m = matchPath("/settings/:section?", location.pathname);
  const background = m ? (location.state?.background || null) : null;
  const section = m?.params?.section || null;
  const settings = useMemo(() => ({ open: !!m, section, background }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [!!m, section, background]);
  return (
    <SettingsRouteContext.Provider value={settings}>
      <Routes location={background || location}>
        <Route element={<Shell />}>
          <Route index element={<ChatView />} />
          <Route path="projects" element={routed(<ProjectsView />)} />
          <Route path="projects/:id" element={routed(<ProjectDetailView />)} />
          <Route path="learning" element={routed(<LearningView />)} />
          <Route path="learning/:id" element={routed(<LearningDetailView />)} />
          <Route path="memory" element={routed(<MemoryView />)} />
          <Route path="settings/:section?" element={<ChatView />} />
        </Route>
      </Routes>
    </SettingsRouteContext.Provider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate />
      <AppRoutes />
    </BrowserRouter>
  );
}
