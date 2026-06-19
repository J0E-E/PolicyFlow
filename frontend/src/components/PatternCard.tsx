import { Fragment } from "react";
import { ArrowRight } from "iconoir-react";
import Card from "./Card.tsx";
import type { ExplainerRun } from "./explainerContent.ts";

interface PatternCardProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  Derives `${id}-body`, `${id}-mono-*`, `${id}-link`. */
  id: string;
  /** The pattern's human title (the card heading). */
  title: string;
  /** The card body as runs — mechanism terms render in `--font-mono` via <code>. */
  body: ExplainerRun[];
  /** The full GitHub tree URL for this pattern's real source directory. */
  githubUrl: string;
}

// One pattern in the "How it's built" showcase index (Epic 21). Wraps the Epic 8
// Card at headingLevel 3 (the page <h1> is the hero, so cards nest a level down,
// keeping heading order — Guide §7). The body walks the "runs" model (the same one
// explainerContent / simulatedNotice use), setting mechanism terms in `--font-mono`
// via <code>. The footer carries one deep link to the pattern's real source
// directory on GitHub, opened safely in a new tab (Guide §7). Composes only — the
// copy lives in howItsBuiltContent.ts, so a later phase adds a pattern as data, not
// a new component.
export default function PatternCard({
  id,
  title,
  body,
  githubUrl,
}: PatternCardProperties) {
  return (
    <Card
      id={id}
      title={title}
      headingLevel={3}
      footer={
        <a
          id={`${id}-link`}
          className="pattern-card-link"
          href={githubUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <span id={`${id}-link-label`} className="pattern-card-link-label">
            View the code on GitHub
          </span>
          <ArrowRight
            width={14}
            height={14}
            aria-hidden="true"
            className="pattern-card-link-arrow"
          />
        </a>
      }
    >
      <p id={`${id}-body`} className="pattern-card-body">
        {body.map((run, runIndex) =>
          typeof run === "string" ? (
            <Fragment key={runIndex}>{run}</Fragment>
          ) : (
            <code
              key={runIndex}
              id={`${id}-mono-${runIndex}`}
              className="pattern-card-mono"
            >
              {run.mono}
            </code>
          ),
        )}
      </p>
    </Card>
  );
}
