"use client";

import { LightboxShell, type LightboxShellProps } from "./shell/lightbox-shell";

export type AcquisitionShellProps = LightboxShellProps;

/** The standalone Sales Xray shell. Callers and the embed API are unchanged. */
export function AcquisitionShell(props: AcquisitionShellProps) {
  return <LightboxShell {...props} />;
}
