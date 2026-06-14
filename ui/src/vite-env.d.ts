/// <reference types="vite/client" />
// ---------------------------------------------------------------------------
// Ambient type declarations for the UI's environment variables.
// Declaring them here gives `import.meta.env.VITE_*` proper TypeScript types.
// ---------------------------------------------------------------------------

interface ImportMetaEnv {
  /** Base URL of the LLMode daemon (empty = same origin via the dev proxy). */
  readonly VITE_LLMODE_API?: string;
  /** Optional bearer token when the daemon enforces auth. */
  readonly VITE_LLMODE_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
