import { Link } from "react-router-dom";
import PageLayout from "../components/PageLayout.tsx";
import PatternCard from "../components/PatternCard.tsx";
import ArchitectureConsole from "../components/ArchitectureConsole.tsx";
import {
  GITHUB_TREE_BASE,
  howItsBuiltMotivation,
  howItsBuiltPatterns,
} from "./howItsBuiltContent.ts";

// The public "How it's built" page (`/how-its-built`, Epic 21). The last guided
// demo surface of P1.6 and one of the two editorial surfaces the hiring audience
// reads most carefully (Guide §6.13). Sits OUTSIDE RequireSession — purely public
// content + links — in the shared public PageLayout frame (paper wordmark header +
// global Footer). Composes only; the editorial copy lives in howItsBuiltContent.ts.
//
// Four beats: a back-home link, a Besley-display hero carrying the "Why PolicyFlow"
// motivation (reusing the landing's Oxford double rule), a pattern-index grid of the
// five real P1.1–P1.5 backend patterns as GitHub deep-link cards, and the
// ink-console architecture placeholder with its real-vs-simulated legend. Content
// grows per phase — P1.7+ adds pattern/showcase entries as data.
export default function HowItsBuiltPage() {
  return (
    <PageLayout pageId="how-its-built">
      <div id="how-its-built-content" className="how-its-built-content">
        <Link
          id="how-its-built-back-link"
          className="text-link how-its-built-back-link"
          to="/"
        >
          ← Back to PolicyFlow
        </Link>

        <h1 id="how-its-built-hero-title" className="how-its-built-hero-title">
          How it's built
        </h1>
        <hr id="how-its-built-oxford-rule" className="oxford-double-rule" />
        <p id="how-its-built-motivation" className="how-its-built-motivation">
          {howItsBuiltMotivation}
        </p>

        <section
          id="how-its-built-patterns"
          className="how-its-built-patterns"
          aria-labelledby="how-its-built-patterns-heading"
        >
          <h2
            id="how-its-built-patterns-heading"
            className="how-its-built-section-heading"
          >
            The patterns on show
          </h2>
          <div
            id="how-its-built-patterns-grid"
            className="how-its-built-patterns-grid"
          >
            {howItsBuiltPatterns.map((pattern) => (
              <PatternCard
                key={pattern.key}
                id={`how-its-built-pattern-${pattern.key}`}
                title={pattern.title}
                body={pattern.body}
                githubUrl={`${GITHUB_TREE_BASE}${pattern.githubPath}`}
              />
            ))}
          </div>
        </section>

        <ArchitectureConsole id="how-its-built-architecture" />
      </div>
    </PageLayout>
  );
}
