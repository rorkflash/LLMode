// ---------------------------------------------------------------------------
// Vite configuration for the LLMode UI.
//
// The UI is a standalone service. During development we proxy API + WebSocket
// calls to the Python daemon so the browser sees a single origin (avoids CORS
// friction while iterating). In production the UI reads VITE_LLMODE_API to find
// the daemon directly.
// ---------------------------------------------------------------------------
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Enable React fast-refresh + JSX transform.
  plugins: [react()],
  server: {
    port: 5173, // Matches the daemon's default allowed CORS origin.
    proxy: {
      // Forward management API + inference proxy to the daemon during dev.
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true, ws: true },
      "/v1": { target: "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
});
