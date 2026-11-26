import { IconCheck } from "@tabler/icons-react";
// Settings → AppearanceTab (split out of Settings.jsx, Phase 9 W1).


// The five named palettes (must mirror the theme blocks in src/index.css). Each
// swatch renders inside its own `theme-<id>` scope, so it reads that theme's
// real tokens (accent, background, text) instead of copied hex values.
export const THEMES = [
  { id: "default", label: "Default" },
  { id: "slate", label: "Slate" },
  { id: "classic", label: "Classic" },
  { id: "mono", label: "Mono" },
  { id: "imperium", label: "Imperium" },
];
export const SWATCH = ["bg-brand", "bg-paper", "bg-ink"];

export function ThemePicker({ themeName, onThemeNameChange }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5">
      {THEMES.map((t) => {
        const active = themeName === t.id;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onThemeNameChange(t.id)}
            className={
              "rounded-xl border p-2.5 text-left transition " +
              (active
                ? "border-brand ring-2 ring-brand/30"
                : "border-border hover:border-brand/50")
            }
          >
            <div className={`theme-${t.id} flex gap-1`}>
              {SWATCH.map((c) => (
                <span key={c} className={`h-6 flex-1 rounded border border-border ${c}`} />
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-sm font-medium text-fg">{t.label}</span>
              {active && (
                <IconCheck size={14} className="text-brand" aria-hidden="true" />
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// Settings → Appearance: palette, light/dark, log level.
export function AppearanceTab({ form, theme, onThemeToggle, themeName, onThemeNameChange }) {
  const { data, cur, setC, env, setEnv, commitEnv } = form;
  return (
    <>
      <Section title="Theme" hint="Pick a palette — applies instantly across the whole app.">
        <ThemePicker themeName={themeName} onThemeNameChange={onThemeNameChange} />
      </Section>
      <Section title="Appearance & system">
        <Toggle label="Dark theme" checked={theme === "dark"} onChange={onThemeToggle} />
        <Field label="Log level"><Select value={cur("logging.level", "info")} onChange={(v) => setC("logging.level", v)} options={["debug", "info", "warning", "error"]} /></Field>
      </Section>
    </>
  );
}
