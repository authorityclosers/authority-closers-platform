"use client";

/**
 * Settings -> Developers -> Connect your AI assistant (owner, 20 Oct: "the mcp
 * server ... not clear"). Step by step, with a copy button for each setup:
 * first the remote MCP server (/v1/mcp, 0370eb5a): add the address and sign
 * in, nothing to download. For assistants that can't reach a remote server,
 * the one-file stdio server (/developers/sx.py) with an API key.
 * ChatGPT first (24 Oct 2026, the connector fixed in 6cecf226): it takes only
 * the remote server, so the download stays hidden for it.
 */
import { useState } from "react";
import { Download } from "lucide-react";

import { Panel, Segmented } from "../ui/kit";
import { CopyButton } from "./copy-button";
import { useOrigin } from "./use-origin";
import styles from "./developers.module.css";

type Assistant =
  | "chatgpt"
  | "claude-desktop"
  | "claude-code"
  | "cursor"
  | "vscode";

const PRODUCTION = "https://salesxray.authorityclosers.com";
const KEY = "paste-your-key-here";

const ASSISTANTS: { key: Assistant; label: string; where: string }[] = [
  {
    key: "chatgpt",
    label: "ChatGPT",
    where: "ChatGPT connects only to the address above.",
  },
  {
    key: "claude-desktop",
    label: "Claude",
    where:
      "In Claude Desktop: Settings → Developer → Edit config. Add this to claude_desktop_config.json, then restart Claude.",
  },
  {
    key: "claude-code",
    label: "Claude Code",
    where: "Run this once in a terminal.",
  },
  {
    key: "cursor",
    label: "Cursor",
    where: "Add this to ~/.cursor/mcp.json (or .cursor/mcp.json in a project).",
  },
  {
    key: "vscode",
    label: "VS Code",
    where:
      "Add this to .vscode/mcp.json in your project, then start the server from the file.",
  },
];

/** The setup for one assistant; the API address is named only off production. */
export function assistantSnippet(assistant: Assistant, origin: string): string {
  const base = origin && origin !== PRODUCTION ? `${origin}/v1/api` : null;
  const env: Record<string, string> = { SX_API_KEY: KEY };
  if (base) env.SX_API_BASE = base;
  const server = { command: "python3", args: ["/path/to/sx.py", "mcp"], env };
  if (assistant === "claude-code")
    return [
      "claude mcp add sales-xray",
      ...Object.entries(env).map(([name, value]) => `  --env ${name}=${value}`),
      "  -- python3 /path/to/sx.py mcp",
    ].join(" \\\n");
  if (assistant === "vscode")
    return JSON.stringify(
      { servers: { "sales-xray": { type: "stdio", ...server } } },
      null,
      2,
    );
  return JSON.stringify({ mcpServers: { "sales-xray": server } }, null, 2);
}

// Where to add the remote server in each assistant; it asks you to sign in.
const REMOTE_WHERE: Record<Assistant, string> = {
  chatgpt:
    "In ChatGPT: Settings → Apps & Connectors → Advanced settings, turn on Developer mode, then Create. Paste the address and keep OAuth.",
  "claude-desktop":
    "In Claude: Customize → Connectors → Add → Add custom connector. Paste the address, then Continue and Add.",
  "claude-code": "Run this once in a terminal, then /mcp to sign in.",
  cursor: "Add this to ~/.cursor/mcp.json.",
  vscode: "Add this to .vscode/mcp.json in your project.",
};

/** The remote server's setup for one assistant, at this site's address. */
export function remoteSnippet(assistant: Assistant, origin: string): string {
  const url = `${origin || PRODUCTION}/v1/mcp`;
  if (assistant === "claude-desktop" || assistant === "chatgpt") return url;
  if (assistant === "claude-code")
    return `claude mcp add --transport http sales-xray ${url}`;
  if (assistant === "vscode")
    return JSON.stringify(
      { servers: { "sales-xray": { type: "http", url } } },
      null,
      2,
    );
  return JSON.stringify({ mcpServers: { "sales-xray": { url } } }, null, 2);
}

function Snippet({ code, label }: { code: string; label: string }) {
  return (
    <div className={styles.snippet}>
      <pre className={styles.code} tabIndex={0} aria-label={label}>
        <code>{code}</code>
      </pre>
      <CopyButton text={code} label={`Copy: ${label}`} />
    </div>
  );
}

export function AssistantSetup() {
  const origin = useOrigin();
  const [assistant, setAssistant] = useState<Assistant>("chatgpt");
  const chosen =
    ASSISTANTS.find((item) => item.key === assistant) ?? ASSISTANTS[0];
  return (
    <Panel title="Connect your AI assistant">
      <ol className={styles.steps} data-steps="remote">
        <li>
          <strong>Add Sales X-Ray to your assistant</strong>
          <div className={styles.picker}>
            <Segmented
              label="Your assistant"
              items={ASSISTANTS.map(({ key, label }) => ({ key, label }))}
              value={assistant}
              onChange={setAssistant}
            />
          </div>
          <span>{REMOTE_WHERE[assistant]}</span>
          <Snippet
            code={remoteSnippet(assistant, origin)}
            label={`${chosen.label} setup`}
          />
        </li>
        <li>
          <strong>Sign in</strong>
          <span>
            Your assistant opens Sales X-Ray: approve it for your account. It
            reads what you can see, in the workspace you have open, and you can
            remove it any time. Nothing to download, no key to copy.
          </span>
        </li>
        <li>
          <strong>Ask it something</strong>
          <span>
            “What objections came up in my last five calls?” · “Which leads are
            waiting for a follow-up?” · “Add a lead: a name, a phone number and
            what they asked about.”
          </span>
        </li>
      </ol>
      {assistant === "chatgpt" ? null : (
        <details className={styles.stdio}>
          <summary>
            Can&apos;t add a remote server? Run it on your computer
          </summary>
          <ol className={styles.steps} data-steps="stdio">
            <li>
              <strong>Make an API key</strong>
              <span>
                Use <b>New key</b> above with <code>calls:read</code>,{" "}
                <code>reports:read</code> and <code>leads:read</code> (add{" "}
                <code>leads:write</code> if it may add leads).
              </span>
            </li>
            <li>
              <strong>Download the Sales X-Ray MCP server</strong>
              <span>
                One file; it needs Python 3.10 or newer and nothing else.
              </span>
              <a className={styles.download} href="/developers/sx.py" download>
                <Download size={14} aria-hidden="true" />
                Download sx.py
              </a>
            </li>
            <li>
              <strong>Add it to {chosen.label}</strong>
              <span>{chosen.where}</span>
              <Snippet
                code={assistantSnippet(assistant, origin)}
                label={`${chosen.label} setup on your computer`}
              />
              <span className={styles.hint}>
                Replace <code>/path/to/sx.py</code> with where you saved it and{" "}
                <code>{KEY}</code> with your key. On Windows, use{" "}
                <code>python</code> instead of <code>python3</code>.
              </span>
            </li>
          </ol>
        </details>
      )}
    </Panel>
  );
}
