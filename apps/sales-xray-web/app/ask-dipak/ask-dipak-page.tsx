"use client";

/** Ask Dipak, /ask-dipak: the phone's middle tab (Dipak's spec, 13 Nov 2026). */

import { useEffect } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { AskDipakView } from "./ask-dipak-view";
import styles from "./ask-dipak.module.css";
import { COPY } from "./copy";
import { progressFor } from "./progress";

/** The page's own shape while the session settles: the title and a quiet card. */
export function AskDipakSkeleton() {
  return (
    <AcquisitionShell
      authenticated={false}
      loading
      active="coaching"
      pageName={COPY.title}
    >
      <PageHeader title={COPY.title} titleInBar />
      <div className={styles.root} aria-busy="true">
        <div className={styles.hero} style={{ minHeight: 320 }} />
      </div>
    </AcquisitionShell>
  );
}

function Signed({ personId }: { personId: string }) {
  useEffect(() => progressFor(personId), [personId]);
  return (
    <AcquisitionShell authenticated active="coaching" pageName={COPY.title}>
      <PageHeader title={COPY.title} titleInBar />
      <AskDipakView />
    </AcquisitionShell>
  );
}

export function AskDipakRoute() {
  const access = useWorkspaceAccess();
  const personId =
    access?.authenticated === true && access.status === "ready"
      ? (access.context?.personId ?? null)
      : null;
  if (personId) return <Signed personId={personId} />;
  const loading =
    !access || access.authenticated === null || access.status === "loading";
  if (loading) return <AskDipakSkeleton />;
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      active="coaching"
      pageName={COPY.title}
    >
      <SignedOutWelcome
        title="Sign in to learn with Dipak"
        text="Dipak's questions and lessons, with your saved lessons and Next-call missions kept on your account."
      />
    </AcquisitionShell>
  );
}
