"use client";

/**
 * Turning on "Analyse my calls automatically" (owner, 26 Oct 2026, approved
 * for v0.96). The sheet shows the server's title and the owner's approved
 * sentence, with the upload terms' privacy details beside them; "Turn on"
 * records the choice for the words and the terms shown, and "Not now" closes
 * and records nothing. It holds no consent words of its own. Used by Settings,
 * Privacy, and by the after-call card when the server says "ask". The upload
 * terms' privacy details show in full, as sealed, and nothing is pre-ticked.
 */
import { useEffect, useState } from "react";

import {
  acquisition,
  parsePolicy,
  type UploadPolicy,
} from "../acquisition-client";
import { notify } from "../notice-center";
import { haptic } from "../ui/haptics";
import { Button, Skeleton } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  chooseAutoAnalysis,
  readAutoAnalysis,
  type AutoAnalysis,
} from "./auto-analysis-client";
import styles from "./sections.module.css";

export function AutoAnalysisSheet({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: (view: AutoAnalysis) => void;
}) {
  const [view, setView] = useState<AutoAnalysis | null>(null);
  const [terms, setTerms] = useState<UploadPolicy | null>(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    Promise.all([
      readAutoAnalysis(controller.signal),
      acquisition("/upload-policy", { signal: controller.signal }).then(
        parsePolicy,
      ),
    ]).then(
      ([next, policy]) => {
        setView(next);
        setTerms(policy);
        setFailed(false);
      },
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, [open]);

  const notice = view?.notice;
  const turnOn = async () => {
    if (!notice || !terms) return;
    setSaving(true);
    try {
      const saved = await chooseAutoAnalysis({
        decision: "granted",
        notice,
        uploadPolicySha256: terms.policy_sha256,
      });
      haptic("success");
      onSaved?.(saved);
      onClose();
    } catch (reason) {
      haptic("error");
      notify({
        id: "auto-analysis",
        tone: "error",
        title: "Automatic analysis didn't turn on",
        message:
          reason instanceof Error && reason.message
            ? reason.message
            : "Not saved. Try again.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={notice?.title ?? "Automatic analysis"}
      footer={
        <>
          <Button variant="ghost" disabled={saving} onClick={onClose}>
            Not now
          </Button>
          <Button
            variant="primary"
            disabled={saving || !notice || !terms}
            onClick={() => void turnOn()}
          >
            {saving ? "Turning on…" : "Turn on"}
          </Button>
        </>
      }
    >
      {failed ? (
        <p className={styles.hint} role="status">
          This couldn&apos;t load. Try again in a moment.
        </p>
      ) : !notice || !terms ? (
        <Skeleton height={96} />
      ) : (
        <div className={styles.stack}>
          <p>{notice.text}</p>
          {terms.privacy_details ? (
            <p className={styles.hint}>{terms.privacy_details}</p>
          ) : null}
        </div>
      )}
    </Sheet>
  );
}
