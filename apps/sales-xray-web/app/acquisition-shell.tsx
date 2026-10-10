"use client";

import { usePathname } from "next/navigation";

import { LightboxShell, type LightboxShellProps } from "./shell/lightbox-shell";
import { PolicyFooter } from "./policy-footer";
import {
  useWorkspaceAccess,
  type WorkspaceAccessStatus,
} from "./workspace-access";

export type AcquisitionShellProps = LightboxShellProps & {
  showPolicyLinks?: boolean;
};

/**
 * The public site's policy links belong to public pages only: the landing a
 * signed-out visitor sees. Inside the app (and while a page is still finding
 * out who is signed in) they live in the account menu's Help section.
 */
export function showsPolicyFooter(
  pathname: string | null,
  status: WorkspaceAccessStatus | undefined,
): boolean {
  return pathname === "/" && status === "unauthenticated";
}

/** The standalone Sales Xray shell. Callers and the embed API are unchanged. */
export function AcquisitionShell(props: AcquisitionShellProps) {
  const { showPolicyLinks, children, ...shellProps } = props;
  const pathname = usePathname();
  const access = useWorkspaceAccess();
  const shouldShowPolicyLinks =
    showPolicyLinks ?? showsPolicyFooter(pathname, access?.status);
  return (
    <LightboxShell {...shellProps}>
      {children}
      {shouldShowPolicyLinks ? <PolicyFooter /> : null}
    </LightboxShell>
  );
}
