import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// #/reset: one address that puts the demo back to its start state (stored web checks on the server,
// anything this browser remembers), then opens the first screen.
if (/^#\/?reset\b/.test(window.location.hash)) {
  try { Object.keys(localStorage).filter((k) => k.startsWith("kello")).forEach((k) => localStorage.removeItem(k)); } catch { /* private window */ }
  const home = () => { window.location.replace(window.location.pathname + "#/"); window.location.reload(); };
  fetch("/api/demo/reset", { method: "POST" }).then(home, home);
} else
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
