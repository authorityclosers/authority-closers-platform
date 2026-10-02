"use client";

import { LightboxShell, type LightboxShellProps } from "./shell/lightbox-shell";
import { PolicyFooter } from "./policy-footer";

export type AcquisitionShellProps = LightboxShellProps & {
  showPolicyLinks?: boolean;
};

/** The standalone Sales Xray shell. Callers and the embed API are unchanged. */
export function AcquisitionShell(props: AcquisitionShellProps) {
  const { showPolicyLinks, children, ...shellProps } = props;
  const shouldShowPolicyLinks = showPolicyLinks ?? !shellProps.authenticated;
  return (
    <LightboxShell {...shellProps}>
      {children}
      {shouldShowPolicyLinks ? <PolicyFooter /> : null}
    </LightboxShell>
  );
}
