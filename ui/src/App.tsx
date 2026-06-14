// ---------------------------------------------------------------------------
// App shell — top-level layout with simple tab navigation between pages.
//
// We use lightweight local-state tabs instead of a router to keep deps minimal;
// the three views (Dashboard, Catalog, Models) cover the v1 surface.
// ---------------------------------------------------------------------------
import { useState } from "react";
import { Dashboard } from "./pages/Dashboard";
import { Catalog } from "./pages/Catalog";
import { Models } from "./pages/Models";

// The set of navigable tabs and their render functions.
const TABS = {
  dashboard: { label: "Dashboard", render: () => <Dashboard /> },
  models: { label: "Models", render: () => <Models /> },
  catalog: { label: "Catalog", render: () => <Catalog /> },
} as const;

type TabKey = keyof typeof TABS;

/** Root component: renders the header/nav and the active page. */
export function App() {
  // Which tab is currently active.
  const [tab, setTab] = useState<TabKey>("dashboard");

  return (
    <div className="app">
      {/* Brand + tab bar. */}
      <header className="header">
        <div className="brand">LLMode</div>
        <nav className="nav">
          {(Object.keys(TABS) as TabKey[]).map((key) => (
            <button
              key={key}
              className={`tab ${tab === key ? "active" : ""}`}
              onClick={() => setTab(key)}
            >
              {TABS[key].label}
            </button>
          ))}
        </nav>
      </header>

      {/* Active page body. */}
      <main className="content">{TABS[tab].render()}</main>
    </div>
  );
}
