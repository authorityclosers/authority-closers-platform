"use client";

/**
 * Archived and the Bin, /leads/shelf?shelf=archived|bin (owner's M3-A, 17 Nov
 * 2026: "a must"): the leads taken off Leads, each with Restore. The Bin is
 * for owners and admins only; everyone else sees Archived alone.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { SignedOutWelcome } from "../../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import { handOverLead } from "../lead-handoff";
import { readMe } from "../leads-client";
import type { Shelf } from "../shelf-client";
import { ShelfView } from "../shelf-view";

/** Owners and admins open the Bin (shelf.py, DELETERS). */
export const BIN_ROLES = new Set(["owner", "admin"]);

export function ShelfSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <PageHeader title="Archived" titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

export function ShelfRoute() {
  const access = useWorkspaceAccess();
  const router = useRouter();
  const params = useSearchParams();
  const asked: Shelf = params.get("shelf") === "bin" ? "bin" : "archived";
  const [role, setRole] = useState<string | null>(null);
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  const who = `${access?.context?.personId}:${access?.context?.tenantId}`;

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    readMe(controller.signal).then(
      (me) => setRole(me.role),
      () => setRole(""),
    );
    return () => controller.abort();
  }, [authenticated, who]);

  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <ShelfSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="leads"
      >
        <SignedOutWelcome
          title="Sign in to see archived leads"
          text="Leads taken off your lists, ready to bring back."
        />
      </AcquisitionShell>
    );
  }
  const canBin = role !== null && BIN_ROLES.has(role);
  // A seller who follows a Bin link lands on Archived.
  const shelf: Shelf = asked === "bin" && canBin ? "bin" : "archived";
  return (
    <AcquisitionShell authenticated active="leads">
      <PageHeader
        title={shelf === "bin" ? "Bin" : "Archived"}
        titleInBar
        back={{ href: "/leads", label: "Leads" }}
      />
      {role === null ? (
        Array.from({ length: 6 }, (_, index) => <SkeletonRow key={index} />)
      ) : (
        <ShelfView
          key={`${who}:${shelf}`}
          shelf={shelf}
          canBin={canBin}
          onShelf={(next) =>
            router.replace(`/leads/shelf?shelf=${next}`, { scroll: false })
          }
          onOpen={(leadId) => {
            handOverLead(leadId);
            router.push("/leads");
          }}
        />
      )}
    </AcquisitionShell>
  );
}
