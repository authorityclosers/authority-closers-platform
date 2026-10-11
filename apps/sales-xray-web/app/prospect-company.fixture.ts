import { parseCompany } from "./prospect-company-contract";

export const companyId = "00000000-0000-0000-0000-000000000011";
export const companyBinding = {
  personId: "00000000-0000-0000-0000-000000000001",
  tenantId: "00000000-0000-0000-0000-000000000002",
  sessionId: "00000000-0000-0000-0000-000000000003",
};

export function fictionalCompanyPayload() {
  const evidence = {
    submission_id: "00000000-0000-0000-0000-000000000012",
    segment_id: "fictional-company",
    quote: "Fictional व्यवसाय manufactures test parts.",
    start_ms: 1200,
    end_ms: 1800,
  };
  return {
    company_id: companyId,
    name: "Fictional व्यवसाय",
    revision: 2,
    origin: "person",
    confirmed_at: "2026-10-10T10:00:00Z",
    can_edit: true,
    can_confirm: false,
    fields: {
      name: {
        state: "known",
        basis: "person",
        locked: true,
        value: { kind: "text", text: "Fictional व्यवसाय" },
        set_at: "2026-10-10T10:00:00Z",
      },
      industry: {
        state: "known",
        basis: "heard_in_call",
        locked: false,
        value: { kind: "text", text: "manufactures test parts" },
        set_at: "2026-10-10T09:00:00Z",
        evidence,
      },
    },
    people: [
      {
        prospect_id: "00000000-0000-0000-0000-000000000013",
        name: "Fictional person",
      },
    ],
  };
}
export const fictionalCompany = () => parseCompany(fictionalCompanyPayload());
export function fictionalCompaniesPage() {
  return {
    schema: "ac.sales-xray.companies/1",
    person_id: companyBinding.personId,
    tenant_id: companyBinding.tenantId,
    session_id: companyBinding.sessionId,
    companies: [fictionalCompanyPayload()],
    total: 1,
    next_offset: null,
  };
}
