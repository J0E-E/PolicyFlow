import Card from "./Card.tsx";
import StampTag from "./StampTag.tsx";
import type { ScenarioEntry } from "./scenarioReference.ts";

interface ScenarioReferenceEntryProperties {
  /** Base id; every rendered element derives a unique id from it (CLAUDE.md). */
  id: string;
  /** The scenario this card renders (trigger, outcome, and its step/control marker). */
  entry: ScenarioEntry;
}

// One scenario as an Epic 8 Card (Guide §5 container) inside the reference modal.
// The body carries the labelled "Trigger" and "Expected outcome" beats; the footer
// carries the neutral Epic 8 StampTag marker naming the walkthrough STEP it becomes
// live in (or the "DEMO CONTROL" fallback for the two with no single step). The
// marker is neutral — it does not signal a status, only "live in this step" — and the
// always-present text label means the marker never reads by color alone (Guide §7).
//
// The card title is an h4 so it nests correctly under the modal's category h3, which
// sits under the dialog's h2 title (Guide §7 heading order). Split out from the panel
// per the React "small, focused components" rule.
export default function ScenarioReferenceEntry({
  id,
  entry,
}: ScenarioReferenceEntryProperties) {
  return (
    <Card
      id={id}
      title={entry.title}
      headingLevel={4}
      footer={
        <StampTag id={`${id}-marker`} status="neutral">
          {entry.marker}
        </StampTag>
      }
    >
      <p id={`${id}-trigger`} className="scenario-reference-entry-beat">
        <span className="scenario-reference-entry-beat-label">Trigger</span>
        {entry.trigger}
      </p>
      <p id={`${id}-outcome`} className="scenario-reference-entry-beat">
        <span className="scenario-reference-entry-beat-label">
          Expected outcome
        </span>
        {entry.outcome}
      </p>
    </Card>
  );
}
