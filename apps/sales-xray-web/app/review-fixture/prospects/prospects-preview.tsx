"use client";
import { ProspectInformation } from "../../prospect-information";
import { syntheticProspect } from "./synthetic-prospect";
import styles from "../../prospect-information.module.css";

export function ProspectsPreview() {
  return (
    <main className={styles.preview}>
      <h1>Prospect’s Information · fictional display preview</h1>
      <p className={styles.note}>
        Invented words and values. No API requests, real customer or recording.
      </p>
      <ProspectInformation prospect={syntheticProspect} />
    </main>
  );
}
