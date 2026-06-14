// ---------------------------------------------------------------------------
// Vite configuration for the LLMode UI.
//
// Env files (all live in ui/, not the repo root):
//   ui/.env          committed defaults (PORT, VITE_LLMODE_API, etc.)
//   ui/.env.local    your local overrides — git-ignored, never commit secrets
//
// Variables read here:
//   PORT              Port for BOTH the dev server and the preview server.
//                     No VITE_ prefix — Node-only, never embedded in the bundle.
//   VITE_LLMODE_API   Daemon base URL — used by the dev proxy AND embedded in
//                     the browser bundle for non-proxy deployments.
//   VITE_LLMODE_TOKEN Optional bearer token — embedded in the bundle.
// ---------------------------------------------------------------------------
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // loadEnv reads ui/.env (and ui/.env.local, ui/.env.[mode], etc.) at config
  // time. The empty-string prefix loads ALL variables, not just VITE_* ones,
  // so we can read PORT here even though it won't be injected into the bundle.
  const env = loadEnv(mode, process.cwd(), "");

  // Parse PORT once; apply it to both server and preview blocks below so the
  // same variable controls whichever Vite mode is running.
  const port = env.PORT ? parseInt(env.PORT, 10) : undefined;

  // Daemon URL for the dev proxy. Falls back to the default daemon address so
  // the UI works out of the box without any configuration.
  const daemonUrl = env.VITE_LLMODE_API || "http://127.0.0.1:8080";

  return {
    plugins: [react()],

    // `server` applies to `vite dev` (npm run dev).
    server: {
      port,
      proxy: {
        // Forward management API + WebSocket calls to the daemon during dev.
        "/api": { target: daemonUrl, changeOrigin: true, ws: true },
        // Forward OpenAI-compatible inference requests.
        "/v1": { target: daemonUrl, changeOrigin: true },
      },
    },

    // `preview` applies to `vite preview` (npm run preview / llmode ui --preview).
    // Without this block PORT was ignored for preview and Vite used its own
    // default (4173), bumping to 4174 if that port was already in use.
    preview: {
      port,
    },
  };
});
