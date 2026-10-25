"use client";

/**
 * Settings → AI apps, for everyone (owner via the orchestrator, 24 Oct 2026:
 * "redo Settings → Connections / Developers"). First the AI apps this person
 * let into their own Sales X-Ray (Pulse, ChatGPT, Claude…), each with what it
 * may do and a Disconnect; then how to connect one: the address to copy (the
 * screen's one primary action) and the steps for ChatGPT, Claude or any other
 * app that speaks MCP.
 */
import { useEffect, useState } from "react";
import { BadgeCheck, Sparkles, Unplug } from "lucide-react";

import { dismissNotice, notify } from "../notice-center";
import { readSalesXrayWorkspaces } from "../sales-xray-workspaces";
import {
  Avatar,
  Button,
  Dialog,
  Empty,
  List,
  Panel,
  Row,
  Segmented,
  SkeletonRow,
} from "../ui/kit";
import {
  accessWords,
  disconnectAiApp,
  readAiApps,
  usedWords,
  type AiApp,
} from "./ai-apps-client";
import { AiWritesPanel, AppChangesPanel } from "./ai-changes";
import { CopyButton } from "./copy-button";
import { useOrigin } from "./use-origin";
import styles from "./ai-apps.module.css";

type Host = "chatgpt" | "claude" | "other";

const HOSTS: { key: Host; label: string }[] = [
  { key: "chatgpt", label: "ChatGPT" },
  { key: "claude", label: "Claude" },
  { key: "other", label: "Other apps" },
];

const STEPS: Record<Host, { steps: string[]; note?: string }> = {
  chatgpt: {
    steps: [
      "In ChatGPT, open Settings, then Apps & Connectors.",
      "Under Advanced settings, turn on Developer mode, then choose Create.",
      "Name it Sales X-Ray, paste the address, keep OAuth and save.",
      "Sign in to Sales X-Ray when it asks, and choose what ChatGPT may read.",
    ],
    note: "Developer mode is needed until Sales X-Ray is in ChatGPT’s app directory. On work plans an admin may need to allow it.",
  },
  claude: {
    steps: [
      "In Claude, open Customize, then Connectors.",
      "Choose Add, then Add custom connector.",
      "Name it Sales X-Ray, paste the address, then choose Continue and Add.",
      "Choose Connect, sign in to Sales X-Ray and choose what Claude may read.",
    ],
    note: "On a Team or Enterprise plan, an owner adds it once under Organization settings, then Connectors.",
  },
  other: {
    steps: [
      "In the app’s settings, add a remote MCP server.",
      "Paste the address. The app signs you in with OAuth; there is no key to copy.",
      "Sign in to Sales X-Ray and choose what the app may read.",
    ],
  },
};

const RETRY_MS = 5000;

function ConnectPanel() {
  const origin = useOrigin();
  const [host, setHost] = useState<Host>("chatgpt");
  const address = origin ? `${origin}/v1/mcp` : "";
  const guide = STEPS[host];
  return (
    <Panel title="Connect an AI app">
      <div className={styles.connect}>
        <div className={styles.address}>
          <span className={styles.addressWords}>
            <span className={styles.addressLabel}>Sales X-Ray address</span>
            <code className={styles.addressText}>{address || "…"}</code>
          </span>
          <CopyButton
            text={address}
            label="Copy the address"
            variant="primary"
          />
        </div>
        <Segmented
          items={HOSTS}
          value={host}
          onChange={setHost}
          label="Which app"
        />
        <ol className={styles.steps}>
          {guide.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        {guide.note ? <p className={styles.note}>{guide.note}</p> : null}
        <p className={styles.note}>
          An AI app sees only what you can see in Sales X-Ray, and you choose
          what it may read or add when you sign in. What it adds shows which app
          sent it and can be undone for 7 days. Disconnect it here at any time.
        </p>
      </div>
    </Panel>
  );
}

export function AiAppsSection() {
  const [apps, setApps] = useState<AiApp[] | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [places, setPlaces] = useState<Map<string, string>>(() => new Map());
  const [leaving, setLeaving] = useState<AiApp | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const control = new AbortController();
    let timer: number | undefined;
    readAiApps(control.signal).then(
      (next) => {
        dismissNotice("ai-apps");
        setApps(next);
      },
      () => {
        if (control.signal.aborted) return;
        // A corner card, and the list keeps its outline while it tries again.
        notify({
          id: "ai-apps",
          tone: "error",
          title: "Your AI apps did not load",
          message: "Trying again in a moment.",
        });
        timer = window.setTimeout(
          () => setAttempt((value) => value + 1),
          RETRY_MS,
        );
      },
    );
    return () => {
      control.abort();
      window.clearTimeout(timer);
    };
  }, [attempt]);

  useEffect(() => {
    const control = new AbortController();
    // Which workspace each app reads, named only when there is more than one.
    readSalesXrayWorkspaces(control.signal).then(
      (choices) =>
        setPlaces(
          new Map(
            choices.workspaces.length > 1
              ? choices.workspaces.map((place) => [
                  place.tenant_id,
                  place.kind === "personal" ? "Personal" : place.name,
                ])
              : [],
          ),
        ),
      () => undefined,
    );
    return () => control.abort();
  }, []);

  const disconnect = (app: AiApp) => {
    setBusy(true);
    disconnectAiApp(app.id).then(
      (next) => {
        setApps(next);
        setLeaving(null);
        setBusy(false);
        notify({
          id: "ai-apps",
          tone: "success",
          title: `${app.name} is disconnected`,
          message: "It can no longer read your Sales X-Ray.",
        });
      },
      () => {
        setBusy(false);
        notify({
          id: "ai-apps",
          tone: "error",
          title: `${app.name} is still connected`,
          message: "Try Disconnect again in a moment.",
        });
      },
    );
  };

  return (
    <div className={styles.page}>
      <Panel
        title="Connected AI apps"
        sub={apps && apps.length ? `${apps.length}` : undefined}
      >
        {apps === null ? (
          <div className={styles.outline} aria-busy="true">
            <SkeletonRow avatar={36} />
            <SkeletonRow avatar={36} />
          </div>
        ) : apps.length === 0 ? (
          <Empty
            icon={Sparkles}
            title="No AI apps connected"
            text="Connect ChatGPT or Claude below, then ask them about your calls and leads."
          />
        ) : (
          <List label="Connected AI apps">
            {apps.map((app) => (
              <Row
                key={app.id}
                icon={<Avatar name={app.name} size={36} shape="square" />}
                title={
                  <span className={styles.name}>
                    {app.name}
                    {app.verified ? (
                      <BadgeCheck
                        className={styles.check}
                        size={16}
                        aria-label={
                          app.maker
                            ? `Checked: made by ${app.maker}`
                            : "Checked"
                        }
                      />
                    ) : null}
                  </span>
                }
                meta={[
                  accessWords(app.scopes),
                  usedWords(app),
                  places.get(app.workspaceId),
                ]}
                end={
                  <Button
                    variant="secondary"
                    className={styles.disconnect}
                    aria-label={`Disconnect ${app.name}`}
                    title={`Disconnect ${app.name}`}
                    onClick={() => setLeaving(app)}
                  >
                    <Unplug size={16} aria-hidden="true" />
                    <span className={styles.disconnectWord}>Disconnect</span>
                  </Button>
                }
              />
            ))}
          </List>
        )}
      </Panel>
      <AppChangesPanel />
      <AiWritesPanel />
      <ConnectPanel />
      <Dialog
        open={leaving !== null}
        title={leaving ? `Disconnect ${leaving.name}?` : "Disconnect"}
        description="It stops reading your Sales X-Ray at once. You can connect it again later."
        onClose={() => (busy ? undefined : setLeaving(null))}
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => setLeaving(null)}
              disabled={busy}
            >
              Keep it
            </Button>
            <Button
              variant="primary"
              onClick={() => (leaving ? disconnect(leaving) : undefined)}
              disabled={busy}
            >
              {busy ? "Disconnecting…" : "Disconnect"}
            </Button>
          </>
        }
      />
    </div>
  );
}
