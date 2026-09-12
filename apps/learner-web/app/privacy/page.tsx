import type { Metadata } from "next";

import { PolicyPage } from "../components/policy-page";
import {
  LEARNER_POLICY_EFFECTIVE_DATE,
  LEARNER_PRIVACY,
} from "../lib/learner-policy";

export const metadata: Metadata = {
  title: "Privacy notice — Authority Closers",
  description:
    "How Authority Closers handles account, learning and optional profile data, and how to make a privacy request.",
};

export default function PrivacyPage() {
  return (
    <PolicyPage
      eyebrow="Privacy notice"
      title="Your data, explained."
      summary="What we collect, why it is used, what others can see and how to exercise your choices."
      effectiveDate={LEARNER_POLICY_EFFECTIVE_DATE}
      sections={LEARNER_PRIVACY.map((section) => ({
        heading: section.heading,
        body: section.paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        )),
      }))}
    />
  );
}
