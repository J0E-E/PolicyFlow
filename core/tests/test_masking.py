"""Unit tests for the pure PII masking + age-band utilities.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_crypto.py`. They cover all three phases of the module: the fixed-template
maskers (`mask_dob` / `mask_generic` / `mask_phone` / `mask_medicare_id`), the
email masker and its malformed-input fallback, and the `age_band_for` boundary
table including the 65+ Medicare edge. Each masked form is asserted against the
module's named constants/templates rather than re-typed magic strings.
"""

from datetime import date

from app.pii.masking import (
    AGE_BAND_18_TO_34,
    AGE_BAND_35_TO_49,
    AGE_BAND_50_TO_64,
    AGE_BAND_65_AND_OVER,
    AGE_BAND_UNDER_18,
    DATE_OF_BIRTH_MASK,
    GENERIC_MASK_TOKEN,
    age_band_for,
    mask_dob,
    mask_email,
    mask_generic,
    mask_medicare_id,
    mask_phone,
)


# --- Phase 1: fixed-template maskers ---


def test_mask_generic_returns_the_fixed_token():
    """The generic mask is the fixed fully-masked token, leaking nothing."""
    assert mask_generic() == GENERIC_MASK_TOKEN
    assert mask_generic() == "***"


def test_mask_dob_is_the_constant_fully_masked_date():
    """Date of birth always masks to the same constant, whatever the input."""
    assert mask_dob("1960-06-13") == DATE_OF_BIRTH_MASK
    assert mask_dob("1960-06-13") == "****-**-**"
    assert mask_dob("anything") == DATE_OF_BIRTH_MASK


def test_mask_phone_reveals_the_last_four_digits():
    """A normal phone masks to the last-4 template."""
    assert mask_phone("5551234567") == "***-***-4567"


def test_mask_phone_ignores_punctuation_and_spacing():
    """Dashes, parentheses, dots, spaces, and a leading plus do not shift the last 4."""
    assert mask_phone("+1 (555) 123-4567") == "***-***-4567"
    assert mask_phone("555.123.4567") == "***-***-4567"


def test_mask_phone_too_short_degrades_to_the_generic_token():
    """Fewer than four digits never reveals a short tail — it falls back to `***`."""
    assert mask_phone("123") == GENERIC_MASK_TOKEN
    assert mask_phone("") == GENERIC_MASK_TOKEN


def test_mask_medicare_id_reveals_the_last_four_digits():
    """A normal Medicare id masks to its last-4 template."""
    assert mask_medicare_id("123456789") == "***-**-6789"


def test_mask_medicare_id_ignores_punctuation():
    """Punctuation in the Medicare id does not shift the revealed last 4."""
    assert mask_medicare_id("123-45-6789") == "***-**-6789"


def test_mask_medicare_id_too_short_degrades_to_the_generic_token():
    """Fewer than four digits falls back to the generic token, not a short tail."""
    assert mask_medicare_id("99") == GENERIC_MASK_TOKEN


# --- Phase 2: email masking + malformed fallback ---


def test_mask_email_standard_address():
    """A standard address keeps the first local char, first domain char, and TLD."""
    assert mask_email("jane@example.com") == "j***@e***.com"


def test_mask_email_single_char_local_and_domain():
    """A single-character local part and domain name still mask cleanly."""
    assert mask_email("a@b.io") == "a***@b***.io"


def test_mask_email_subdomain_keeps_first_label_and_final_tld():
    """A subdomained domain keeps its first label's first char and the final TLD."""
    assert mask_email("jane@a.b.example.com") == "j***@a***.com"


def test_mask_email_malformed_inputs_route_to_the_generic_token():
    """No `@`, empty local/domain, or no TLD dot all fall back to `***` — no leak."""
    assert mask_email("not-an-email") == GENERIC_MASK_TOKEN  # no @
    assert mask_email("@example.com") == GENERIC_MASK_TOKEN  # empty local
    assert mask_email("jane@") == GENERIC_MASK_TOKEN  # empty domain
    assert mask_email("jane@example") == GENERIC_MASK_TOKEN  # no TLD dot
    assert mask_email("jane@@example.com") == GENERIC_MASK_TOKEN  # two @


# --- Phase 3: age-band boundary table (lower-bound inclusive, incl. 65+ edge) ---


def test_age_band_one_representative_age_in_each_band():
    """One clearly-inside age maps to each of the five bands."""
    as_of = date(2026, 6, 13)
    assert age_band_for(date(2016, 1, 1), as_of) == AGE_BAND_UNDER_18  # 10
    assert age_band_for(date(2000, 1, 1), as_of) == AGE_BAND_18_TO_34  # 26
    assert age_band_for(date(1986, 1, 1), as_of) == AGE_BAND_35_TO_49  # 40
    assert age_band_for(date(1970, 1, 1), as_of) == AGE_BAND_50_TO_64  # 56
    assert age_band_for(date(1950, 1, 1), as_of) == AGE_BAND_65_AND_OVER  # 76


def test_age_band_on_each_cut_point_birthday_lands_in_the_upper_band():
    """On the 18/35/50/65 birthday the age is inclusive — it lands in the upper band."""
    as_of = date(2026, 6, 13)
    assert age_band_for(date(2008, 6, 13), as_of) == AGE_BAND_18_TO_34  # exactly 18
    assert age_band_for(date(1991, 6, 13), as_of) == AGE_BAND_35_TO_49  # exactly 35
    assert age_band_for(date(1976, 6, 13), as_of) == AGE_BAND_50_TO_64  # exactly 50
    assert age_band_for(date(1961, 6, 13), as_of) == AGE_BAND_65_AND_OVER  # exactly 65


def test_age_band_day_before_each_cut_point_lands_in_the_lower_band():
    """The day before a cut-point birthday the person is one year younger — lower band."""
    as_of = date(2026, 6, 13)
    assert age_band_for(date(2008, 6, 14), as_of) == AGE_BAND_UNDER_18  # turns 18 tomorrow
    assert age_band_for(date(1991, 6, 14), as_of) == AGE_BAND_18_TO_34  # turns 35 tomorrow
    assert age_band_for(date(1976, 6, 14), as_of) == AGE_BAND_35_TO_49  # turns 50 tomorrow
    assert age_band_for(date(1961, 6, 14), as_of) == AGE_BAND_50_TO_64  # turns 65 tomorrow


def test_age_band_65th_birthday_is_the_medicare_edge():
    """Explicit 65+ edge: the day before is `50-64`, the 65th birthday is `65+`."""
    as_of = date(2026, 6, 13)
    assert age_band_for(date(1961, 6, 14), as_of) == AGE_BAND_50_TO_64
    assert age_band_for(date(1961, 6, 13), as_of) == AGE_BAND_65_AND_OVER


def test_age_band_defaults_to_today_when_no_reference_date_given():
    """Omitting `as_of` measures against today — a newborn is `<18`."""
    assert age_band_for(date.today()) == AGE_BAND_UNDER_18
