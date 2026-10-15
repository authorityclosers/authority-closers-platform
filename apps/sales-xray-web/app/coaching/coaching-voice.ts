"use client";

import { createContext, useContext } from "react";

/**
 * True on another rep's coaching (a fictional AC Sandbox rep, or a rep who
 * shared theirs), so the shared cards say "their", not "your".
 */
export const TheirCoaching = createContext(false);

export const useTheirCoaching = () => useContext(TheirCoaching);

/**
 * True on a real rep's shared coaching: a call opens its report (owners and
 * admins can open it), because a call's own coaching is only ever the rep's.
 */
export const CallsOpenReports = createContext(false);

export function useCallHref() {
  const reports = useContext(CallsOpenReports);
  return (callId: string) =>
    reports ? `/analysis/calls/${callId}` : `/coaching?call=${callId}`;
}
