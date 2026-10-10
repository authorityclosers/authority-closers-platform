"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";

import {
  brandingKey,
  updateBranding,
  useBranding,
} from "../shell/branding-store";
import { OrgLogo } from "../shell/org-logo";
import { useWorkspaceAccess } from "../workspace-access";
import {
  LOGO_TYPES,
  MAX_LOGO_BYTES,
  OrgApiError,
  uploadOrganisationLogo,
} from "./organisation-api";
import styles from "./organisation.module.css";

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

function uploadError(error: unknown) {
  if (!(error instanceof OrgApiError))
    return error instanceof Error && error.message.startsWith("Choose")
      ? error.message
      : "The logo was not saved. Try again.";
  if (error.status === 400 || error.status === 413 || error.status === 422)
    return "Use a still PNG, JPG or WebP image up to 2 MB.";
  if (error.status === 401 || error.status === 403)
    return "Only owners and admins can change the logo.";
  if (error.status === 404 || error.status === 405)
    return "Logo upload isn't available on this server yet.";
  if (error.status === 409 || error.status === 429)
    return "The logo was not saved. Try again in a moment.";
  if (error.status === 503)
    return "Logo storage is unavailable right now. Try again later.";
  return "The logo was not saved. Try again.";
}

/**
 * The organisation's logo: everyone sees it; owners and admins upload or
 * replace it. The preview shows the centre square the server keeps, so what
 * you save is what the sidebar and this page show.
 */
export function CompanyLogoPanel({
  name,
  canEdit,
}: {
  name: string;
  canEdit: boolean;
}) {
  const context = useWorkspaceAccess()?.context ?? null;
  const branding = useBranding();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean }>({
    text: "",
    error: false,
  });
  // One key per chosen file, so a retry of the same upload is not doubled.
  const requestKey = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  const previewUrl = useRef<string | null>(null);
  const showFile = (next: File | null) => {
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = next ? URL.createObjectURL(next) : null;
    setFile(next);
    setPreview(previewUrl.current);
  };
  useEffect(
    () => () => {
      controller.current?.abort();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    },
    [],
  );

  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!chosen) return;
    if (!(LOGO_TYPES as readonly string[]).includes(chosen.type)) {
      setMessage({ text: "Choose a PNG, JPG or WebP image.", error: true });
      return;
    }
    if (chosen.size > MAX_LOGO_BYTES) {
      setMessage({ text: "Choose an image up to 2 MB.", error: true });
      return;
    }
    requestKey.current = null;
    showFile(chosen);
    setMessage({ text: "", error: false });
  };

  const cancel = () => {
    controller.current?.abort();
    showFile(null);
    setMessage({ text: "", error: false });
  };

  const save = async () => {
    const key = brandingKey(context);
    if (!file || !context || !key || saving) return;
    requestKey.current ??= crypto.randomUUID();
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;
    setSaving(true);
    setMessage({ text: "", error: false });
    try {
      const settings = await uploadOrganisationLogo(
        context.tenantId,
        file,
        requestKey.current,
        active.signal,
      );
      if (active.signal.aborted) return;
      updateBranding(key, {
        tenantId: settings.tenant_id,
        name: settings.name,
        logoUrl: settings.logo_url,
      });
      requestKey.current = null;
      showFile(null);
      setMessage({ text: "Logo saved.", error: false });
    } catch (error) {
      if (!active.signal.aborted)
        setMessage({ text: uploadError(error), error: true });
    } finally {
      if (!active.signal.aborted) setSaving(false);
    }
  };

  const hasLogo = Boolean(branding?.logoUrl);
  return (
    <section className={styles.setting} aria-labelledby="org-logo">
      <div className={styles.settingIntro}>
        <h2 id="org-logo">Logo</h2>
        <p>Everyone in the organisation sees it here and in the sidebar.</p>
      </div>
      <div className={styles.settingBody}>
        <div className={styles.logoRow}>
          <span
            className={styles.logoTile}
            data-preview={preview ? "" : undefined}
          >
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element -- A local preview of the chosen file, never uploaded as shown.
              <img src={preview} alt="Preview of the new logo" />
            ) : (
              <OrgLogo
                src={branding?.logoUrl}
                fallback={<span aria-hidden="true">{initials(name)}</span>}
              />
            )}
          </span>
          <div className={styles.logoCopy}>
            {canEdit ? (
              <>
                <div className={styles.logoActions}>
                  {file ? (
                    <>
                      <button
                        type="button"
                        className={styles.secondary}
                        disabled={saving}
                        onClick={() => void save()}
                      >
                        {saving ? "Saving…" : "Save logo"}
                      </button>
                      <button
                        type="button"
                        className={styles.ghost}
                        disabled={saving}
                        onClick={cancel}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className={styles.secondary}
                      onClick={() => input.current?.click()}
                    >
                      {hasLogo ? "Replace logo" : "Upload logo"}
                    </button>
                  )}
                  <input
                    ref={input}
                    type="file"
                    accept={LOGO_TYPES.join(",")}
                    hidden
                    aria-label="Choose a logo image"
                    onChange={choose}
                  />
                </div>
                <small className={styles.hint}>
                  {file
                    ? "This is the square that will show. Save to use it."
                    : "PNG, JPG or WebP, up to 2 MB. The centre square is kept."}
                </small>
              </>
            ) : (
              <small className={styles.hint}>
                Only owners and admins can change the logo.
              </small>
            )}
            <small
              className={styles.hint}
              role={message.error ? "alert" : "status"}
              data-tone={message.error ? "error" : undefined}
            >
              {message.text}
            </small>
          </div>
        </div>
      </div>
    </section>
  );
}
