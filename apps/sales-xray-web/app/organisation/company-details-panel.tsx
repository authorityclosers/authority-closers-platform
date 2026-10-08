"use client";

import { Building2 } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  noOrganisationSelected,
  OrgApiError,
  readOrganisationSettings,
  saveOrganisationSettings,
  type OrganisationDetails,
  type OrgRole,
} from "./organisation-api";
import styles from "./organisation.module.css";

const fields = [
  ["name", "Company name", 80],
  ["legal_name", "Legal name", 200],
  ["gstin", "GSTIN", 32],
  ["address", "Address", 1000],
  ["industry", "Industry", 100],
  ["team_size", "Team size", 80],
  ["website", "Website", 500],
  ["city", "City", 100],
] as const;
type Props = {
  tenantId: string | null;
  role: OrgRole | null;
  authenticated: boolean;
  refresh: () => void;
  onAccessLost: () => void;
  onPersonal: () => void;
};

/** Remount private state for each tenant/role; directory roles never grant access. */
export function CompanyDetailsPanel(props: Props) {
  if (!props.authenticated || !props.tenantId) return null;
  return (
    <section className={styles.card}>
      <h2>
        <Building2 size={16} aria-hidden="true" /> Company details
      </h2>
      {props.role !== "owner" && props.role !== "admin" ? (
        <p className={styles.cardNote}>
          Only owners and admins can view and edit company details.
        </p>
      ) : (
        <DetailsEditor
          key={`${props.tenantId}:${props.role}`}
          {...props}
          tenantId={props.tenantId}
        />
      )}
    </section>
  );
}

function DetailsEditor({
  tenantId,
  refresh,
  onAccessLost,
  onPersonal,
}: Props & { tenantId: string }) {
  const [draft, setDraft] = useState<OrganisationDetails | null>(null);
  const [message, setMessage] = useState("");
  const [readFailed, setReadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [denied, setDenied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const request = useRef<{
    controller: AbortController;
    key: string | null;
    saving: boolean;
  } | null>(null);
  // Callbacks may change when the organisation header refreshes, without reloading the draft.
  const callbacks = useRef({ refresh, onAccessLost, onPersonal });
  useEffect(() => {
    callbacks.current = { refresh, onAccessLost, onPersonal };
  }, [refresh, onAccessLost, onPersonal]);

  const failure = useCallback((error: unknown, reading: boolean) => {
    if (noOrganisationSelected(error)) {
      callbacks.current.onPersonal();
      return;
    }
    if (
      error instanceof OrgApiError &&
      (error.status === 401 || error.status === 403)
    ) {
      setDraft(null);
      setDenied(true);
      if (request.current) request.current.key = null;
      callbacks.current.onAccessLost();
      return;
    }
    setReadFailed(reading);
    const status = error instanceof OrgApiError ? error.status : null;
    setConflict(status === 409);
    setMessage(
      reading
        ? "Company details could not be loaded. Try again."
        : status === 422
          ? "Check the company details and try again."
          : status === 409
            ? "Company details were not saved. Retry save, or edit the details."
            : "Company details were not saved. Try again.",
    );
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    request.current = { controller, key: null, saving: false };
    readOrganisationSettings(tenantId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setDraft(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) failure(error, true);
      });
    return () => {
      controller.abort();
      request.current = null;
    };
  }, [tenantId, attempt, failure]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const active = request.current;
    if (!draft || !active || active.saving || active.controller.signal.aborted)
      return;
    if (
      draft.name.trim().length < 2 ||
      fields.some(([key, , limit]) => draft[key].trim().length > limit)
    ) {
      setMessage(
        "Company name must be 2–80 characters. Check the field lengths.",
      );
      return;
    }
    active.key ??= crypto.randomUUID();
    active.saving = true;
    setSaving(true);
    setMessage("");
    try {
      const value = await saveOrganisationSettings(
        tenantId,
        draft,
        active.key,
        active.controller.signal,
      );
      if (active.controller.signal.aborted) return;
      setDraft(value);
      setMessage("Saved.");
      setConflict(false);
      active.key = null;
      callbacks.current.refresh();
    } catch (error) {
      if (!active.controller.signal.aborted) failure(error, false);
    } finally {
      if (!active.controller.signal.aborted) {
        active.saving = false;
        setSaving(false);
      }
    }
  };

  if (denied)
    return (
      <p className={styles.cardNote}>
        Company details are unavailable. Your access has changed.
      </p>
    );
  if (!draft)
    return (
      <div>
        <p className={styles.cardNote} role={readFailed ? "alert" : "status"}>
          {readFailed ? message : "Loading company details…"}
        </p>
        {readFailed ? (
          <button
            type="button"
            className={styles.secondary}
            onClick={() => {
              setReadFailed(false);
              setMessage("");
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </button>
        ) : null}
      </div>
    );
  return (
    <form
      className={styles.form}
      onSubmit={(event) => void save(event)}
      noValidate
      aria-label="Company details"
    >
      {fields.map(([key, label, limit]) => (
        <label key={key}>
          <span>{label}</span>
          <input
            name={key}
            type="text"
            value={draft[key]}
            maxLength={limit}
            required={key === "name"}
            disabled={saving}
            onChange={(event) => {
              if (request.current) request.current.key = null;
              setDraft({ ...draft, [key]: event.target.value });
              setMessage("");
              setConflict(false);
            }}
          />
        </label>
      ))}
      <div className={`${styles.saveRow} ${styles.detailsActions}`}>
        <button type="submit" className={styles.primary} disabled={saving}>
          {saving ? "Saving…" : conflict ? "Retry save" : "Save details"}
        </button>
        <small
          className={styles.hint}
          role={message && message !== "Saved." ? "alert" : "status"}
        >
          {message}
        </small>
      </div>
    </form>
  );
}
