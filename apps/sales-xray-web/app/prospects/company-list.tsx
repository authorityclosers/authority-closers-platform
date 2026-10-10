"use client";

import type { CompanyRecord } from "../prospect-company-contract";
import { profileValueText } from "../prospect-profile-contract";
import styles from "./prospects.module.css";

/** Controlled list: source/actor-checked records only; no text matching or fake save. */
export function CompanyList({
  companies,
  onOpen,
}: {
  companies: CompanyRecord[];
  onOpen: (companyId: string) => void;
}) {
  return (
    <section aria-label="Companies" className={styles.prospectsList}>
      {companies.length ? (
        companies.map((company) => {
          const industry = company.fields.industry;
          const city = company.fields.city;
          return (
            <div key={company.company_id} className={styles.prospectRow}>
              <button
                type="button"
                className={styles.companyOpen}
                onClick={() => onOpen(company.company_id)}
              >
                <span className={styles.prospectName}>{company.name}</span>
                <span className={styles.prospectSub}>
                  {industry.state === "known"
                    ? profileValueText(industry.value)
                    : "Industry unknown"}
                  {" · "}
                  {city.state === "known"
                    ? profileValueText(city.value)
                    : "City unknown"}
                </span>
              </button>
              <span className={styles.badge}>
                {company.origin === "detected" && !company.confirmed_at
                  ? "Detected"
                  : "Company"}
              </span>
            </div>
          );
        })
      ) : (
        <p className={styles.emptyText}>No companies recorded yet.</p>
      )}
    </section>
  );
}
