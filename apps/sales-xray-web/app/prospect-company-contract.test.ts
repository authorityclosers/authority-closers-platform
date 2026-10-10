import { expect, it } from "vitest";
import { parseCompany, parseCompanyList } from "./prospect-company-contract";
import {
  companyBinding,
  fictionalCompaniesPage,
  fictionalCompanyPayload,
} from "./prospect-company.fixture";

it("keeps company and person identity distinct and missing business fields Unknown", () => {
  const row = parseCompany(fictionalCompanyPayload());
  expect(row.company_id).not.toBe(row.people[0].prospect_id);
  expect(row.fields.city).toEqual({
    state: "unknown",
    reason: "not_mentioned",
  });
  expect(row.fields.size.state).toBe("unknown");
  expect(row.fields.industry.state).toBe("known");
});
it("never matches or merges equal names", () => {
  const payload = fictionalCompaniesPage();
  payload.companies.push({
    ...fictionalCompanyPayload(),
    company_id: companyBinding.personId,
  });
  payload.total = 2;
  const page = parseCompanyList(payload, companyBinding);
  expect(page.companies).toHaveLength(2);
  expect(page.companies[0].name).toBe(page.companies[1].name);
  expect(page.companies[0].company_id).not.toBe(page.companies[1].company_id);
});
it.each(["person_id", "tenant_id", "session_id"])(
  "rejects crossed %s without exposing private input",
  (key) => {
    expect(() =>
      parseCompanyList(
        { ...fictionalCompaniesPage(), [key]: "wrong private actor" },
        companyBinding,
      ),
    ).toThrow("Companies are unavailable");
  },
);
it.each(["phone", "email", "team_size", "budget", "turnover", "role"])(
  "rejects unsupported or person-only %s",
  (key) => {
    const payload = fictionalCompanyPayload();
    expect(() =>
      parseCompany({
        ...payload,
        fields: { ...payload.fields, [key]: payload.fields.name },
      }),
    ).toThrow("Companies are unavailable");
  },
);
it("requires exact native evidence for observed values and consistent human locks", () => {
  const payload = fictionalCompanyPayload();
  expect(() =>
    parseCompany({
      ...payload,
      fields: {
        ...payload.fields,
        industry: { ...payload.fields.industry, evidence: undefined },
      },
    }),
  ).toThrow();
  expect(() =>
    parseCompany({
      ...payload,
      fields: {
        ...payload.fields,
        name: { ...payload.fields.name, locked: false },
      },
    }),
  ).toThrow();
  expect(() =>
    parseCompany({
      ...payload,
      fields: {
        ...payload.fields,
        industry: {
          ...payload.fields.industry,
          evidence: { ...payload.fields.industry.evidence, start_ms: 1900 },
        },
      },
    }),
  ).toThrow();
});
it("does not turn company size into inferred or coerced headcount", () => {
  const payload = fictionalCompanyPayload();
  const size = {
    ...payload.fields.name,
    value: { kind: "text", text: "about 10–20 people across two units" },
  };
  const row = parseCompany({ ...payload, fields: { ...payload.fields, size } });
  expect(row.fields.size).toMatchObject({ value: size.value });
  expect(() =>
    parseCompany({
      ...payload,
      fields: {
        ...payload.fields,
        size: { ...size, value: { kind: "numeric", lower: "10" } },
      },
    }),
  ).toThrow();
});
it("omitted capabilities disable actions instead of deriving a role grant", () => {
  expect(
    parseCompany({
      ...fictionalCompanyPayload(),
      can_edit: undefined,
      can_confirm: undefined,
    }),
  ).toMatchObject({ can_edit: false, can_confirm: false });
});
it.each([
  { company_id: "https://outside.invalid" },
  { revision: 0 },
  { origin: "organisation" },
  { name: "Some unrelated person" },
  { fields: {} },
  { confirmed_at: "invalid" },
  { can_edit: "admin" },
  { people: [{ prospect_id: "by-name", name: "Fictional person" }] },
])("rejects malformed identity or provenance %#", (change) => {
  expect(() =>
    parseCompany({ ...fictionalCompanyPayload(), ...change }),
  ).toThrow("Companies are unavailable");
});
it("rejects duplicate opaque identities and unsafe pagination", () => {
  const payload = fictionalCompaniesPage();
  expect(() =>
    parseCompanyList(
      {
        ...payload,
        companies: [...payload.companies, ...payload.companies],
        total: 2,
      },
      companyBinding,
    ),
  ).toThrow();
  expect(() =>
    parseCompanyList({ ...payload, next_offset: -1 }, companyBinding),
  ).toThrow();
});
