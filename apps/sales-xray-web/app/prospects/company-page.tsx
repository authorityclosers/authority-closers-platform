"use client";

import Link from "next/link";
import { AcquisitionShell } from "../acquisition-shell";
import { CompanyInformation } from "../prospect-company-information";
import type { CompanyRead } from "../prospect-company-client";
import type {
  CompanyFieldKey,
  CompanyListPage,
  CompanyRecord,
} from "../prospect-company-contract";
import { PageSkeleton } from "../shell/page-skeleton";
import { useWorkspaceAccess } from "../workspace-access";
import informationStyles from "../prospect-information.module.css";
import { CompanyList } from "./company-list";
import styles from "./prospects.module.css";

export type CompanyPageRead =
  | { kind: "list"; value: CompanyRead<CompanyListPage> }
  | { kind: "detail"; value: CompanyRead<CompanyRecord> };

/** Route loads the page on the server; this view never starts an effect-driven read. */
export function CompanyPage({
  read,
  pending = false,
  onRetry,
  onOpen,
  onSave,
  onConfirm,
}: {
  read: CompanyPageRead;
  pending?: boolean;
  onRetry?: () => void;
  onOpen?: (companyId: string) => void;
  onSave?: (key: CompanyFieldKey, value: string) => Promise<void>;
  onConfirm?: () => void;
}) {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  const response = read.value;
  const current =
    authenticated &&
    response.status === "ready" &&
    response.binding.personId === access.context?.personId &&
    response.binding.tenantId === access.context?.tenantId &&
    response.binding.sessionId === access.context?.sessionId;
  const loading =
    !access || access.status === "loading" || (authenticated && pending);
  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={!access}
      active="prospects"
    >
      <div className={styles.root}>
        <Link href="/prospects" prefetch={false} className={styles.backLink}>
          Back to Prospects
        </Link>
        <div className={styles.intro}>
          <div>
            <h1 className={styles.title}>Companies</h1>
            <p className={styles.summary}>
              Customer businesses and their explicitly linked people.
            </p>
          </div>
        </div>
        {loading ? (
          <div aria-label="Loading companies" aria-busy="true">
            <PageSkeleton variant="list" />
          </div>
        ) : !authenticated ? (
          <p className={styles.emptyText}>
            Select an authorised workspace to see companies.
          </p>
        ) : !current ? (
          <>
            <p className={styles.emptyText}>
              Company information is unavailable.
            </p>
            <div className={informationStyles.cornerError} role="alert">
              <span>Companies are unavailable. Try again.</span>
              {onRetry && (
                <button
                  type="button"
                  className={styles.retryBtn}
                  onClick={onRetry}
                >
                  Try again
                </button>
              )}
            </div>
          </>
        ) : read.kind === "list" && read.value.status === "ready" ? (
          <CompanyList companies={read.value.data.companies} onOpen={onOpen} />
        ) : read.kind === "detail" && read.value.status === "ready" ? (
          <CompanyInformation
            key={`${access.context?.personId}:${access.context?.tenantId}:${access.context?.sessionId}:${read.value.data.company_id}`}
            company={read.value.data}
            onSave={onSave}
            onConfirm={onConfirm}
          />
        ) : null}
      </div>
    </AcquisitionShell>
  );
}
