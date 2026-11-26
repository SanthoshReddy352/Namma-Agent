import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { installClickSounds } from "./sounds.js";
import "highlight.js/styles/github.css";
// Imperium's display face (OFL-1.1). Only the Latin 600 weight; the browser
// fetches it only when an Imperium heading actually uses it.
import "@fontsource/cinzel/latin-600.css";
import "./index.css";

// Hermes-style: a soft tick on every button press (Settings → Notifications).
installClickSounds();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
