// Client-side validation for the public Shopper intake form. Every rule here is
// a faithful mirror of the backend's `PublicIntakeRequest` (core/app/leads/
// schemas.py) so the visitor sees the same verdict the server would — but the
// server stays authoritative (this only catches mistakes early; it never grants
// anything). Pure functions, no React: easy to unit-test and reused by the form.
//
// The honeypot (`website`) is deliberately NOT validated — a human leaves it
// empty and a bot filling it must sail through to the silent server-side drop.

/** The form's editable values — the strings the controls bind to. All start
 *  empty; `productLines` is the checkbox group's selection. `dateOfBirth` is the
 *  native date input's `YYYY-MM-DD` string (empty when untouched). */
export interface ShopperIntakeFormValues {
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  dateOfBirth: string;
  zipCode: string;
  streetAddress: string;
  preferredContactMethod: string;
  notes: string;
  productLines: string[];
}

/** The error message per field, keyed by the same names as the values. A field
 *  with no error is simply absent. */
export type ShopperIntakeFieldErrors = Partial<
  Record<keyof ShopperIntakeFormValues, string>
>;

/** The empty starting state — every text field blank, no product lines picked. */
export const emptyShopperIntakeValues: ShopperIntakeFormValues = {
  firstName: "",
  lastName: "",
  email: "",
  phone: "",
  dateOfBirth: "",
  zipCode: "",
  streetAddress: "",
  preferredContactMethod: "",
  notes: "",
  productLines: [],
};

// The backend length caps (schemas.py Field(max_length=…)). Also fed to the
// inputs' native `maxLength` so the cap is enforced as the visitor types.
export const SHOPPER_INTAKE_MAX_LENGTHS = {
  firstName: 100,
  lastName: 100,
  email: 254,
  phone: 32,
  zipCode: 10,
  streetAddress: 200,
  preferredContactMethod: 20,
  notes: 1000,
} as const;

// The backend format rules (schemas.py), mirrored exactly.
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const ZIP_PATTERN = /^\d{5}(-\d{4})?$/;
const EARLIEST_DATE_OF_BIRTH = "1900-01-01";
const MAX_PRODUCT_LINES = 10;

/** Strip everything but ASCII digits — the frontend twin of the backend's
 *  `normalize_phone`, so both agree on "the digits" of a phone number. */
function phoneDigits(value: string): string {
  return value.replace(/\D/g, "");
}

/** Today as a `YYYY-MM-DD` string in local time — the boundary the strictly-past
 *  date-of-birth rule compares against (the native date input also emits this
 *  format, so a lexical compare is exact). */
function todayIso(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Validate one field and return its error message, or `undefined` when valid.
 * Used both on blur (one field at a time) and on submit (all fields). Mirrors
 * the backend rule for each field; `streetAddress`, `notes`, and
 * `preferredContactMethod` are optional, so an empty value is valid for them.
 */
export function validateShopperIntakeField(
  field: keyof ShopperIntakeFormValues,
  values: ShopperIntakeFormValues,
): string | undefined {
  switch (field) {
    case "firstName":
      return values.firstName.trim() === ""
        ? "Enter your first name."
        : undefined;
    case "lastName":
      return values.lastName.trim() === ""
        ? "Enter your last name."
        : undefined;
    case "email":
      if (values.email.trim() === "") return "Enter your email address.";
      return EMAIL_PATTERN.test(values.email.trim())
        ? undefined
        : "Enter a valid email address, like name@example.com.";
    case "phone":
      if (values.phone.trim() === "") return "Enter your phone number.";
      {
        const digitCount = phoneDigits(values.phone).length;
        return digitCount >= 10 && digitCount <= 15
          ? undefined
          : "Enter a phone number with 10 to 15 digits.";
      }
    case "dateOfBirth":
      if (values.dateOfBirth === "") return "Enter your date of birth.";
      if (values.dateOfBirth >= todayIso())
        return "Date of birth must be in the past.";
      return values.dateOfBirth < EARLIEST_DATE_OF_BIRTH
        ? "Date of birth must be on or after 1900."
        : undefined;
    case "zipCode":
      if (values.zipCode.trim() === "") return "Enter your ZIP code.";
      return ZIP_PATTERN.test(values.zipCode.trim())
        ? undefined
        : "Enter a 5-digit ZIP code, like 33134.";
    case "productLines":
      if (values.productLines.length < 1)
        return "Choose at least one coverage interest.";
      return values.productLines.length > MAX_PRODUCT_LINES
        ? `Choose no more than ${MAX_PRODUCT_LINES} coverage interests.`
        : undefined;
    // The optionals have no presence rule; their length caps ride the inputs'
    // native maxLength, so there is nothing to flag here.
    case "streetAddress":
    case "preferredContactMethod":
    case "notes":
      return undefined;
    default:
      return undefined;
  }
}

/** The fields that carry a validation rule, in form order — the set submit
 *  walks to build the full error map and the top summary. */
export const VALIDATED_SHOPPER_INTAKE_FIELDS: (keyof ShopperIntakeFormValues)[] =
  [
    "firstName",
    "lastName",
    "dateOfBirth",
    "email",
    "phone",
    "zipCode",
    "productLines",
  ];

/**
 * Validate every rule-bearing field and return the resulting error map (empty
 * when the whole form is valid). Called on submit to decide whether to send and
 * to populate the top error summary plus the inline field errors.
 */
export function validateShopperIntakeForm(
  values: ShopperIntakeFormValues,
): ShopperIntakeFieldErrors {
  const errors: ShopperIntakeFieldErrors = {};
  for (const field of VALIDATED_SHOPPER_INTAKE_FIELDS) {
    const message = validateShopperIntakeField(field, values);
    if (message !== undefined) {
      errors[field] = message;
    }
  }
  return errors;
}
