"use client";

import { useState } from "react";
import { readCompanies } from "../../../prospect-company-client";
import {
  companyBinding,
  fictionalCompany,
} from "../../../prospect-company.fixture";
import {
  CompanyPage,
  type CompanyPageRead,
} from "../../../prospects/company-page";
import { WorkspaceAccessContext } from "../../../workspace-access";
import { Button } from "../../../ui/kit";
import styles from "../../../prospect-information.module.css";

const company = fictionalCompany();
const list: CompanyPageRead = {
  kind: "list",
  value: {
    status: "ready",
    binding: companyBinding,
    data: { companies: [company], total: 1, next_offset: null },
  },
};
const detail: CompanyPageRead = {
  kind: "detail",
  value: { status: "ready", binding: companyBinding, data: company },
};
const unavailable: CompanyPageRead = {
  kind: "list",
  value: {
    status: "unavailable",
    message: "Companies are unavailable. Try again.",
  },
};

/** Invented read states only; the browser proof refuses every persistence API. */
export function CompanyFixture() {
  const [read, setRead] = useState<CompanyPageRead>(list);
  const [pending, setPending] = useState(false);
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: companyBinding,
        retry: () => {},
      }}
    >
      <div className={styles.preview} style={{ minHeight: 0 }}>
        <h1>Companies · fictional display</h1>
        <p>
          No account, detected business, saved edit or server API is represented
          here.
        </p>
        <Button
          className={styles.profileLink}
          onClick={() => setRead(unavailable)}
        >
          Show unavailable
        </Button>
      </div>
      <CompanyPage
        read={read}
        pending={pending}
        onOpen={() => setRead(detail)}
        onRetry={() => {
          setPending(true);
          void readCompanies(companyBinding)
            .then((value) => {
              setRead({ kind: "list", value });
            })
            .finally(() => setPending(false));
        }}
      />
    </WorkspaceAccessContext.Provider>
  );
}
