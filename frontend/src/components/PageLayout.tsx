import type { ReactNode } from "react";

interface PageLayoutProperties {
  /** Stable id prefix so each page's layout elements stay uniquely targetable. */
  pageId: string;
  /** The page body rendered inside the centered main column. */
  children: ReactNode;
}

// Shared, tenant-agnostic page frame: a paper header carrying the Besley
// wordmark above a hairline rule, wrapping a centered main column. Kept small
// and focused so each page only owns its own content (React philosophy /
// Guide §4 layout). No tenant letterhead rule yet — no tenant is selected.
export default function PageLayout({ pageId, children }: PageLayoutProperties) {
  return (
    <div id={`${pageId}-layout`} className="page-layout">
      <header id={`${pageId}-header`} className="page-header">
        <div id={`${pageId}-header-inner`} className="page-header-inner">
          <p id={`${pageId}-wordmark`} className="page-wordmark">
            PolicyFlow
          </p>
        </div>
      </header>
      <main id={`${pageId}-main`} className="page-main">
        {children}
      </main>
    </div>
  );
}
