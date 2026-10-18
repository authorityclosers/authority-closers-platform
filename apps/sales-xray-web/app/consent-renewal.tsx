"use client";

import { ExternalLink, ShieldCheck } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  ConsentRequestError,
  readConsent,
  renewConsent,
  type ConsentRecord,
} from "./consent-renewal-client";
import styles from "./consent-renewal.module.css";
import { dismissNotice, notify } from "./notice-center";
import { Button } from "./ui/kit";
import { useWorkspaceAccess } from "./workspace-access";

const READ_NOTICE = "consent-read";
const SAVE_NOTICE = "consent-save";

/**
 * One calm card, shown once to a signed-in person whose recorded consent is
 * not the current document, whatever way they signed in. It covers the page
 * without moving it, and accepting returns to the page they were on. Nothing
 * renders (and nothing shifts) for someone whose consent is current.
 *
 * The words, version and links come from the server's document; accepting
 * sends that same version back. Problems appear as corner cards.
 */
export function ConsentRenewal() {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true;
  const key = access?.context?.sessionId ?? "";
  // The answer belongs to the session it was read for, so a person who signs
  // in after someone else never meets the earlier person's card.
  const [loaded, setLoaded] = useState<{
    key: string;
    record: ConsentRecord;
  } | null>(null);
  const consent = signedIn && loaded?.key === key ? loaded.record : null;
  const [checked, setChecked] = useState(false);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const savingRef = useRef(false);
  const cardRef = useRef<HTMLElement>(null);
  const latest = useRef({ consent, checked, key });
  const acceptRef = useRef<() => void>(() => {});
  const titleId = useId();
  const leadId = useId();

  useEffect(() => {
    latest.current = { consent, checked, key };
  }, [consent, checked, key]);

  useEffect(() => {
    if (!signedIn) return;
    const controller = new AbortController();
    void readConsent(controller.signal)
      .then((record) => {
        if (controller.signal.aborted) return;
        dismissNotice(READ_NOTICE);
        setLoaded({ key, record });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        // Signed out, or an account that cannot accept here: nothing to ask.
        if (
          error instanceof ConsentRequestError &&
          (error.status === 401 || error.status === 403)
        ) {
          setLoaded(null);
          return;
        }
        notify({
          id: READ_NOTICE,
          tone: "error",
          title: "Couldn't check the Terms",
          message: "Your calls and reports are safe. Try again in a moment.",
          action: { label: "Try again", run: () => setAttempt((n) => n + 1) },
        });
      });
    return () => controller.abort();
  }, [signedIn, key, attempt]);

  const open = consent !== null && consent.status !== "current";

  // Corner cards rise above this card while it is up (notice-center.module.css).
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    document.documentElement.setAttribute("data-sx-consent", "");
    cardRef.current?.focus();
    return () => {
      document.documentElement.removeAttribute("data-sx-consent");
      dismissNotice(SAVE_NOTICE);
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, [open]);

  const accept = useCallback(async () => {
    const { consent: shown, checked: agreed, key: shownKey } = latest.current;
    if (!shown || !agreed || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const updated = await renewConsent(shown.document.version);
      if (updated.status !== "current") throw new Error("consent_not_recorded");
      dismissNotice(SAVE_NOTICE);
      setLoaded({ key: shownKey, record: updated });
    } catch (error: unknown) {
      if (error instanceof ConsentRequestError && error.status === 409) {
        // The words changed while they read: show the new ones, ask again.
        try {
          const record = await readConsent();
          setLoaded({ key: shownKey, record });
          if (record.status !== "current") {
            setChecked(false);
            notify({
              id: SAVE_NOTICE,
              tone: "info",
              title: "The Terms were just updated",
              message: "Please read the new version, then accept.",
            });
          }
        } catch {
          notify({
            id: SAVE_NOTICE,
            tone: "error",
            title: "Couldn't save your answer",
            message: "Check your connection and try again.",
            action: { label: "Try again", run: () => acceptRef.current() },
          });
        }
      } else if (error instanceof ConsentRequestError && error.status === 403) {
        notify({
          id: SAVE_NOTICE,
          tone: "error",
          title: "This account can't accept here",
          message: "Only an active account with a verified email can accept.",
        });
      } else if (error instanceof ConsentRequestError && error.status === 401) {
        notify({
          id: SAVE_NOTICE,
          tone: "error",
          title: "You were signed out",
          message: "Reload the page and sign in again.",
          action: { label: "Reload", run: () => window.location.reload() },
        });
      } else {
        notify({
          id: SAVE_NOTICE,
          tone: "error",
          title: "Couldn't save your answer",
          message: "Check your connection and try again.",
          action: { label: "Try again", run: () => acceptRef.current() },
        });
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, []);

  useEffect(() => {
    acceptRef.current = () => void accept();
  }, [accept]);

  if (!open || !consent) return null;

  const { document: terms } = consent;
  const renewal = consent.status === "renewal_required";

  // The page behind stays put but cannot be reached: Tab cycles in the card
  // and Escape does not close it.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      return;
    }
    if (event.key !== "Tab" || !cardRef.current) return;
    const stops = Array.from(
      cardRef.current.querySelectorAll<HTMLElement>(
        "a[href], input:not(:disabled), button:not(:disabled)",
      ),
    );
    if (!stops.length) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    const here = document.activeElement;
    if (event.shiftKey && (here === first || here === cardRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && here === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void accept();
  };

  return (
    <div className={styles.scrim} onKeyDown={onKeyDown}>
      <section
        ref={cardRef}
        className={styles.card}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={leadId}
        aria-busy={saving}
        tabIndex={-1}
        data-consent-status={consent.status}
        data-consent-version={terms.version}
      >
        <span className={styles.icon} aria-hidden="true">
          <ShieldCheck size={20} />
        </span>
        <h2 id={titleId} className={styles.title}>
          {renewal ? "We've updated our terms" : "Accept our terms to continue"}
        </h2>
        <p id={leadId} className={styles.lead}>
          Please read the {renewal ? "updated " : ""}Terms and Privacy notice,
          then accept to keep using Sales Xray.
        </p>
        <div className={styles.links}>
          <a
            className={styles.link}
            href={terms.terms_path}
            target="_blank"
            rel="noreferrer"
          >
            Terms
            <ExternalLink size={14} aria-hidden="true" />
          </a>
          <a
            className={styles.link}
            href={terms.privacy_path}
            target="_blank"
            rel="noreferrer"
          >
            Privacy notice
            <ExternalLink size={14} aria-hidden="true" />
          </a>
        </div>
        <form className={styles.form} onSubmit={submit}>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={checked}
              disabled={saving}
              onChange={(event) => setChecked(event.target.checked)}
            />
            <span>{terms.acknowledgement}</span>
          </label>
          <Button
            type="submit"
            variant="primary"
            className={styles.accept}
            disabled={!checked || saving}
          >
            {saving ? "Saving…" : "Accept and continue"}
          </Button>
        </form>
      </section>
    </div>
  );
}
