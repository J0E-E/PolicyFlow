import type { ReactNode } from "react";

interface CardProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  Derives `${id}-title`, `${id}-body`, `${id}-footer`. */
  id: string;
  /** Optional card title — renders a heading and names the card for assistive
   *  tech (aria-labelledby). An untitled card is an unnamed section, so it is
   *  deliberately not exposed as a landmark. */
  title?: string;
  /** Heading level for the title (default 2). Lets later epics nest cards under
   *  deeper page headings without breaking heading order (Guide §7). */
  headingLevel?: 2 | 3 | 4;
  /** Optional footer — typically actions (Guide §5). */
  footer?: ReactNode;
  /** The card body. */
  children: ReactNode;
}

// The Guide's flat bordered "paper" container (Guide §5): --surface-2, a 1px
// --outline border, --radius-md, the resting --elevation-1 crease, --space-4
// padding, and a header (Title) + body + optional footer. Pure and
// non-interactive; styling lives in styles/card.css. Later surfaces compose it
// (branded tenant cards, the "How it's built" pattern-index cards).
export default function Card({
  id,
  title,
  headingLevel = 2,
  footer,
  children,
}: CardProperties) {
  const titleId = `${id}-title`;
  const Heading = `h${headingLevel}` as const;

  return (
    <section
      id={id}
      className="card"
      aria-labelledby={title ? titleId : undefined}
    >
      {title && (
        <Heading id={titleId} className="card-title">
          {title}
        </Heading>
      )}
      <div id={`${id}-body`} className="card-body">
        {children}
      </div>
      {footer && (
        <div id={`${id}-footer`} className="card-footer">
          {footer}
        </div>
      )}
    </section>
  );
}
