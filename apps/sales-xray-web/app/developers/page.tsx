import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { PolicyFooter } from "../policy-footer";
import { CodeBlock, CodeTabs } from "./code-block";
import {
  API,
  CONNECT_URL,
  ENDPOINTS,
  ERRORS,
  EVENT_SAMPLE,
  EVENTS,
  HOST,
  MCP_SETUPS,
  MCP_TOOLS,
  MCP_URL,
  REGISTER,
  REMOTE_SETUPS,
  NODE_VERIFY,
  PYTHON_VERIFY,
  SCOPES,
  TOKEN,
} from "./reference";
import styles from "./developers.module.css";

export const metadata: Metadata = {
  title: "Developers · Sales X-Ray",
  description:
    "Connect your apps to Sales X-Ray: quick start, API keys, Connect (OAuth) and apps that register themselves, every endpoint with examples, webhooks, a remote MCP server for AI assistants, limits and errors.",
};

const TOC: {
  id: string;
  label: string;
  children?: { id: string; label: string }[];
}[] = [
  { id: "start", label: "Quick start" },
  { id: "keys", label: "API keys" },
  { id: "connect", label: "Connect (OAuth)" },
  {
    id: "api",
    label: "API reference",
    children: ENDPOINTS.map((item) => ({
      id: item.id,
      label: `${item.method} ${item.path}`,
    })),
  },
  { id: "webhooks", label: "Webhooks" },
  { id: "mcp", label: "AI assistants (MCP)" },
  { id: "cli", label: "Command line" },
  { id: "handover", label: "Hand-over" },
  { id: "limits", label: "Limits and errors" },
];

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={styles.section}>
      <h2 id={`${id}-title`}>
        <a href={`#${id}`}>{title}</a>
      </h2>
      {children}
    </section>
  );
}

function Method({ method }: { method: string }) {
  return (
    <span className={styles.method} data-method={method}>
      {method}
    </span>
  );
}

/** Public developer documentation: how any organisation connects its apps. */
export default function DevelopersPage() {
  return (
    <main className={styles.page}>
      <header className={styles.top}>
        <Link className={styles.brand} href="/">
          Sales X-Ray
        </Link>
        <span className={styles.crumb}>Developers</span>
        <Link className={styles.openApp} href="/settings/developers">
          Open Settings → Developers
        </Link>
      </header>
      <div className={styles.layout}>
        <nav className={styles.toc} aria-label="On this page">
          <p>On this page</p>
          <ul>
            {TOC.map((item) => (
              <li key={item.id}>
                <a href={`#${item.id}`}>{item.label}</a>
                {item.children ? (
                  <ul>
                    {item.children.map((child) => (
                      <li key={child.id}>
                        <a href={`#${child.id}`}>{child.label}</a>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        </nav>
        <article className={styles.doc}>
          <header className={styles.hero}>
            <p className={styles.eyebrow}>Sales X-Ray for developers</p>
            <h1>Connect your apps to Sales X-Ray</h1>
            <p>
              Read calls and the facts found in them, read and add leads, hear
              about new reports and leads the moment they happen, and let AI
              assistants work with your data. Keys, webhooks and your
              organisation&apos;s own apps are set up by its owners and admins
              in <b>Settings → Developers</b>. Apps that anyone can use register
              themselves, and each person connects their own account. Nothing to
              send us, no keys shared by hand.
            </p>
            <ul className={styles.cards}>
              <li>
                <a href="#api">
                  <strong>REST API</strong>
                  <span>
                    Calls, facts and leads over HTTPS with an API key.
                  </span>
                </a>
              </li>
              <li>
                <a href="#webhooks">
                  <strong>Webhooks</strong>
                  <span>
                    Signed events when an analysis is ready or a lead changes.
                  </span>
                </a>
              </li>
              <li>
                <a href="#mcp">
                  <strong>AI assistants</strong>
                  <span>An MCP server for Claude, Cursor and VS Code.</span>
                </a>
              </li>
            </ul>
          </header>

          <Section id="start" title="Quick start">
            <ol className={styles.steps}>
              <li>
                <strong>Make a key.</strong> In Sales X-Ray open{" "}
                <Link href="/settings/developers">Settings → Developers</Link>,
                choose <b>New key</b>, give it a name and only the permissions
                it needs, and copy it. It is shown once.
              </li>
              <li>
                <strong>Keep it secret.</strong> Put it in your app&apos;s
                secret settings or an environment variable, e.g.{" "}
                <code>SX_API_KEY</code>. Never in a web page or a phone app.
              </li>
              <li>
                <strong>Make a request.</strong> Every request sends the key as
                a bearer token. Or use <b>Try the API</b> in Settings →
                Developers.
              </li>
            </ol>
            <CodeTabs
              label="Your first request"
              samples={[
                { key: "curl", label: "curl", code: ENDPOINTS[0].curl },
                { key: "js", label: "JavaScript", code: ENDPOINTS[0].js },
              ]}
            />
            <CodeBlock label="Answer" code={ENDPOINTS[0].answer} />
          </Section>

          <Section id="keys" title="API keys">
            <p>
              A key belongs to one organisation and sees what its owners see.
              Make one key per app so you can revoke it alone; choose an expiry
              (30, 90 or 365 days, or never). Production keys start{" "}
              <code>sxk_live_</code> and work only on production; keys made
              anywhere else start <code>sxk_test_</code>. Sales X-Ray keeps only
              a fingerprint of the key and its first characters, so a lost key
              is replaced, not recovered.
            </p>
            <table className={styles.table}>
              <caption>Permissions (scopes)</caption>
              <thead>
                <tr>
                  <th scope="col">Scope</th>
                  <th scope="col">Allows</th>
                </tr>
              </thead>
              <tbody>
                {SCOPES.map(([scope, text]) => (
                  <tr key={scope}>
                    <td>
                      <code>{scope}</code>
                    </td>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section id="connect" title="Connect (OAuth 2.0)">
            <p>
              Connect signs people in with their Sales X-Ray account, with PKCE
              (S256) on every request. There are two kinds of app:
            </p>
            <ul className={styles.facts}>
              <li>
                <strong>Your organisation&apos;s own app.</strong> Register it
                in <b>Settings → Developers → Your own apps</b>. An owner or
                admin approves it for the whole organisation.
              </li>
              <li>
                <strong>An app anyone can use.</strong> It registers itself (RFC
                7591), with no step on our side. Each person who connects it
                approves it for their own account, in the workspace they have
                open (Personal or an organisation), and it sees what they see.
                The consent screen shows the address it returns to, so people
                can check whose app it is.
              </li>
            </ul>
            <CodeBlock label="Register an app" code={REGISTER} />
            <p>
              Every address is in the server metadata at{" "}
              <code>{`${HOST}/.well-known/oauth-authorization-server`}</code>{" "}
              (RFC 8414). Send people to the consent screen; they come back to
              your address with a one-time code.
            </p>
            <CodeBlock
              label="1. Send people to the consent screen"
              code={CONNECT_URL}
            />
            <CodeBlock label="2. Swap the code for tokens" code={TOKEN} />
            <p>
              Access tokens (<code>sxa_…</code>) last an hour and work on the
              same API as keys, within the approved scopes. Refresh tokens (
              <code>sxr_…</code>) last 30 days and are replaced each time you
              use one (<code>grant_type=refresh_token</code>); using an old one
              again ends the connection. Revoke with{" "}
              <code>POST /v1/oauth/revoke</code>; people can also remove an app
              they connected from their account.
            </p>
          </Section>

          <Section id="api" title="API reference">
            <p>
              Base address <code>{API}</code>. Answers are JSON. Send{" "}
              <code>Authorization: Bearer sxk_live_…</code>, or a Connect access
              token (<code>sxa_…</code>), with every request. A key, or an app
              an organisation connected, sees what an organisation owner sees.
              An app a person connected for themself sees only what that person
              sees: their own calls and leads, or their team&apos;s when they
              are an owner or admin, checked on every request. Sensitive parts
              of calls always stay withheld.
            </p>
            {ENDPOINTS.map((item) => (
              <section
                key={item.id}
                id={item.id}
                className={styles.endpoint}
                aria-labelledby={`${item.id}-title`}
              >
                <h3 id={`${item.id}-title`}>
                  <Method method={item.method} />
                  <code>{item.path}</code>
                  {item.scope ? (
                    <span className={styles.scope}>{item.scope}</span>
                  ) : (
                    <span className={styles.scope}>any key</span>
                  )}
                </h3>
                <p>{item.summary}</p>
                {item.params.length ? (
                  <table className={styles.table}>
                    <caption>Parameters</caption>
                    <thead>
                      <tr>
                        <th scope="col">Name</th>
                        <th scope="col">In</th>
                        <th scope="col">Type</th>
                        <th scope="col">What it does</th>
                      </tr>
                    </thead>
                    <tbody>
                      {item.params.map((param) => (
                        <tr key={param.name}>
                          <td>
                            <code>{param.name}</code>
                          </td>
                          <td>{param.where}</td>
                          <td>{param.type}</td>
                          <td>{param.text}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
                <CodeTabs
                  label={`${item.method} ${item.path}`}
                  samples={[
                    { key: "curl", label: "curl", code: item.curl },
                    { key: "js", label: "JavaScript", code: item.js },
                  ]}
                />
                <CodeBlock label="Answer" code={item.answer} />
                {item.notes ? (
                  <p className={styles.note}>{item.notes}</p>
                ) : null}
              </section>
            ))}
          </Section>

          <Section id="webhooks" title="Webhooks">
            <p>
              In <b>Settings → Developers → Webhook</b>, add your app&apos;s
              https address and pick events. Sales X-Ray shows the signing
              secret (<code>whsec_…</code>) once. Each event is a JSON{" "}
              <code>POST</code> with <code>X-SX-Event-Id</code>,{" "}
              <code>X-SX-Event-Type</code> and{" "}
              <code>X-SX-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code>, where
              v1 is HMAC-SHA256 of <code>&lt;t&gt;.</code> followed by the raw
              body.
            </p>
            <table className={styles.table}>
              <caption>Events</caption>
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">When</th>
                </tr>
              </thead>
              <tbody>
                {EVENTS.map(([event, text]) => (
                  <tr key={event}>
                    <td>
                      <code>{event}</code>
                    </td>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <CodeBlock
              label="An event as your app receives it"
              code={EVENT_SAMPLE}
            />
            <h3 className={styles.subhead}>Check the signature</h3>
            <p>
              Reject requests more than 5 minutes old, and use the event id to
              ignore repeats. While you change secrets, requests carry two v1
              values; accept either.
            </p>
            <CodeTabs
              label="Check a signature"
              samples={[
                { key: "node", label: "Node.js", code: NODE_VERIFY },
                { key: "python", label: "Python", code: PYTHON_VERIFY },
              ]}
            />
            <h3 className={styles.subhead}>Delivery and retries</h3>
            <p>
              Any 2xx answer counts as delivered. Otherwise Sales X-Ray tries
              again from 10 seconds, doubling up to an hour, 25 times; you can
              send a stopped event again from the delivery log.{" "}
              <b>Send test event</b> sends a signed, fictional{" "}
              <code>sx.test.v1</code> event straight away.
            </p>
          </Section>

          <Section id="mcp" title="AI assistants (MCP)">
            <p>
              AI assistants and agents can use Sales X-Ray as a remote MCP
              server at <code>{MCP_URL}</code> (Streamable HTTP). Add the
              address to your assistant; it finds Connect by itself (RFC 9728),
              registers, and asks the person to sign in. The assistant then
              reads as that person, within the scopes they approved.
            </p>
            <CodeTabs
              label="Add Sales X-Ray to your assistant"
              samples={REMOTE_SETUPS.map((item) => ({
                key: item.key,
                label: item.label,
                code: item.code,
                note: item.where,
              }))}
            />
            <table className={styles.table}>
              <caption>Tools</caption>
              <thead>
                <tr>
                  <th scope="col">Tool</th>
                  <th scope="col">Scope</th>
                  <th scope="col">What it does</th>
                </tr>
              </thead>
              <tbody>
                {MCP_TOOLS.map(([tool, scope, text]) => (
                  <tr key={tool}>
                    <td>
                      <code>{tool}</code>
                    </td>
                    <td>
                      <code>{scope}</code>
                    </td>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              Only the tools the connection&apos;s scopes allow are listed. A
              request without a valid token gets 401 with{" "}
              <code>WWW-Authenticate: Bearer resource_metadata=…</code>.
            </p>
            <h3 className={styles.subhead}>On your own computer (stdio)</h3>
            <p>
              For assistants that can&apos;t reach a remote server,{" "}
              <code>sx.py</code> runs the same tools on your computer (all but{" "}
              <code>get_call</code>), with an API key. One file, Python 3.10 or
              newer, nothing to install.
            </p>
            <ol className={styles.steps}>
              <li>
                <strong>Make a key</strong> with <code>calls:read</code>,{" "}
                <code>reports:read</code> and <code>leads:read</code> (and{" "}
                <code>leads:write</code> to add leads).
              </li>
              <li>
                <strong>Download</strong>{" "}
                <a href="/developers/sx.py" download>
                  sx.py
                </a>{" "}
                and note where you saved it.
              </li>
              <li>
                <strong>Add it to your assistant</strong>, replacing the path
                and the key. On Windows use <code>python</code> instead of{" "}
                <code>python3</code>.
              </li>
            </ol>
            <CodeTabs
              label="Run sx.py in your assistant"
              samples={MCP_SETUPS.map((item) => ({
                key: item.key,
                label: item.label,
                code: item.code,
                note: item.where,
              }))}
            />
            <p>
              Off production, add <code>SX_API_BASE</code> with that site&apos;s{" "}
              <code>/v1/api</code> address next to <code>SX_API_KEY</code>;
              Settings → Developers writes it for you.
            </p>
          </Section>

          <Section id="cli" title="Command line">
            <p>
              The same <code>sx.py</code> is a command line. It reads your key
              from <code>SX_API_KEY</code>, never from an argument, so it stays
              out of your shell history. Output is JSON.
            </p>
            <CodeBlock
              label="Command line"
              code={`export SX_API_KEY=sxk_live_...
python3 sx.py me
python3 sx.py calls
python3 sx.py facts <call id>
python3 sx.py leads --stage new
python3 sx.py add-lead --name "Asha Rao" --phone +919800000000 --external-id crm-42`}
            />
          </Section>

          <Section id="handover" title="Hand-over">
            <p>
              When a lead is won, Sales X-Ray can send the customer to your app:{" "}
              <code>
                POST &lt;your app&gt;/api/v1/service/customers/handover
              </code>{" "}
              with your app&apos;s service key as the bearer and an{" "}
              <code>Idempotency-Key</code>. Paste the key and choose what is
              sent in <b>Settings → Developers → Hand-over</b>; the key is kept
              sealed and never shown again.
            </p>
          </Section>

          <Section id="limits" title="Limits and errors">
            <ul className={styles.facts}>
              <li>
                <strong>120 requests a minute</strong> per key; then{" "}
                <code>429</code> with <code>Retry-After</code> (seconds).
              </li>
              <li>
                <strong>Pages:</strong> 50 calls a page (<code>before</code>),
                up to 50 leads (<code>limit</code>, <code>offset</code>).
              </li>
              <li>
                <strong>Errors</strong> are JSON:{" "}
                <code>{`{"error": {"code": "…", "message": "…"}}`}</code>. Show
                the message; branch on the code.
              </li>
            </ul>
            <table className={styles.table}>
              <caption>Error codes</caption>
              <thead>
                <tr>
                  <th scope="col">Status</th>
                  <th scope="col">Code</th>
                  <th scope="col">Meaning</th>
                </tr>
              </thead>
              <tbody>
                {ERRORS.map(([status, code, text]) => (
                  <tr key={code}>
                    <td>{status}</td>
                    <td>
                      <code>{code}</code>
                    </td>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className={styles.note}>
              Base address on production: <code>{HOST}</code>. Test keys work on
              the test sites only, and live keys on production only.
            </p>
          </Section>
        </article>
      </div>
      <PolicyFooter />
    </main>
  );
}
