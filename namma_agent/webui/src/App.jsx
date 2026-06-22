import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Outlet, useNavigate } from "react-router-dom";
import { fetchConfig, fileChat, listProjects, renameSession, useNammaAgent } from "./api.js";
import Logo from "./components/Logo.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Settings from "./components/Settings.jsx";
import PasswordPrompt from "./components/PasswordPrompt.jsx";
import ImageViewer from "./components/ImageViewer.jsx";
import UpdateBanner from "./components/UpdateBanner.jsx";
import { installClipboardShortcuts } from "./clipboard.js";
import { setNotifyAppName } from "./notify.js";
import ChatView from "./views/ChatView.jsx";
import ProjectsView from "./views/ProjectsView.jsx";
import ProjectDetailView from "./views/ProjectDetailView.jsx";
import LearningView from "./views/LearningView.jsx";
import LearningDetailView from "./views/LearningDetailView.jsx";

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
  const [showSettings, setShowSettings] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  // Theme = a named palette (default|slate|classic|mono) × light/dark mode. Migrate
  // the old binary "namma-theme" (light|dark) → mode, defaulting the palette.
  const [themeName, setThemeName] = useState(localStorage.getItem("namma-theme-name") || "default");
  const [dark, setDark] = useState(
    (localStorage.getItem("namma-theme-mode") || localStorage.getItem("namma-theme") || "light") === "dark");
  const theme = dark ? "dark" : "light"; // kept for components reading a string mode
  const [projects, setProjects] = useState([]);
  const [confirmReq, setConfirmReq] = useState(null); // {message, confirmLabel, resolve}
  const navigate = useNavigate();

  // In-app confirm — native window.confirm() is a no-op inside the pywebview
  // desktop window, so destructive actions route through this modal instead.
  const confirmAction = (message, confirmLabel = "Delete") =>
    new Promise((resolve) => setConfirmReq({ message, confirmLabel, resolve }));
  const resolveConfirm = (ok) => { confirmReq?.resolve(ok); setConfirmReq(null); };

  const refreshProjects = () => listProjects().then((r) => r?.projects && setProjects(r.projects));
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
    localStorage.setItem("namma-theme-mode", dark ? "dark" : "light");
  }, [themeName, dark]);

  const toggleDark = () => setDark((d) => !d);

  if (shuttingDown) {
    return (
      <div className="h-full grid place-items-center bg-paper dark:bg-night text-ink dark:text-night-ink">
        <div className="text-center animate-rise">
          <Logo size={56} className="mx-auto mb-4" />
          <h1 className="font-serif text-2xl">{assistantName} has shut down.</h1>
          <p className="mt-2 text-ink-soft dark:text-night-faint">You can close this tab. See you next time.</p>
        </div>
      </div>
    );
  }

  const ctx = {
    ...namma_agent, config, assistantName, theme, themeName, dark, setThemeName, toggleDark, projects, refreshProjects, confirmAction,
    openChat: (id) => { openSession(id); navigate("/"); },
    openSettings: () => setShowSettings(true),
  };

  return (
    <div className="h-full flex bg-paper dark:bg-night text-ink dark:text-night-ink">
      <Sidebar
        sessions={sessions} projects={projects}
        onNew={() => { newChat(); navigate("/"); }}
        onOpen={(id) => { openSession(id); navigate("/"); }}
        onDelete={removeSession}
        onRename={handleRename}
        onFile={handleFile}
        onConfirm={confirmAction}
        onOpenSettings={() => setShowSettings(true)}
        collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)}
        name={assistantName}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <UpdateBanner />
        <Outlet context={ctx} />
      </div>

      {/* Tool approval is no longer a global modal — it renders inline in the chat's
          activity timeline (Hermes-style), handled in Timeline/Activity. */}

      {confirmReq && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={() => resolveConfirm(false)}>
          <div className="w-[400px] max-w-full rounded-2xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop p-5 animate-rise"
               onClick={(e) => e.stopPropagation()}>
            <h3 className="font-serif text-lg mb-1">Are you sure?</h3>
            <p className="text-ink-soft dark:text-night-faint text-sm mb-4">{confirmReq.message}</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => resolveConfirm(false)} className="px-4 py-2 rounded-lg text-ink-soft dark:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft">Cancel</button>
              <button autoFocus onClick={() => resolveConfirm(true)} className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep">{confirmReq.confirmLabel}</button>
            </div>
          </div>
        </div>
      )}

      <PasswordPrompt req={passwordReq} onSubmit={respondPassword} onCancel={() => respondPassword("")} />

      {/* Top-layer image viewer (zoom / pan / reset / close) — opened from inline images. */}
      <ImageViewer />

      {showSettings && (
        <Settings onClose={() => setShowSettings(false)} theme={theme}
                  onThemeToggle={toggleDark}
                  themeName={themeName} onThemeNameChange={setThemeName}
                  onModelsChanged={() => namma_agent.reloadConfiguredModels?.()}
                  onAssistantNameChanged={(n) => {
                    setAssistantName(n);
                    localStorage.setItem("namma-assistant-name", n);
                  }}
                  onMemoryCleared={() => { namma_agent.refreshSessions(); newChat(); }} />
      )}
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<ChatView />} />
          <Route path="projects" element={<ProjectsView />} />
          <Route path="projects/:id" element={<ProjectDetailView />} />
          <Route path="learning" element={<LearningView />} />
          <Route path="learning/:id" element={<LearningDetailView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
