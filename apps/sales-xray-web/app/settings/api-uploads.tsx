"use client";

/**
 * Analyse calls our apps upload: the organisation's switch for calls an app sends with
 * one of its API keys (API gap 2). The owner delegated the consent model; the orchestrator
 * approved it as drafted on 15 Nov 2026. Owners and admins only, as this screen is.
 *
 * The words are the server's own. Turning it on records them with the upload terms in
 * force, so new upload terms (another AI provider, another retention) ask again. Off, every
 * call an app sends is refused. Minimal on purpose; the owner's UI lane may restyle it.
 */

import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { DevCard } from "./dev-card";

export const TERMS_PATH = "/v1/sales-xray/integrations/api-upload-terms";

export type UploadTerms = {
  state: "on" | "off" | "ask" | "closed";
  open: boolean;
  notice: { title: string; text: string; policySha256: string } | null;
  uploadPolicySha256: string;
};

const STATES = new Set(["on", "off", "ask", "closed"]);

export function readUploadTerms(raw: unknown): UploadTerms | null {
  if (!raw || typeof raw !== "object") return null;
  const body = raw as Record<string, unknown>;
  if (typeof body.state !== "string" || !STATES.has(body.state)) return null;
  const notice =
    body.notice && typeof body.notice === "object"
      ? (body.notice as Record<string, unknown>)
      : null;
  return {
    state: body.state as UploadTerms["state"],
    open: body.open === true,
    notice:
      notice &&
      typeof notice.title === "string" &&
      typeof notice.text === "string" &&
      typeof notice.policy_sha256 === "string"
        ? {
            title: notice.title,
            text: notice.text,
            policySha256: notice.policy_sha256,
          }
        : null,
    uploadPolicySha256:
      typeof body.upload_policy_sha256 === "string"
        ? body.upload_policy_sha256
        : "",
  };
}

async function call(init: RequestInit = {}): Promise<UploadTerms | null> {
  const response = await fetch(TERMS_PATH, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
    },
  });
  if (!response.ok) throw new Error(String(response.status));
  return readUploadTerms(await response.json());
}

export function ApiUploadsSwitch() {
  const [terms, setTerms] = useState<UploadTerms | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    call({ signal: controller.signal }).then(setTerms, () => undefined);
    return () => controller.abort();
  }, []);
  if (!terms || !terms.open || !terms.notice) return null;
  const notice = terms.notice;
  const on = terms.state === "on";
  const choose = (decision: "granted" | "withdrawn") => {
    setBusy(true);
    setFailed(false);
    call({
      method: "POST",
      body: JSON.stringify(
        decision === "granted"
          ? {
              decision,
              policy_sha256: notice.policySha256,
              upload_policy_sha256: terms.uploadPolicySha256,
            }
          : { decision },
      ),
    })
      .then(
        (next) => {
          if (next) setTerms(next);
        },
        () => setFailed(true),
      )
      .finally(() => setBusy(false));
  };
  return (
    <DevCard
      icon={<Upload />}
      tone="teal"
      title={notice.title}
      tools={
        <Button
          variant={on ? "secondary" : "primary"}
          disabled={busy}
          onClick={() => choose(on ? "withdrawn" : "granted")}
        >
          {on ? "Turn off" : "Turn on"}
        </Button>
      }
    >
      <p>{notice.text.split("{organisation}").join("your organisation")}</p>
      <p role="status">
        {on
          ? "On. Calls sent with your API keys are analysed as they arrive."
          : "Off. Calls sent with your API keys are refused until you turn this on."}
      </p>
      {failed ? <p role="alert">That didn’t save. Try again.</p> : null}
    </DevCard>
  );
}
