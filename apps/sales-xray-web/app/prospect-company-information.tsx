"use client";

import Link from "next/link";
import { ProfileFact } from "./prospect-information";
import {
  COMPANY_FIELDS,
  type CompanyFieldKey,
  type CompanyRecord,
} from "./prospect-company-contract";
import styles from "./prospect-information.module.css";

/** Presentation seam; callbacks must save/read back canonical company revisions. */
export function CompanyInformation({
  company,
  saving = false,
  onSave,
  onConfirm,
}: {
  company: CompanyRecord;
  saving?: boolean;
  onSave?: (key: CompanyFieldKey, value: string) => Promise<void>;
  onConfirm?: () => void;
}) {
  return (
    <section className={styles.information} aria-label="Company information">
      <div className={styles.linkSection}>
        <h2>{company.name}</h2>
        <p>
          {company.origin === "detected" && !company.confirmed_at
            ? "Detected company · awaiting confirmation"
            : "Company"}
        </p>
        {company.can_confirm && !company.confirmed_at && onConfirm && (
          <button type="button" disabled={saving} onClick={onConfirm}>
            Confirm company
          </button>
        )}
      </div>
      <dl className={styles.facts}>
        {(Object.keys(COMPANY_FIELDS) as CompanyFieldKey[]).map((key) => (
          <ProfileFact
            key={`${company.company_id}:${key}`}
            label={COMPANY_FIELDS[key]}
            field={company.fields[key]}
            disabled={saving}
            onSave={
              company.can_edit && onSave
                ? (value) => onSave(key, value)
                : undefined
            }
          />
        ))}
      </dl>
      <div className={styles.linkSection}>
        <h2>People linked to this company</h2>
        {company.people.length ? (
          <ul>
            {company.people.map((person) => (
              <li key={person.prospect_id}>
                <Link
                  className={styles.profileLink}
                  prefetch={false}
                  href={`/prospects/${person.prospect_id}`}
                >
                  {person.name}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p>No visible confirmed person links.</p>
        )}
      </div>
    </section>
  );
}
