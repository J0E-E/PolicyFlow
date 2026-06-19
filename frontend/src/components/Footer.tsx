import { Link } from "react-router-dom";

// The global footer chrome shown on every page. A single shared `contentinfo`
// landmark mounted as the last flex child of both layout frames (PageLayout for
// public pages + the `/app` loading skeleton; AppShell for the signed-in `/app`
// workspace), so it pins to the bottom of the sticky-footer column on every
// surface. Presentational only — no props.
//
// Three links: an in-app react-router <Link> to the public "How it's built" page
// (same-tab SPA nav — public reach on every surface, Epic 21), then the project's
// source and its author. The latter two are external, so they open in a new tab and
// carry `rel="noopener noreferrer"` (Guide §7). Because the footer now renders a
// <Link>, it must mount inside a router (it always does — main.tsx wraps the app in
// BrowserRouter; its test wraps in MemoryRouter).
export default function Footer() {
  return (
    <footer id="app-footer" className="app-footer">
      <div id="app-footer-inner" className="app-footer-inner">
        <Link
          id="app-footer-how-its-built-link"
          className="app-footer-link"
          to="/how-its-built"
        >
          How it's built
        </Link>
        <a
          id="app-footer-repo-link"
          className="app-footer-link"
          href="https://github.com/J0E-E/PolicyFlow"
          target="_blank"
          rel="noopener noreferrer"
        >
          PolicyFlow on GitHub
        </a>
        <a
          id="app-footer-author-link"
          className="app-footer-link"
          href="https://github.com/J0E-E"
          target="_blank"
          rel="noopener noreferrer"
        >
          Joey Iglesias
        </a>
      </div>
    </footer>
  );
}
