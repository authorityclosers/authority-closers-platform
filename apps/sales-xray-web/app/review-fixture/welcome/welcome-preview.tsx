"use client";

/**
 * /welcome (first-run setup) with a fictional person and business, for
 * screenshots on GitHub (wb-ci --visual). Nothing is read or sent.
 * `?step=start|name|business|team|first` and `&path=business|solo|join`;
 * `?path=pick`: where to work right after a sign-in (two organisations and
 * the person's own calls; `&invite=1` adds an invite to join).
 */

import { useSyncExternalStore } from "react";

import { SetupFlow } from "../../welcome/setup-flow";
import {
  stepsFor,
  type SetupPath,
  type SetupStep,
} from "../../welcome/setup-state";

const KINDS = [
  ["simple", "Any business", "Six stages that suit most teams.", "spark"],
  [
    "real_estate",
    "Real estate",
    "From enquiry to site visit to booking.",
    "building",
  ],
  [
    "education",
    "Coaching & education",
    "Counselling, demo class, enrolment.",
    "cap",
  ],
  ["insurance", "Insurance", "Needs, quote, documents, policy.", "shield"],
  [
    "clinic",
    "Clinics & healthcare",
    "Enquiry, appointment, visit, treatment.",
    "heart",
  ],
  [
    "b2b_services",
    "B2B services & agencies",
    "Discovery, meeting, proposal, deal.",
    "briefcase",
  ],
  ["loans", "Loans & finance", "Eligibility, documents, disbursal.", "bank"],
  ["software", "Software & SaaS", "Demo, trial, proposal, signed.", "screen"],
].map(([id, name, blurb, icon]) => ({ id, name, blurb, icon, stages: [] }));

const STEPS: readonly SetupStep[] = [
  "workspace",
  "start",
  "name",
  "business",
  "team",
  "first",
];
const PATHS: readonly SetupPath[] = ["business", "solo", "join", "pick"];

const PERSONAL = "00000000-0000-4000-8000-000000000002";
const HOMES = "00000000-0000-4000-8000-000000000004";
const PARTNERS = "00000000-0000-4000-8000-000000000005";

/** Two organisations and the person's own calls; sign-in opened the first. */
const PICK = {
  workspaces: [
    {
      tenant_id: PERSONAL,
      kind: "personal" as const,
      name: "Personal",
      role: null,
      sales_xray_enabled: true,
    },
    {
      tenant_id: PARTNERS,
      kind: "organisation" as const,
      name: "Fictional Partners Network",
      role: "admin" as const,
      sales_xray_enabled: true,
    },
    {
      tenant_id: HOMES,
      kind: "organisation" as const,
      name: "Fictional Homes",
      role: "member" as const,
      sales_xray_enabled: true,
    },
  ],
  selected: HOMES,
  leads: { [PERSONAL]: 0, [PARTNERS]: 12, [HOMES]: 383 },
};

const noSubscription = () => () => {};
const readSearch = () => window.location.search;

export function WelcomePreview() {
  // Null on the server, the address on the client: no hydration mismatch.
  const search = useSyncExternalStore(noSubscription, readSearch, () => null);
  if (search === null) return null;
  const query = new URLSearchParams(search);
  const path = PATHS.find((item) => item === query.get("path")) ?? "business";
  const asked = STEPS.find((item) => item === query.get("step")) ?? "start";
  const step = stepsFor(path).includes(asked) ? asked : stepsFor(path)[0];
  const invited = path === "join" || query.get("invite") === "1";
  return (
    <SetupFlow
      key={`${path}:${step}`}
      preview={{
        step,
        path,
        person: {
          personId: "00000000-0000-4000-8000-000000000001",
          email: "asha@fictional-homes.example",
          name: "Asha Example",
          personalId: PERSONAL,
          pick: path === "pick" ? PICK : undefined,
          invite: invited
            ? {
                inviteId: "00000000-0000-4000-8000-000000000003",
                tenantId:
                  path === "pick"
                    ? "00000000-0000-4000-8000-000000000006"
                    : HOMES,
                organisationName:
                  path === "pick" ? "Fictional Clinics" : "Fictional Homes",
                role: "member",
                invitedAt: null,
                expiresAt: null,
              }
            : null,
        },
        templates: KINDS,
        orgName:
          step === "start" || step === "name" ? undefined : "Fictional Homes",
        ...(step === "first"
          ? {
              applied: "real_estate",
              invited: ["ravi@fictional-homes.example"],
            }
          : {}),
      }}
    />
  );
}
