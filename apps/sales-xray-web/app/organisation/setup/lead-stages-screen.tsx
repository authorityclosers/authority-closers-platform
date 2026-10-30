"use client";

import { ChevronLeft } from "lucide-react";
import { useRouter } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { useWorkspaceAccess } from "../../workspace-access";
import { OrganisationStages } from "./stages";
import styles from "./stage-editor.module.css";

/**
 * Lead stages as its own page (owner, 31 Oct 2026): More → Lead stages and Settings →
 * Lead stages open it. On a phone it takes the whole screen (no top bar, no tab bar, no
 * +), with its own header leading back, so the first stages show without scrolling.
 */
export function LeadStagesScreen() {
  const access = useWorkspaceAccess();
  const router = useRouter();
  const back = () => {
    if (window.history.length > 1) router.back();
    else router.push("/leads");
  };
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref="/"
      active="organisation"
      pageName="Lead stages"
      mobileFit={false}
      immersive
    >
      <div className={styles.screen}>
        <header className={styles.screenHead}>
          <button
            type="button"
            className={styles.screenBack}
            aria-label="Back"
            onClick={back}
          >
            <ChevronLeft size={24} aria-hidden="true" />
          </button>
          <div>
            <h1>Lead stages</h1>
            <p>What your sellers see</p>
          </div>
        </header>
        <OrganisationStages bare />
      </div>
    </AcquisitionShell>
  );
}
