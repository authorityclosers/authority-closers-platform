import type { Metadata } from "next";

import { PolicyPage } from "../components/policy-page";

export const metadata: Metadata = {
  title: "Staging privacy notice — Authority Closers",
  description:
    "How the Authority Closers invitation-only staging environment handles identity and learning-test data.",
};

export default function PrivacyPage() {
  return (
    <PolicyPage
      eyebrow="Privacy / controlled staging"
      title="A small data footprint, made visible."
      summary="This notice describes the data needed to operate email/password or Google sign-in and the first invitation-only learning test. It deliberately does not authorize the broader data uses preserved in future architecture plans."
      effectiveDate="31 August 2026"
      sections={[
        {
          heading: "What this environment may receive",
          body: (
            <>
              <p>
                With email/password registration, the platform receives your
                first name, email address, WhatsApp number, password-derived
                credential, consent version, and the security facts needed to
                establish a session. It never stores the plain-text password.
                When Google sign-in is enabled, it may instead receive your
                verified email address, display name, and Google account
                subject; it does not receive your Google password.
              </p>
              <p>
                During an enabled learning test, it may also store your selected
                organisation context, enrollment, drafts, submitted practice
                evidence, authoritative progress, and certificate state.
              </p>
            </>
          ),
        },
        {
          heading: "Account and course-access email",
          body: (
            <p>
              The registration consent covers only the service messages needed
              for verification, password recovery, account security, free-course
              access, and the next learning action. Promotional email remains a
              separate future permission, and WhatsApp messaging is not
              activated in this alpha.
            </p>
          ),
        },
        {
          heading: "Why the data is used",
          body: (
            <p>
              Data is used to authenticate the invited tester, keep one
              person&apos;s learning state separate from another&apos;s, protect
              tenant boundaries, show the correct course version, recover from
              failures, and investigate security or operational incidents. It is
              not sold and analytics cannot become canonical progress.
            </p>
          ),
        },
        {
          heading: "What is intentionally absent",
          body: (
            <p>
              This staging slice does not activate payment processing, public
              community features, WhatsApp automation, call recording, voice
              analysis, autonomous official scoring, advertising profiles, or
              external AI processing of real conversations. A future feature
              requires its own consent, retention, provider, and governance gate
              before use.
            </p>
          ),
        },
        {
          heading: "Protection and retention",
          body: (
            <p>
              Access is restricted by named identity and server-owned
              authorization. Secrets are injected at runtime rather than stored
              in source control. Operational logs are redacted, privileged
              actions create separate audit evidence, and encrypted recovery
              copies follow bounded retention. Test data is kept only as long as
              needed for the controlled test, security evidence, or recovery
              validation.
            </p>
          ),
        },
        {
          heading: "Your choices",
          body: (
            <p>
              Do not use this staging environment if you do not want the data
              above processed for testing. You may ask for access, correction,
              or deletion through the contact below. Some security, audit, or
              backup records may need to be retained for a bounded period and
              will be handled through a reviewed process rather than a hidden
              database edit.
            </p>
          ),
        },
      ]}
    />
  );
}
