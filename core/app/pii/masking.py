"""Pure render-layer masking + the derived age band (no DB, no tenant logic).

Every function here takes a plaintext value and returns its safe display form
with no database, no tenant logic, and no global state, so each one is trivially
testable. This is the **render half** of the PII layer: the service seam
(`pii/service.py`) decrypts a stored value, and these functions turn that
plaintext into the masked string the API returns by default. The masked forms
are taken **verbatim from TDD §5**:

| Function | Output | Rule |
|---|---|---|
| `mask_email` | `j***@e***.com` | first char of local + first char of domain + `.` + TLD |
| `mask_phone` | `***-***-1234` | last 4 digits |
| `mask_dob` | `****-**-**` | fully masked (constant; `age_band` shown instead) |
| `mask_medicare_id` | `***-**-1234` | last 4 digits |
| `mask_generic` | `***` | fixed fully-masked token |

Two conventions were confirmed at the gate:

- **`mask_generic` returns the fixed token `***`** — fully masked, leaking
  neither the content nor the length of the value, so it is the safe fallback for
  an unknown field or a value too short/malformed to mask field-specifically.
- **`age_band_for` measures completed years lived, lower-bound inclusive** — on
  the 65th birthday you are 65, so that day lands in `65+` (the Medicare
  eligibility signal P2 keys off). Same convention at every cut point.

Every masker degrades safely: a value too short or malformed to mask
field-specifically falls back to `mask_generic` rather than crash or leak.
"""

from datetime import date

# The fixed fully-masked token: leaks neither content nor length. It is both the
# `mask_generic` output and the safe fallback every other masker degrades to.
GENERIC_MASK_TOKEN = "***"

# Date of birth is never shown even masked-with-detail — the `age_band` is shown
# in its place — so this masker returns one constant fully-masked template.
DATE_OF_BIRTH_MASK = "****-**-**"

# Last-4 templates: everything before the final group is masked, the last four
# digits of the value fill the trailing `NNNN`.
PHONE_MASK_TEMPLATE = "***-***-{last_four}"
MEDICARE_ID_MASK_TEMPLATE = "***-**-{last_four}"

# The number of trailing digits a last-4 masker reveals.
REVEALED_DIGIT_COUNT = 4

# The five plaintext eligibility bands, lower-bound inclusive. The lower bound of
# each band (other than the open-ended first/last) is the cut point.
AGE_BAND_UNDER_18 = "<18"
AGE_BAND_18_TO_34 = "18-34"
AGE_BAND_35_TO_49 = "35-49"
AGE_BAND_50_TO_64 = "50-64"
AGE_BAND_65_AND_OVER = "65+"

# The four inclusive cut points, paired with the band an age at-or-above that cut
# (but below the next) falls into. Ordered high-to-low so the first match wins.
_AGE_BAND_CUT_POINTS = (
    (65, AGE_BAND_65_AND_OVER),
    (50, AGE_BAND_50_TO_64),
    (35, AGE_BAND_35_TO_49),
    (18, AGE_BAND_18_TO_34),
)


def _ascii_digits_only(value: str) -> str:
    """Return just the ASCII digits of a value, dropping all other characters.

    Punctuation, spaces, and a leading `+` are all discarded, so the same number
    written in different styles yields the same digit run to mask.
    """
    return "".join(
        character
        for character in value
        if character.isascii() and character.isdigit()
    )


def _mask_with_last_four(value: str, template: str) -> str:
    """Fill a last-4 template with the value's final four digits.

    Extracts the ASCII digits and, only if there are at least four, formats them
    into the template. A value with fewer than four digits degrades safely to the
    fully-masked generic token rather than revealing a short tail.
    """
    digits = _ascii_digits_only(value)
    if len(digits) < REVEALED_DIGIT_COUNT:
        return mask_generic()
    last_four = digits[-REVEALED_DIGIT_COUNT:]
    return template.format(last_four=last_four)


def mask_generic() -> str:
    """Return the fixed fully-masked token `***`.

    Leaks neither the content nor the length of the underlying value, so it is
    the safe default for an unknown field and the fallback every other masker
    degrades to on a too-short or malformed value.
    """
    return GENERIC_MASK_TOKEN


def mask_dob(value: str) -> str:
    """Return the constant fully-masked date `****-**-**`.

    Date of birth is never shown even partially — the plaintext `age_band` is
    shown in its place — so this always returns the same constant regardless of
    the input. The argument is accepted only to keep one masker shape across all
    fields.
    """
    return DATE_OF_BIRTH_MASK


def mask_phone(value: str) -> str:
    """Mask a phone number to its last four digits: `***-***-1234`.

    Non-digit characters (spaces, dashes, parentheses, a leading `+`) are ignored
    when finding the last four. A value with fewer than four digits degrades to
    the generic token.
    """
    return _mask_with_last_four(value, PHONE_MASK_TEMPLATE)


def mask_medicare_id(value: str) -> str:
    """Mask a Medicare id to its last four digits: `***-**-1234`.

    Same last-4 rule as `mask_phone` with the Medicare template. Note this masker
    only shapes the display string — the mock Medicare id is never revealable at
    all, which the reveal endpoint enforces separately (TDD Decision #10).
    """
    return _mask_with_last_four(value, MEDICARE_ID_MASK_TEMPLATE)


def mask_email(value: str) -> str:
    """Mask an email to `j***@e***.com`: first local char, first domain char, TLD.

    Splits on the single `@`, keeps the first character of the local part and the
    first character of the domain name, and appends the top-level domain (the
    final dot-segment of the domain). A subdomain like `a.b.example.com` keeps its
    first char (`a`) and TLD (`com`). Anything malformed — no `@`, an empty local
    or domain part, or a domain with no dot — falls back to the generic token
    rather than crash or leak.
    """
    if value.count("@") != 1:
        return mask_generic()
    local_part, domain_part = value.split("@")
    if local_part == "" or "." not in domain_part:
        return mask_generic()
    top_level_domain = domain_part.rsplit(".", 1)[-1]
    domain_name = domain_part.split(".", 1)[0]
    if domain_name == "" or top_level_domain == "":
        return mask_generic()
    return f"{local_part[0]}***@{domain_name[0]}***.{top_level_domain}"


def _completed_years(date_of_birth: date, as_of: date) -> int:
    """Return the whole years lived from `date_of_birth` up to `as_of`.

    Counts completed years: the difference in calendar years minus one if this
    year's birthday has not yet happened on `as_of`. On the birthday itself the
    year is counted (lower-bound inclusive), so the 65th birthday returns 65.
    """
    years = as_of.year - date_of_birth.year
    has_birthday_passed_this_year = (as_of.month, as_of.day) >= (
        date_of_birth.month,
        date_of_birth.day,
    )
    if not has_birthday_passed_this_year:
        years -= 1
    return years


def age_band_for(date_of_birth: date, as_of: date | None = None) -> str:
    """Return the plaintext eligibility band for a date of birth.

    Bands are `<18`, `18-34`, `35-49`, `50-64`, `65+`, lower-bound inclusive, so
    each cut point (18 / 35 / 50 / 65) lands in the upper band on the birthday
    itself — the 65th birthday is `65+`, the Medicare-eligibility signal.

    `as_of` defaults to today; passing an explicit reference date keeps the
    function pure and testable against a fixed point. This optional second
    argument is a deliberate, documented extension of the TDD's one-argument
    signature for testability (confirmed at the gate).
    """
    reference_date = as_of if as_of is not None else date.today()
    age_in_years = _completed_years(date_of_birth, reference_date)
    for cut_point, band in _AGE_BAND_CUT_POINTS:
        if age_in_years >= cut_point:
            return band
    return AGE_BAND_UNDER_18
