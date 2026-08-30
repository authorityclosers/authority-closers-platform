import type { Metadata } from "next";

import { PolicyPage } from "../components/policy-page";

export const metadata: Metadata = {
  title: "Staging test terms — Authority Closers",
  description:
    "Terms for invitation-only testing of the Authority Closers first learning slice.",
};

export default function TermsPage() {
  return (
    <PolicyPage
      eyebrow="Terms / controlled staging"
      title="Test the product. Do not mistake it for the promise."
      summary="These narrow terms govern invitation-only staging access. They are an operational testing boundary, not the final commercial terms for a production learning service."
      effectiveDate="30 August 2026"
      sections={[
        {
          heading: "Who may use staging",
          body: (
            <p>
              Only invited test users may access this environment. Use your own
              authorized identity, keep your session private, and do not attempt
              to access another person&apos;s or organisation&apos;s data.
              Access may be suspended to protect the test or investigate an
              incident.
            </p>
          ),
        },
        {
          heading: "Permitted testing",
          body: (
            <p>
              You may explore the published preview, complete enabled practice
              steps, and report defects. Do not upload unlawful, confidential,
              or unnecessary personal data; probe other users; bypass controls;
              run unapproved automated traffic; or treat a preview certificate
              as an official credential.
            </p>
          ),
        },
        {
          heading: "Preview status",
          body: (
            <p>
              Features may be incomplete, reset, withdrawn, or changed. Static
              examples and preview progress are not durable facts. No purchase,
              paid entitlement, employment outcome, sales result, or service
              availability commitment is created by staging access.
            </p>
          ),
        },
        {
          heading: "Content and feedback",
          body: (
            <p>
              Authority Closers retains its platform and course materials. You
              retain the rights you already hold in material you submit. By
              sending product feedback, you permit Authority Closers to use it
              to diagnose and improve the service without publishing your
              identity as an endorsement.
            </p>
          ),
        },
        {
          heading: "Ending the test",
          body: (
            <p>
              You may stop using staging at any time and request account-data
              handling through the contact below. Authority Closers may end or
              restrict the test when required for security, compliance,
              reliability, or product decisions. Final production terms must be
              separately reviewed and published before a commercial launch.
            </p>
          ),
        },
      ]}
    />
  );
}
