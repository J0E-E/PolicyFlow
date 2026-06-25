import { useState } from "react";
import { getHouseholds } from "../api";
import type { HouseholdSearchResult } from "../api";

// The create-new-vs-link household picker on the convert screen (P2.1 Epic 8). Two
// choices: mint a new household for the contact (the default), or link the contact
// into an existing household found by a name search. Choosing "link" reveals a search
// box backed by `GET /api/households?q=` (tenant- and session-scoped on the server);
// each match shows the household name and its members so the agent picks the right
// one. The parent owns the chosen mode + household id (so the commit can build the
// request); this component only reports the choices up and renders the search.

interface HouseholdPickerProperties {
  /** The current household mode — "new" mints one, "link" reuses an existing one. */
  mode: "new" | "link";
  /** The chosen household id when linking, or null (none picked yet). */
  selectedHouseholdId: string | null;
  /** Switch to the create-a-new-household choice. */
  onSelectNew: () => void;
  /** Switch to the link-an-existing-household choice (no household picked yet). */
  onSelectLinkMode: () => void;
  /** Pick one searched household to link into. */
  onSelectHousehold: (householdId: string) => void;
}

function memberNames(household: HouseholdSearchResult): string {
  return household.members
    .map((member) => `${member.first_name} ${member.last_name}`)
    .join(", ");
}

export default function HouseholdPicker({
  mode,
  selectedHouseholdId,
  onSelectNew,
  onSelectLinkMode,
  onSelectHousehold,
}: HouseholdPickerProperties) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HouseholdSearchResult[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  const runSearch = (nextQuery: string) => {
    setQuery(nextQuery);
    getHouseholds(nextQuery)
      .then((households) => {
        setResults(households);
        setHasSearched(true);
      })
      .catch(() => {
        setResults([]);
        setHasSearched(true);
      });
  };

  return (
    <fieldset
      id="convert-lead-household-picker"
      className="convert-lead-household-picker"
    >
      <legend
        id="convert-lead-household-picker-legend"
        className="form-field-label"
      >
        Household
      </legend>

      <label
        id="convert-lead-household-new-label"
        className="convert-lead-household-choice"
        htmlFor="convert-lead-household-new"
      >
        <input
          id="convert-lead-household-new"
          type="radio"
          name="convert-lead-household-mode"
          checked={mode === "new"}
          onChange={onSelectNew}
        />
        <span id="convert-lead-household-new-text">Create a new household</span>
      </label>

      <label
        id="convert-lead-household-link-label"
        className="convert-lead-household-choice"
        htmlFor="convert-lead-household-link"
      >
        <input
          id="convert-lead-household-link"
          type="radio"
          name="convert-lead-household-mode"
          checked={mode === "link"}
          onChange={onSelectLinkMode}
        />
        <span id="convert-lead-household-link-text">
          Link to an existing household
        </span>
      </label>

      {mode === "link" && (
        <div
          id="convert-lead-household-search-area"
          className="convert-lead-household-search-area"
        >
          <input
            id="convert-lead-household-search"
            className="convert-lead-household-search"
            type="search"
            value={query}
            placeholder="Search households by name"
            aria-label="Search households by name"
            onChange={(event) => runSearch(event.target.value)}
          />
          {results.length > 0 && (
            <ul
              id="convert-lead-household-results"
              className="convert-lead-household-results"
            >
              {results.map((household) => {
                const optionId = `convert-lead-household-option-${household.id}`;
                return (
                  <li
                    id={`${optionId}-item`}
                    key={household.id}
                    className="convert-lead-household-result"
                  >
                    <label id={`${optionId}-label`} htmlFor={optionId}>
                      <input
                        id={optionId}
                        type="radio"
                        name="convert-lead-household-choice"
                        checked={selectedHouseholdId === household.id}
                        onChange={() => onSelectHousehold(household.id)}
                      />
                      <span id={`${optionId}-name`}>{household.name}</span>
                      {household.members.length > 0 && (
                        <span
                          id={`${optionId}-members`}
                          className="convert-lead-household-result-members"
                        >
                          {memberNames(household)}
                        </span>
                      )}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {hasSearched && results.length === 0 && (
            <p
              id="convert-lead-household-empty"
              className="convert-lead-household-empty"
              role="status"
            >
              No households match.
            </p>
          )}
        </div>
      )}
    </fieldset>
  );
}
