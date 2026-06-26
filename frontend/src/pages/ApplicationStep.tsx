import { useState } from "react";
import Button from "../components/Button.tsx";
import { ApiError, patchApplication } from "../api";
import type { Application } from "../api";

// The health step's five yes/no questions (P2.3 Epic 6). The keys match the backend
// `HEALTH_QUESTION_KEYS` contract; the prompts are the workspace's display content.
const HEALTH_QUESTIONS: { key: string; prompt: string }[] = [
  { key: "tobacco_use", prompt: "Have you used tobacco products in the last 12 months?" },
  { key: "hospitalized_recently", prompt: "Have you been hospitalized in the past 2 years?" },
  {
    key: "chronic_condition",
    prompt: "Have you been diagnosed with a chronic condition (diabetes, heart disease, cancer)?",
  },
  {
    key: "prescription_medications",
    prompt: "Are you currently taking prescription medications?",
  },
  { key: "family_history", prompt: "Is there a family history of hereditary illness?" },
];

interface ApplicationStepProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The Draft application whose product step / Medicare ID is being captured. */
  application: Application;
  /** Fired with the updated application once the step is captured. */
  onCaptured: (application: Application) => void;
}

// The product-step + Medicare-ID capture form (P2.3 Epics 6 / 11): the beneficiary
// details (life lines) or the five health questions (health lines), plus the
// Tenant-1 Medicare ID, chosen by the application's `application_step` and
// `collects_medicare_id`. A focused component (Frontend Philosophy) the detail page
// renders while the application is Draft and something is uncaptured. The Medicare ID
// is sent to the audited, encrypt-on-capture endpoint. Tokens + primitives only.
export default function ApplicationStep({
  id,
  application,
  onCaptured,
}: ApplicationStepProperties) {
  const [beneficiary, setBeneficiary] = useState({
    full_name: "",
    relationship: "",
    date_of_birth: "",
  });
  const [healthAnswers, setHealthAnswers] = useState<Record<string, boolean>>(
    Object.fromEntries(HEALTH_QUESTIONS.map((question) => [question.key, false])),
  );
  const [medicareId, setMedicareId] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsBeneficiary = application.application_step === "beneficiary";
  const needsHealth = application.application_step === "health";
  const needsMedicare =
    application.collects_medicare_id && application.medicare_id_masked === null;

  const heading = needsBeneficiary
    ? "Beneficiary details"
    : needsHealth
      ? "Health questions"
      : "Medicare ID";

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const body: {
      beneficiary?: Record<string, string>;
      health_answers?: Record<string, boolean>;
      medicare_id?: string;
    } = {};
    if (needsBeneficiary) {
      body.beneficiary = beneficiary;
    }
    if (needsHealth) {
      body.health_answers = healthAnswers;
    }
    if (needsMedicare && medicareId.trim() !== "") {
      body.medicare_id = medicareId.trim();
    }
    setError(null);
    setIsSaving(true);
    patchApplication(application.id, body)
      .then((updated) => onCaptured(updated))
      .catch((caught: unknown) => {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "We couldn't save the application step. Please try again.",
        );
        setIsSaving(false);
      });
  };

  return (
    <section id={id} className="application-step" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className="application-step-heading">
        {heading}
      </h2>
      {error && (
        <p id={`${id}-error`} className="application-step-error" role="alert">
          {error}
        </p>
      )}
      <form id={`${id}-form`} className="application-step-form" onSubmit={submit}>
        {needsBeneficiary && (
          <>
            <BeneficiaryField
              id={`${id}-full-name`}
              label="Full name"
              type="text"
              value={beneficiary.full_name}
              onChange={(value) => setBeneficiary((prior) => ({ ...prior, full_name: value }))}
            />
            <BeneficiaryField
              id={`${id}-relationship`}
              label="Relationship"
              type="text"
              value={beneficiary.relationship}
              onChange={(value) =>
                setBeneficiary((prior) => ({ ...prior, relationship: value }))
              }
            />
            <BeneficiaryField
              id={`${id}-date-of-birth`}
              label="Date of birth"
              type="date"
              value={beneficiary.date_of_birth}
              onChange={(value) =>
                setBeneficiary((prior) => ({ ...prior, date_of_birth: value }))
              }
            />
          </>
        )}
        {needsHealth &&
          HEALTH_QUESTIONS.map((question) => (
            <label
              key={question.key}
              id={`${id}-${question.key}-row`}
              htmlFor={`${id}-${question.key}`}
              className="application-step-question"
            >
              <input
                id={`${id}-${question.key}`}
                type="checkbox"
                checked={healthAnswers[question.key]}
                onChange={(event) =>
                  setHealthAnswers((prior) => ({
                    ...prior,
                    [question.key]: event.target.checked,
                  }))
                }
              />
              <span id={`${id}-${question.key}-prompt`}>{question.prompt}</span>
            </label>
          ))}
        {needsMedicare && (
          <BeneficiaryField
            id={`${id}-medicare-id`}
            label="Medicare ID"
            type="text"
            value={medicareId}
            required={!needsBeneficiary && !needsHealth}
            onChange={setMedicareId}
          />
        )}
        <Button id={`${id}-submit`} type="submit" variant="filled" isPending={isSaving}>
          Save
        </Button>
      </form>
    </section>
  );
}

// One labeled input — text or date.
function BeneficiaryField({
  id,
  label,
  type,
  value,
  required,
  onChange,
}: {
  id: string;
  label: string;
  type: "text" | "date";
  value: string;
  required?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div id={`${id}-field`} className="application-step-field">
      <label id={`${id}-label`} htmlFor={id} className="application-step-label">
        {label}
      </label>
      <input
        id={id}
        type={type}
        className="application-step-input"
        value={value}
        required={required}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
