import type { ReactNode } from "react";
import Link from "next/link";
import { StandaloneStudio } from "../../../sales-xray-web/app/standalone-studio";
import { LearnerShell } from "../components/site-shell";

export function SalesXrayShell({
  children,
  current,
}: {
  children: ReactNode;
  current: "analyse" | "calls" | "recordings";
}) {
  return (
    <LearnerShell current="sales-xray">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <nav
          aria-label="Sales Xray sections"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "12px 24px",
            marginBottom: 24,
          }}
        >
          <Link
            href="/sales-xray"
            aria-current={current === "analyse" ? "page" : undefined}
          >
            Analyse a call
          </Link>
          <Link
            href="/sales-xray/calls"
            aria-current={current === "calls" ? "page" : undefined}
          >
            Saved calls
          </Link>
          <Link
            href="/sales-xray/recordings"
            aria-current={current === "recordings" ? "page" : undefined}
          >
            Earlier recordings
          </Link>
        </nav>
        <StandaloneStudio variant="embedded">{children}</StandaloneStudio>
      </main>
    </LearnerShell>
  );
}
