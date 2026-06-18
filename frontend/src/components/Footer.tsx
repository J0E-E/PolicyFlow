// The global footer chrome shown on every page. A single shared `contentinfo`
// landmark mounted as the last flex child of both layout frames (PageLayout for
// public pages + the `/app` loading skeleton; AppShell for the signed-in `/app`
// workspace), so it pins to the bottom of the sticky-footer column on every
// surface. Presentational only — no props.
//
// The two links point at the project's source and its author; both are external,
// so they open in a new tab and carry `rel="noopener noreferrer"` (Guide §7).
export default function Footer() {
  return (
    <footer id="app-footer" className="app-footer">
      <div id="app-footer-inner" className="app-footer-inner">
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
