"use client";

import {
  Building2,
  ChevronRight,
  Factory,
  FileText,
  Globe,
  ImageIcon,
  Landmark,
  MapPin,
  ReceiptText,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { OrgLogo } from "../shell/org-logo";
import { Sheet } from "../ui/sheet";
import { useLogoUpload } from "./company-logo-panel";
import family from "./family.module.css";
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
  ["industry", "Industry", 100],
  ["team_size", "Team size", 80],
  ["gstin", "GSTIN", 32],
  ["city", "City", 100],
  ["website", "Website", 500],
  ["address", "Address", 1000],
] as const;
// Long values take the full row so the two columns always line up.
const WIDE = new Set<string>(["website", "address"]);
type FieldKey = (typeof fields)[number][0];
const ICON: Record<FieldKey, LucideIcon> = {
  name: Building2,
  legal_name: Landmark,
  industry: Factory,
  team_size: Users,
  gstin: ReceiptText,
  city: MapPin,
  website: Globe,
  address: FileText,
};
type Props = {
  /** The organisation's name, for the logo's initials and the note under the card. */
  orgName?: string;
  tenantId: string | null;
  role: OrgRole | null;
  authenticated: boolean;
  refresh: () => void;
  onAccessLost: () => void;
  onPersonal: () => void;
};

/**
 * Company details as one card of short rows (sx-redesign board, pick 06 C,
 * owner 21 Nov 2026): the label, the saved value or "Not added", a chevron.
 * A row opens a sheet with that one field and one Save; the logo, while there
 * is none, is the one hero above. This is the form pattern for Settings.
 * Remount private state for each tenant/role; directory roles never grant access.
 */
export function CompanyDetailsPanel(props: Props) {
  if (!props.authenticated || !props.tenantId) return null;
  return (
    <section className={family.stack} aria-labelledby="org-details">
      <h2 id="org-details" className={styles.srOnly}>
        Company details
      </h2>
      {props.role !== "owner" && props.role !== "admin" ? (
        <div className={family.card}>
          <LogoRow canEdit={false} />
          <p className={`${family.note} ${styles.cardNote}`}>
            Only owners and admins can view and edit company details.
          </p>
        </div>
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

/**
 * The logo's row, and while there is none (owners and admins) the hero that
 * asks for it. Its picker and save are the logo panel's own.
 */
function LogoRow({
  canEdit,
  upload,
}: {
  canEdit: boolean;
  upload?: ReturnType<typeof useLogoUpload>;
}) {
  const logo = upload?.logoUrl ?? null;
  const content = (
    <>
      <span className={family.tile}>
        {upload?.preview ? (
          // eslint-disable-next-line @next/next/no-img-element -- A local preview of the chosen file.
          <img src={upload.preview} alt="Preview of the new logo" />
        ) : logo ? (
          <OrgLogo src={logo} fallback={<ImageIcon aria-hidden="true" />} />
        ) : (
          <ImageIcon aria-hidden="true" />
        )}
      </span>
      <span className={family.rowText}>
        <span className={family.rowLabel}>Logo</span>
        <span className={family.rowValue} data-empty={logo ? undefined : ""}>
          {logo ? "Added" : "Not added"}
        </span>
      </span>
      {canEdit ? (
        <span className={family.rowEnd}>
          <ChevronRight className={family.chevron} aria-hidden="true" />
        </span>
      ) : (
        <span />
      )}
    </>
  );
  if (!canEdit || !upload) return <div className={family.row}>{content}</div>;
  return (
    <button
      type="button"
      className={family.row}
      aria-label={logo ? "Logo: change it" : "Logo: not added, add it"}
      onClick={upload.pick}
    >
      {content}
    </button>
  );
}

function DetailsEditor({
  tenantId,
  orgName = "",
  refresh,
  onAccessLost,
  onPersonal,
}: Props & { tenantId: string }) {
  const upload = useLogoUpload();
  // The row being changed in its sheet, or null.
  const [editing, setEditing] = useState<FieldKey | null>(null);
  const [shownField, setShownField] = useState<FieldKey | null>(editing);
  if (editing && editing !== shownField) setShownField(editing);
  const [draft, setDraft] = useState<OrganisationDetails | null>(null);
  // What is saved now: Save shows only when the draft differs from it.
  const [base, setBase] = useState<OrganisationDetails | null>(null);
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
        if (!controller.signal.aborted) {
          setDraft(value);
          setBase(value);
        }
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
      base !== null &&
      !fields.some(([key]) => draft[key] !== base[key]) &&
      !conflict
    ) {
      setEditing(null);
      return;
    }
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
      setBase(value);
      setMessage("Saved.");
      setConflict(false);
      setEditing(null);
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
      <p className={styles.muted}>
        Company details are unavailable. Your access has changed.
      </p>
    );
  if (!draft)
    return (
      <div className={styles.formState}>
        {readFailed ? (
          <p className={styles.muted} role="alert">
            {message}
          </p>
        ) : (
          <div
            className={styles.formSkeleton}
            role="status"
            aria-busy="true"
            aria-label="Loading company details…"
          >
            {fields.map(([key]) => (
              <span key={key} data-wide={WIDE.has(key) ? "" : undefined} />
            ))}
          </div>
        )}
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
  const changed =
    base === null || fields.some(([key]) => draft[key] !== base[key]);
  const saved = base ?? draft;
  const filled =
    fields.filter(([key]) => saved[key].trim()).length +
    (upload.logoUrl ? 1 : 0);
  const total = fields.length + 1;
  const field = fields.find(([key]) => key === shownField) ?? null;
  const close = () => {
    if (saving) return;
    // Closing keeps what is saved: an unsaved change in the sheet is dropped.
    if (base) setDraft(base);
    setMessage("");
    setConflict(false);
    if (request.current) request.current.key = null;
    setEditing(null);
  };
  const failed = Boolean(message && message !== "Saved.");
  return (
    <>
      {upload.canEdit && (!upload.logoUrl || upload.file) ? (
        <div className={family.hero} data-tone="amber" data-ringless="">
          <div className={styles.heroLogo}>
            <span className={family.tile} data-tone="amber">
              {upload.preview ? (
                // eslint-disable-next-line @next/next/no-img-element -- A local preview of the chosen file.
                <img src={upload.preview} alt="Preview of the new logo" />
              ) : (
                <ImageIcon aria-hidden="true" />
              )}
            </span>
            <div className={family.heroBody}>
              <h3 className={family.heroTitle}>
                {upload.file ? "Save your logo" : "Add your logo"}
              </h3>
              <p className={family.heroLine}>
                {upload.file
                  ? "This is the square your team will see. Save to use it."
                  : "Your team sees it in the app. PNG, JPG or WebP, up to 2 MB."}
              </p>
            </div>
            <div className={`${family.heroActions} ${styles.heroLogoActions}`}>
              {upload.file ? (
                <>
                  <button
                    type="button"
                    className={family.primary}
                    disabled={upload.saving}
                    onClick={() => void upload.save()}
                  >
                    {upload.saving ? "Saving…" : "Save logo"}
                  </button>
                  <button
                    type="button"
                    className={family.neutral}
                    disabled={upload.saving}
                    onClick={upload.cancel}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className={family.primary}
                  onClick={upload.pick}
                >
                  Add logo
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
      {upload.input}
      <p className={styles.detailsCount}>
        {filled} of {total} details added
      </p>
      <div className={`${family.card} ${styles.detailsCard}`}>
        <LogoRow canEdit={upload.canEdit} upload={upload} />
        {fields.map(([key, label]) => {
          const Icon = ICON[key];
          const value = saved[key].trim();
          return (
            <button
              key={key}
              type="button"
              className={family.row}
              data-wide={WIDE.has(key) ? "" : undefined}
              aria-label={`${label}: ${value || "not added"}. Change it`}
              onClick={() => {
                setMessage("");
                setEditing(key);
              }}
            >
              <span className={family.tile}>
                <Icon aria-hidden="true" />
              </span>
              <span className={family.rowText}>
                <span className={family.rowLabel}>{label}</span>
                <span
                  className={family.rowValue}
                  data-empty={value ? undefined : ""}
                >
                  {value || "Not added"}
                </span>
              </span>
              <span className={family.rowEnd}>
                <ChevronRight className={family.chevron} aria-hidden="true" />
              </span>
            </button>
          );
        })}
      </div>
      {upload.message.text ? (
        <p
          className={family.hint}
          role={upload.message.error ? "alert" : "status"}
          data-tone={upload.message.error ? "error" : undefined}
        >
          {upload.message.text}
        </p>
      ) : null}
      <p className={family.note}>
        Everyone in {orgName || "your organisation"} sees this.
        {message === "Saved." && !editing ? (
          <span role="status"> Saved.</span>
        ) : null}
      </p>
      <Sheet
        open={editing !== null}
        onClose={close}
        title={field ? field[1] : ""}
        wide="center"
      >
        {field ? (
          <form
            className={family.sheetForm}
            onSubmit={(event) => void save(event)}
            noValidate
            aria-label="Company details"
          >
            <label className={family.field}>
              <span>{field[1]}</span>
              <input
                name={field[0]}
                type="text"
                value={draft[field[0]]}
                maxLength={field[2]}
                required={field[0] === "name"}
                disabled={saving}
                autoFocus
                onChange={(event) => {
                  if (request.current) request.current.key = null;
                  setDraft({ ...draft, [field[0]]: event.target.value });
                  setMessage("");
                  setConflict(false);
                }}
              />
            </label>
            {failed ? (
              <p className={family.hint} role="alert" data-tone="error">
                {message}
              </p>
            ) : null}
            <button
              type="submit"
              className={family.primary}
              disabled={saving || (!changed && !conflict)}
            >
              {saving ? "Saving…" : conflict ? "Retry save" : "Save"}
            </button>
          </form>
        ) : null}
      </Sheet>
    </>
  );
}
