// namma:// deep links → an in-app action. Pure functions (unit-tested).
//
//   namma://                      → just show the window
//   namma://new  | namma://chat/new → start a new chat
//   namma://settings/notifications → /settings/notifications
//   namma://projects/<id>, namma://learning/<id>, namma://memory, namma://projects
//
// Anything else is ignored: a link from a web page must never be able to steer
// the app somewhere unexpected, so only these routes and a strict charset pass.
"use strict";

const PROTOCOL = "namma";
const ROUTES = /^\/(?:$|projects(?:\/[\w.-]+)?$|learning(?:\/[\w.-]+)?$|memory$|settings(?:\/[a-z-]+)?$)/;

function parseDeepLink(raw) {
  if (typeof raw !== "string" || !raw.toLowerCase().startsWith(`${PROTOCOL}:`)) return null;
  if (raw.includes("..") || raw.length > 512) return null;
  let url;
  try { url = new URL(raw); } catch { return null; }
  // namma://settings/x parses with host "settings" and path "/x".
  const route = `/${[url.hostname, url.pathname.replace(/^\/+/, "")].filter(Boolean).join("/")}`
    .replace(/\/+$/, "") || "/";
  if (route.includes("..")) return null;
  if (route === "/") return { type: "show" };
  if (route === "/new" || route === "/chat/new") return { type: "new-chat" };
  if (ROUTES.test(route)) return { type: "navigate", route };
  return null;
}

// The deep link inside a process argv (Windows passes it as an argument to the
// second instance / a cold start), if any.
function findDeepLink(argv) {
  return (argv || []).find((a) => typeof a === "string" && a.toLowerCase().startsWith(`${PROTOCOL}://`)) || null;
}

// Notification actions use the same allowlist; only in-app routes.
function safeRoute(route) {
  if (typeof route !== "string" || !route.startsWith("/") || route.includes("..")) return null;
  const clean = route.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
  return clean === "/" || ROUTES.test(clean) ? clean : null;
}

module.exports = { PROTOCOL, parseDeepLink, findDeepLink, safeRoute };
