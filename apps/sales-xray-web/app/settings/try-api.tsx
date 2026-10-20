"use client";

/**
 * Settings -> Developers -> Try the API (owner, 20 Oct: "a 'Try it' request box
 * that shows a real response"). A real request to /v1/api with a key the person
 * pastes, or the one they just made; the key stays in this tab's memory and is
 * never saved or sent anywhere else.
 */
import { useId, useState } from "react";
import { Send } from "lucide-react";

import { notify } from "../notice-center";
import { Badge, Button, Panel, type Tone } from "../ui/kit";
import { CopyButton } from "./copy-button";
import { useOrigin } from "./use-origin";
import styles from "./developers.module.css";

type Endpoint = {
  id: string;
  path: string;
  label: string;
  scope: string | null;
  needsId?: boolean;
};

export const ENDPOINTS: readonly Endpoint[] = [
  {
    id: "me",
    path: "/me",
    label: "GET /me · the key’s organisation",
    scope: null,
  },
  {
    id: "calls",
    path: "/calls",
    label: "GET /calls · calls, newest first",
    scope: "calls:read",
  },
  {
    id: "leads",
    path: "/leads?limit=5",
    label: "GET /leads · the 5 newest leads",
    scope: "leads:read",
  },
  {
    id: "facts",
    path: "/calls/{id}/facts",
    label: "GET /calls/{id}/facts · facts in one call",
    scope: "reports:read",
    needsId: true,
  },
];

type Answer = { status: number; ms: number; body: string };

const MAX_BODY = 20_000;

function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function tone(status: number): Tone {
  if (status >= 200 && status < 300) return "good";
  if (status === 429 || status >= 500) return "bad";
  return "warn";
}

export function TryApi({
  freshKey,
  onUsed,
}: {
  /** The key made a moment ago in this tab, if any. */
  freshKey: string | null;
  onUsed: () => void;
}) {
  const ids = useId();
  const origin = useOrigin();
  const [endpointId, setEndpointId] = useState(ENDPOINTS[0].id);
  const [typed, setTyped] = useState<string | null>(null);
  const [callId, setCallId] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const endpoint =
    ENDPOINTS.find((item) => item.id === endpointId) ?? ENDPOINTS[0];
  const key = (typed ?? freshKey ?? "").trim();
  const path = endpoint.needsId
    ? endpoint.path.replace("{id}", encodeURIComponent(callId.trim()))
    : endpoint.path;
  const ready =
    /^(sxk|sxa)_/.test(key) && (!endpoint.needsId || callId.trim() !== "");
  const curl = `curl ${origin}/v1/api${path} \\\n  -H "Authorization: Bearer $SX_API_KEY"`;

  async function send() {
    if (!ready || busy) return;
    setBusy(true);
    const started = performance.now();
    try {
      const response = await fetch(`/v1/api${path}`, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        headers: { accept: "application/json", authorization: `Bearer ${key}` },
      });
      const text = await response.text();
      setAnswer({
        status: response.status,
        ms: Math.round(performance.now() - started),
        body:
          text.length > MAX_BODY
            ? `${pretty(text).slice(0, MAX_BODY)}\n… (cut here; the full answer is longer)`
            : pretty(text),
      });
      onUsed();
    } catch {
      notify({
        id: "try-api",
        tone: "error",
        title: "The request didn’t reach the API",
        message: "Check your connection and try again.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Try the API" sub="Send a real request with one of your keys">
      <form
        className={styles.tryForm}
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label className={styles.field} htmlFor={`${ids}-endpoint`}>
          <span>Request</span>
          <select
            id={`${ids}-endpoint`}
            value={endpointId}
            onChange={(event) => {
              setEndpointId(event.target.value);
              setAnswer(null);
            }}
          >
            {ENDPOINTS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          {endpoint.scope ? (
            <small>
              The key needs <code>{endpoint.scope}</code>.
            </small>
          ) : null}
        </label>
        {endpoint.needsId ? (
          <label className={styles.field} htmlFor={`${ids}-call`}>
            <span>Call id</span>
            <input
              id={`${ids}-call`}
              value={callId}
              spellCheck={false}
              autoComplete="off"
              placeholder="An id from GET /calls"
              onChange={(event) => setCallId(event.target.value)}
            />
          </label>
        ) : null}
        <label className={styles.field} htmlFor={`${ids}-key`}>
          <span>API key</span>
          <input
            id={`${ids}-key`}
            type="password"
            value={typed ?? freshKey ?? ""}
            spellCheck={false}
            autoComplete="off"
            placeholder="sxk_…"
            onChange={(event) => setTyped(event.target.value)}
          />
          <small>
            {freshKey && typed === null
              ? "Using the key you just made. It stays in this tab and is never saved."
              : "Paste a key. It stays in this tab and is never saved."}
          </small>
        </label>
        <div className={styles.tryActions}>
          <Button type="submit" variant="primary" disabled={!ready || busy}>
            <Send size={14} aria-hidden="true" />
            {busy ? "Sending…" : "Send request"}
          </Button>
        </div>
      </form>
      {answer ? (
        <div className={styles.answer} role="status" aria-live="polite">
          <div className={styles.answerHead}>
            <Badge tone={tone(answer.status)}>{answer.status}</Badge>
            <span>{answer.ms} ms</span>
          </div>
          <pre
            className={styles.code}
            tabIndex={0}
            aria-label="The API’s answer"
          >
            <code>{answer.body}</code>
          </pre>
        </div>
      ) : null}
      <div className={styles.snippet}>
        <pre
          className={styles.code}
          tabIndex={0}
          aria-label="The same request with curl"
        >
          <code>{curl}</code>
        </pre>
        <CopyButton text={curl} label="Copy the curl command" />
      </div>
    </Panel>
  );
}
