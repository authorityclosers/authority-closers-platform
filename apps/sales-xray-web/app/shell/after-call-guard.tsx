"use client";

/**
 * After every call the phone app placed, its lead's "How did it go?" stays
 * until the seller answers it (owner, 19 Nov 2026, Wise Life: "After the call
 * the pop-up doesn't ask; it should lock until answered … not skippable by
 * navigating away").
 *
 * Mounted once in the shell, so it hears the phone's call-ended report on any
 * page, not only while that lead is open. While the answer is missing, every
 * move away from that lead brings the seller back to its question, the same
 * one Home's Finish row opens (handOverAnswer). It draws nothing of its own.
 * In a browser, or once the answer is saved, it does nothing.
 */

import { useCallback, useEffect, useRef } from "react";

import { handOverAnswer } from "../leads/lead-handoff";
import {
  inPhoneApp,
  onPhoneCall,
  onPhoneSignal,
  readLastCall,
} from "../leads/native-phone";
import type { NativeCall } from "../leads/native-phone";
import {
  PENDING_ANSWER_EVENT,
  answerAccount,
  callToAnswer,
  dialledLead,
  forgetDial,
  rememberCallToAnswer,
} from "../leads/pending-answer";
import { useWorkspaceAccess } from "../workspace-access";

/** How often a lead closed in place (no navigation event) is noticed. */
const LOOK_MS = 1500;

/** Is this lead open on its own sheet right now? */
export function showingLead(location: Location, leadId: string): boolean {
  return (
    location.pathname.replace(/\/+$/, "") === "/leads" &&
    new URLSearchParams(location.search).get("lead") === leadId
  );
}

export function AfterCallGuard({
  openLead,
}: {
  openLead: (href: string) => void;
}) {
  const workspace = useWorkspaceAccess();
  const account = answerAccount(workspace?.context ?? null);
  const open = useRef(openLead);
  useEffect(() => {
    open.current = openLead;
  });
  // The last lead it brought the seller back to, and when: one hand-over per
  // look, so a slow Leads page isn't asked twice at once.
  const sent = useRef<{ leadId: string; at: number } | null>(null);

  const hold = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    const pending = callToAnswer(account);
    if (!pending) return;
    if (showingLead(window.location, pending.leadId)) {
      sent.current = null;
      return;
    }
    const now = Date.now();
    if (
      sent.current?.leadId === pending.leadId &&
      now - sent.current.at < LOOK_MS * 2
    )
      return;
    sent.current = { leadId: pending.leadId, at: now };
    handOverAnswer(pending.leadId);
    open.current(`/leads?lead=${encodeURIComponent(pending.leadId)}`);
  }, [account]);

  useEffect(() => {
    if (!account || !inPhoneApp()) return;
    let live = true;
    const take = (call: NativeCall) => {
      if (!call.endedMs) return;
      forgetDial(call.leadId);
      if (rememberCallToAnswer(account, call)) hold();
    };
    // Back in the app: a call whose end this page never heard (Android closed
    // it during the call) is read from the phone.
    const catchUp = () => {
      const leadId = dialledLead();
      if (!leadId) return hold();
      void readLastCall(leadId).then((call) => {
        if (live && call) take(call);
        if (live) hold();
      });
    };
    const stopCalls = onPhoneCall(take);
    const stopSignal = onPhoneSignal((event) => {
      if (event === "resume") catchUp();
    });
    const onEvent = () => hold();
    const onVisible = () => {
      if (document.visibilityState === "visible") catchUp();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("popstate", onEvent);
    window.addEventListener(PENDING_ANSWER_EVENT, onEvent);
    const look = window.setInterval(hold, LOOK_MS);
    catchUp();
    return () => {
      live = false;
      stopCalls();
      stopSignal();
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("popstate", onEvent);
      window.removeEventListener(PENDING_ANSWER_EVENT, onEvent);
      window.clearInterval(look);
    };
  }, [account, hold]);

  return null;
}
