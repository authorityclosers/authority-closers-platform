import type { Metadata } from "next";

import { PolicyPage } from "../components/policy-page";
import {
  LEARNER_POLICY_EFFECTIVE_DATE,
  LEARNER_TERMS,
} from "../lib/learner-policy";

export const metadata: Metadata = {
  title: "Terms of use — Authority Closers",
  description:
    "Terms for the Authority Closers learning application and Free Course.",
};

export default function TermsPage() {
  return (
    <PolicyPage
      eyebrow="Terms of use"
      title="Clear terms for learning together."
      summary="Your account, free-course access, submitted work and rights when you use Authority Closers."
      effectiveDate={LEARNER_POLICY_EFFECTIVE_DATE}
      sections={LEARNER_TERMS.map((section) => ({
        heading: section.heading,
        body: section.paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        )),
      }))}
    />
  );
}
