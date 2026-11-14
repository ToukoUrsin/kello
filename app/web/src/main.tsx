import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./design4.css";

// #/reset: one address that puts the demo back to its start state (stored web checks on the server,
// anything this browser remembers), then opens the first screen.
// #/reset/demo does the same, then puts one stored check aside (Lapland, the radiotherapy referral) and opens
// Lapland on that action, so pressing "Check on the web" shows the check changing the plan.
const DEMO = { area: "21", action: "sbrt_pathway" };
if (/^#\/?reset\b/.test(window.location.hash)) {
  const demo = /^#\/?reset\/demo\b/.test(window.location.hash);
  try { Object.keys(localStorage).filter((k) => k.startsWith("kello")).forEach((k) => localStorage.removeItem(k)); } catch { /* private window */ }
  const go = () => {
    if (demo) { try { sessionStorage.setItem("kello-focus", `card-${DEMO.action}`); } catch { /* private window */ } }
    window.location.replace(window.location.pathname + (demo ? `#/county/${DEMO.area}` : "#/"));
    window.location.reload();
  };
  fetch("/api/demo/reset" + (demo ? `?fresh=${DEMO.action}:${DEMO.area}` : ""), { method: "POST" }).then(go, go);
} else
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
