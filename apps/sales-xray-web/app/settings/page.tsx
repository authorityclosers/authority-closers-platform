"use client";

import { SectionList } from "./settings-shell";
import styles from "./settings-shell.module.css";

/** Every section at a glance: the list on a phone, cards on a computer. */
export default function SettingsPage() {
  return (
    <div className={styles.overview}>
      <header className={styles.overviewHead}>
        <h1>Settings</h1>
        <p>
          Your account, your organisation, the apps you connect and this device.
        </p>
      </header>
      <SectionList current={null} variant="list" />
    </div>
  );
}
