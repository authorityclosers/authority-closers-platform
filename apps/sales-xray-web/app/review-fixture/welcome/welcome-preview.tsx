"use client";

/**
 * /welcome (first-run setup) with a fictional person and business, for
 * screenshots on GitHub (wb-ci --visual). Nothing is read or sent.
 * `?step=start|name|business|team|first` and `&path=business|solo|join`.
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
  "start",
  "name",
  "business",
  "team",
  "first",
];
const PATHS: readonly SetupPath[] = ["business", "solo", "join"];

const noSubscription = () => () => {};
const readSearch = () => window.location.search;

export function WelcomePreview() {
  // Null on the server, the address on the client: no hydration mismatch.
  const search = useSyncExternalStore(noSubscription, readSearch, () => null);
  if (search === null) return null;
  const query = new URLSearchParams(search);
  const path = PATHS.find((item) => item === query.get("path")) ?? "business";
  const asked = STEPS.find((item) => item === query.get("step")) ?? "start";
  const step = stepsFor(path).includes(asked) ? asked : "start";
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
          personalId: "00000000-0000-4000-8000-000000000002",
          invite:
            path === "join"
              ? {
                  inviteId: "00000000-0000-4000-8000-000000000003",
                  tenantId: "00000000-0000-4000-8000-000000000004",
                  organisationName: "Fictional Homes",
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
