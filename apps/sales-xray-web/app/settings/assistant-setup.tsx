"use client";

/**
 * Settings -> Developers -> Connect your AI assistant (owner, 20 Oct: "the mcp
 * server ... not clear"). Step by step, with a copy button for each setup: the
 * one-file MCP server (/developers/sx.py, stdio) in Claude Desktop, Claude
 * Code, Cursor or VS Code, reading the organisation's calls and leads with an
 * API key.
 */
import { useState } from "react";
import { Download } from "lucide-react";

import { Panel, Segmented } from "../ui/kit";
import { CopyButton } from "./copy-button";
import { useOrigin } from "./use-origin";
import styles from "./developers.module.css";

type Assistant = "claude-desktop" | "claude-code" | "cursor" | "vscode";

const PRODUCTION = "https://salesxray.authorityclosers.com";
const KEY = "paste-your-key-here";

const ASSISTANTS: { key: Assistant; label: string; where: string }[] = [
  {
    key: "claude-desktop",
    label: "Claude Desktop",
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

export function AssistantSetup() {
  const origin = useOrigin();
  const [assistant, setAssistant] = useState<Assistant>("claude-desktop");
  const chosen =
    ASSISTANTS.find((item) => item.key === assistant) ?? ASSISTANTS[0];
  const snippet = assistantSnippet(assistant, origin);
  return (
    <Panel
      title="Connect your AI assistant"
      sub="Let Claude, Cursor or VS Code read your calls and leads (MCP)"
    >
      <ol className={styles.steps}>
        <li>
          <strong>Make an API key</strong>
          <span>
            Use <b>New key</b> above with <code>calls:read</code>,{" "}
            <code>reports:read</code> and <code>leads:read</code> (add{" "}
            <code>leads:write</code> if it may add leads). One key per
            assistant, so you can revoke it alone.
          </span>
        </li>
        <li>
          <strong>Download the Sales Xray MCP server</strong>
          <span>One file; it needs Python 3.10 or newer and nothing else.</span>
          <a className={styles.download} href="/developers/sx.py" download>
            <Download size={14} aria-hidden="true" />
            Download sx.py
          </a>
        </li>
        <li>
          <strong>Add it to your assistant</strong>
          <Segmented
            label="Your assistant"
            items={ASSISTANTS.map(({ key, label }) => ({ key, label }))}
            value={assistant}
            onChange={setAssistant}
          />
          <span>{chosen.where}</span>
          <div className={styles.snippet}>
            <pre
              className={styles.code}
              tabIndex={0}
              aria-label={`${chosen.label} setup`}
            >
              <code>{snippet}</code>
            </pre>
            <CopyButton
              text={snippet}
              label={`Copy the ${chosen.label} setup`}
            />
          </div>
          <span className={styles.hint}>
            Replace <code>/path/to/sx.py</code> with where you saved it and{" "}
            <code>{KEY}</code> with your key. On Windows, use{" "}
            <code>python</code> instead of <code>python3</code>.
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
    </Panel>
  );
}
