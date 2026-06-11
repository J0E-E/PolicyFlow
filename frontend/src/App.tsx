import HealthStatus from "./HealthStatus.tsx";

// Throwaway walking-skeleton shell (Epic 4). No UI/UX Guide design work here —
// Epic 5 owns the real landing + tenant-selection pages. Every element carries
// a descriptive id per CLAUDE.md.
export default function App() {
  return (
    <main id="app-shell">
      <header id="app-header">
        <h1 id="app-title">PolicyFlow</h1>
        <p id="app-subtitle">
          Walking-skeleton shell — placeholder pages arrive in Epic 5.
        </p>
      </header>
      <section id="app-health-section">
        <h2 id="app-health-heading">Live API health</h2>
        <HealthStatus />
      </section>
    </main>
  );
}
