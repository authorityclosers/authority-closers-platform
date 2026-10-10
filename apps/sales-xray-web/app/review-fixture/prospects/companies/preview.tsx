"use client";

import { useState } from "react";
import { CompanyInformation } from "../../../prospect-company-information";
import { fictionalCompany } from "../../../prospect-company.fixture";
import { CompanyList } from "../../../prospects/company-list";
import styles from "../../../prospect-information.module.css";

const company = fictionalCompany();

export function CompanyFixture() {
  const [selected, setSelected] = useState(false);
  return (
    <main className={styles.preview}>
      <h1>Companies · fictional display</h1>
      <p>
        No account, detected business, saved edit or server API is represented
        here.
      </p>
      <CompanyList companies={[company]} onOpen={() => setSelected(true)} />
      {selected && <CompanyInformation company={company} />}
    </main>
  );
}
