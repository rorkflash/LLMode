// ---------------------------------------------------------------------------
// React entry point — mounts the App into the #root element from index.html.
// ---------------------------------------------------------------------------
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// Locate the mount node injected by index.html and render the app tree.
const rootEl = document.getElementById("root")!;
createRoot(rootEl).render(
  // StrictMode surfaces potential problems during development (double-invokes
  // effects in dev only; no effect in production builds).
  <StrictMode>
    <App />
  </StrictMode>,
);
