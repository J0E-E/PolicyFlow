// Tests for the public-intake client validation. These assert the client mirror
// matches the backend's PublicIntakeRequest rules exactly (the server stays
// authoritative, but the visitor should see the same verdict). Pure functions —
// no React.

import { describe, expect, it } from "vitest";

import {
  emptyShopperIntakeValues,
  validateShopperIntakeField,
  validateShopperIntakeForm,
} from "./shopperIntakeValidation.ts";
import type { ShopperIntakeFormValues } from "./shopperIntakeValidation.ts";

// A fully-valid set of values — each test mutates one field to prove its rule.
const validValues: ShopperIntakeFormValues = {
  firstName: "Margaret",
  lastName: "Chen",
  email: "margaret.chen@example.com",
  phone: "(305) 555-0149",
  dateOfBirth: "1956-03-12",
  zipCode: "33134",
  streetAddress: "88 Coral Way",
  preferredContactMethod: "email",
  notes: "",
  productLines: ["medicare_advantage"],
};

describe("validateShopperIntakeField", () => {
  it("passes every field on a fully-valid form", () => {
    expect(validateShopperIntakeForm(validValues)).toEqual({});
  });

  it("requires the names", () => {
    expect(
      validateShopperIntakeField("firstName", {
        ...validValues,
        firstName: "   ",
      }),
    ).toBeDefined();
    expect(
      validateShopperIntakeField("lastName", { ...validValues, lastName: "" }),
    ).toBeDefined();
  });

  it("rejects a malformed email and accepts a well-formed one", () => {
    expect(
      validateShopperIntakeField("email", { ...validValues, email: "nope" }),
    ).toBeDefined();
    expect(
      validateShopperIntakeField("email", {
        ...validValues,
        email: "a@b.co",
      }),
    ).toBeUndefined();
  });

  it("requires 10-15 phone digits after stripping non-digits", () => {
    // 9 digits → too few.
    expect(
      validateShopperIntakeField("phone", {
        ...validValues,
        phone: "123-456-78",
      }),
    ).toBeDefined();
    // 10 digits in a formatted number → ok.
    expect(
      validateShopperIntakeField("phone", {
        ...validValues,
        phone: "(305) 555-0149",
      }),
    ).toBeUndefined();
    // 16 digits → too many.
    expect(
      validateShopperIntakeField("phone", {
        ...validValues,
        phone: "1234567890123456",
      }),
    ).toBeDefined();
  });

  it("accepts 5-digit and ZIP+4, rejects other shapes", () => {
    expect(
      validateShopperIntakeField("zipCode", { ...validValues, zipCode: "33134" }),
    ).toBeUndefined();
    expect(
      validateShopperIntakeField("zipCode", {
        ...validValues,
        zipCode: "33134-1234",
      }),
    ).toBeUndefined();
    expect(
      validateShopperIntakeField("zipCode", { ...validValues, zipCode: "3313" }),
    ).toBeDefined();
    expect(
      validateShopperIntakeField("zipCode", {
        ...validValues,
        zipCode: "ABCDE",
      }),
    ).toBeDefined();
  });

  it("requires a past date of birth on or after 1900", () => {
    expect(
      validateShopperIntakeField("dateOfBirth", {
        ...validValues,
        dateOfBirth: "2999-01-01",
      }),
    ).toBeDefined();
    expect(
      validateShopperIntakeField("dateOfBirth", {
        ...validValues,
        dateOfBirth: "1899-12-31",
      }),
    ).toBeDefined();
    expect(
      validateShopperIntakeField("dateOfBirth", {
        ...validValues,
        dateOfBirth: "1956-03-12",
      }),
    ).toBeUndefined();
  });

  it("requires 1-10 product lines", () => {
    expect(
      validateShopperIntakeField("productLines", {
        ...validValues,
        productLines: [],
      }),
    ).toBeDefined();
    const eleven = Array.from({ length: 11 }, (_, index) => `line_${index}`);
    expect(
      validateShopperIntakeField("productLines", {
        ...validValues,
        productLines: eleven,
      }),
    ).toBeDefined();
  });

  it("treats the optional fields as always valid", () => {
    expect(
      validateShopperIntakeField("streetAddress", emptyShopperIntakeValues),
    ).toBeUndefined();
    expect(
      validateShopperIntakeField("notes", emptyShopperIntakeValues),
    ).toBeUndefined();
    expect(
      validateShopperIntakeField(
        "preferredContactMethod",
        emptyShopperIntakeValues,
      ),
    ).toBeUndefined();
  });
});

describe("validateShopperIntakeForm", () => {
  it("flags every required field on the empty form", () => {
    const errors = validateShopperIntakeForm(emptyShopperIntakeValues);
    expect(errors.firstName).toBeDefined();
    expect(errors.lastName).toBeDefined();
    expect(errors.email).toBeDefined();
    expect(errors.phone).toBeDefined();
    expect(errors.dateOfBirth).toBeDefined();
    expect(errors.zipCode).toBeDefined();
    expect(errors.productLines).toBeDefined();
  });
});
