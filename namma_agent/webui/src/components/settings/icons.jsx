// Settings nav icons: Tabler, one per section, drawn in currentColor
// (Phase 9 W1 — replaces the hand-drawn path table).
import {
  IconActivity, IconAdjustmentsHorizontal, IconBell, IconBrain, IconCalendarRepeat, IconChartLine,
  IconCpu, IconEye, IconHistory, IconInfoCircle, IconMessages, IconPackage, IconPalette,
  IconPlug, IconShieldCheck, IconSparkles, IconTool, IconUserCircle, IconWorld,
} from "@tabler/icons-react";

export const TAB_ICONS = {
  Behavior: IconAdjustmentsHorizontal,
  Persona: IconUserCircle,
  Appearance: IconPalette,
  Notifications: IconBell,
  Model: IconCpu,
  Skills: IconSparkles,
  Toolsets: IconTool,
  MCP: IconPlug,
  Packs: IconPackage,
  Browser: IconWorld,
  Messaging: IconMessages,
  Memory: IconBrain,
  Security: IconShieldCheck,
  Checkpoints: IconHistory,
  Learning: IconChartLine,
  Routines: IconCalendarRepeat,
  Watchers: IconEye,
  Status: IconActivity,
  About: IconInfoCircle,
};

export function TabIcon({ name }) {
  const Icon = TAB_ICONS[name];
  return Icon ? <Icon size={16} stroke={1.7} className="shrink-0" aria-hidden="true" /> : null;
}
