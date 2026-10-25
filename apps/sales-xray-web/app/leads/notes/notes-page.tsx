"use client";

/**
 * Notes, /leads/notes (owner, 25 Oct 2026: "Add a note" jumped to History, which
 * confused; Notes gets its own place): everything written on the leads a person can see, newest
 * first, the lead on each, and a box that finds notes by their words or the
 * lead's name. A tap opens that lead on Leads.
 */

import { useRouter } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { SignedOutWelcome } from "../../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import { handOverLead } from "../lead-handoff";
import { NotesView } from "../notes-view";

export function NotesSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <PageHeader title="Notes" titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

export function NotesRoute() {
  const access = useWorkspaceAccess();
  const router = useRouter();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <NotesSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="leads"
      >
        <SignedOutWelcome
          title="Sign in to see your notes"
          text="Everything you and your team wrote on your leads, in one place."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="leads">
      <PageHeader
        title="Notes"
        titleInBar
        back={{ href: "/leads", label: "Leads" }}
      />
      <NotesView
        key={`${access.context?.personId}:${access.context?.tenantId}`}
        onOpen={(leadId) => {
          handOverLead(leadId);
          router.push("/leads");
        }}
      />
    </AcquisitionShell>
  );
}
