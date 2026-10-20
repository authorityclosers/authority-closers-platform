import type { Metadata } from "next";
import Link from "next/link";

import { PolicyFooter } from "../policy-footer";
import policy from "../policy-pages.module.css";
import styles from "./developers.module.css";

export const metadata: Metadata = {
  title: "Developers · Sales X-Ray",
  description:
    "Connect your apps to Sales X-Ray: API keys, webhooks, Connect (OAuth), a remote MCP server and a command line.",
};

const HOST = "https://salesxray.authorityclosers.com";
const API = `${HOST}/v1/api`;

const SCOPES: [string, string][] = [
  ["calls:read", "Read calls and their status"],
  ["reports:read", "Read the facts found in calls"],
  ["leads:read", "Read leads"],
  ["leads:write", "Add leads"],
  ["webhooks:manage", "Manage the webhook (coming to the API)"],
];

const ENDPOINTS: [string, string, string, string][] = [
  [
    "GET",
    "/me",
    "any",
    "Who is calling: the organisation or workspace, the person and the scopes",
  ],
  [
    "GET",
    "/calls?before=<call id>",
    "calls:read",
    "Calls, newest first, 50 a page, each with its title and a link to its report",
  ],
  [
    "GET",
    "/calls/{id}",
    "calls:read",
    "One call; with reports:read also the facts found in it",
  ],
  [
    "GET",
    "/calls/{id}/facts",
    "reports:read",
    "The facts found in one call, each with its quote",
  ],
  ["GET", "/leads?stage=&offset=", "leads:read", "Leads, newest change first"],
  ["GET", "/leads/{id}", "leads:read", "One lead with its history"],
  [
    "POST",
    "/leads",
    "leads:write",
    "Add a lead; the same external_id again changes nothing",
  ],
];

const EVENTS: [string, string][] = [
  ["analysis.completed", "A call's analysis is ready"],
  ["lead.created", "A lead is added"],
  ["lead.stage_changed", "A lead moves stage (including a reopen)"],
  ["lead.closed", "A lead is won or lost"],
];

const NODE_VERIFY = `import crypto from "node:crypto";

// rawBody: the exact bytes received; secret: your whsec_... signing secret
export function verify(rawBody, header, secret, now = Date.now() / 1000) {
  const items = header.split(",").map((part) => part.split("="));
  const t = Number(items.find(([key]) => key === "t")?.[1]);
  if (!t || Math.abs(now - t) > 300) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(\`\${t}.\`)
    .update(rawBody)
    .digest();
  return items
    .filter(([key]) => key === "v1")
    .some(([, value]) => {
      const given = Buffer.from(value, "hex");
      return given.length === expected.length && crypto.timingSafeEqual(given, expected);
    });
}`;

const PYTHON_VERIFY = `import hashlib, hmac, time

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    items = [part.split("=", 1) for part in header.split(",")]
    t = next((int(v) for k, v in items if k == "t"), 0)
    if not t or abs(time.time() - t) > 300:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return any(k == "v1" and hmac.compare_digest(v, expected) for k, v in items)`;

const CONNECT_URL = `${HOST}/connect?response_type=code
  &client_id=sxc_...
  &redirect_uri=https://your-app.example.com/sales-xray/callback
  &scope=calls:read%20leads:read
  &state=<random>
  &code_challenge=<BASE64URL(SHA256(verifier))>
  &code_challenge_method=S256`;

const TOKEN = `curl ${HOST}/v1/oauth/token \\
  -d grant_type=authorization_code \\
  -d code=sxo_... \\
  -d redirect_uri=https://your-app.example.com/sales-xray/callback \\
  -d code_verifier=<verifier> \\
  -u sxc_...:sxcs_...        # client secret; public apps send client_id and no secret`;

const MCP = `{
  "mcpServers": {
    "sales-xray": {
      "command": "python3",
      "args": ["/path/to/sx.py", "mcp"],
      "env": { "SX_API_KEY": "sxk_live_..." }
    }
  }
}`;

const MCP_URL = `${HOST}/v1/mcp`;

const REMOTE_MCP = `{
  "mcpServers": {
    "sales-xray": { "url": "${MCP_URL}" }
  }
}`;

const REMOTE_MCP_KEY = `{
  "mcpServers": {
    "sales-xray": {
      "url": "${MCP_URL}",
      "headers": { "Authorization": "Bearer sxk_live_..." }
    }
  }
}`;

const REGISTER = `curl ${HOST}/v1/oauth/register \\
  -H "Content-Type: application/json" \\
  -d '{"client_name": "Your App",
       "redirect_uris": ["https://your-app.example.com/sales-xray/callback"],
       "grant_types": ["authorization_code", "refresh_token"],
       "token_endpoint_auth_method": "client_secret_basic"}'
# 201: {"client_id": "sxc_...", "client_secret": "sxcs_...", ...}
# Apps with no server of their own send "token_endpoint_auth_method": "none".`;

const TOOLS: [string, string, string][] = [
  ["whoami", "any", "Who this connection reads as, and its scopes"],
  ["list_calls", "calls:read", "Calls, newest first"],
  ["get_call", "calls:read", "One call, with its facts when allowed"],
  ["call_facts", "reports:read", "The facts found in one call"],
  ["list_leads", "leads:read", "Leads, by stage"],
  ["get_lead", "leads:read", "One lead with its history"],
  ["add_lead", "leads:write", "Add a lead"],
];

function Code({ children, label }: { children: string; label: string }) {
  return (
    <pre className={styles.code} aria-label={label} tabIndex={0}>
      <code>{children}</code>
    </pre>
  );
}

/** Public developer documentation: how any organisation connects its apps. */
export default function DevelopersPage() {
  return (
    <main className={policy.page}>
      <header className={policy.top}>
        <Link className={policy.brand} href="/">
          Sales Xray
        </Link>
      </header>
      <article className={`${policy.content} ${styles.doc}`}>
        <p className={policy.eyebrow}>Sales Xray</p>
        <h1>Developers</h1>
        <p className={policy.intro}>
          Connect your own apps to Sales X-Ray. Keys, webhooks and your
          organisation&apos;s own apps are set up by its owners and admins in{" "}
          <b>Organisation → Integrations</b>. Apps that anyone can use register
          themselves, and each person connects their own account. No forms to
          send us and no keys shared by hand.
        </p>
        <nav className={styles.toc} aria-label="On this page">
          <a href="#keys">API keys</a>
          <a href="#api">API</a>
          <a href="#webhooks">Webhooks</a>
          <a href="#handover">Hand-over</a>
          <a href="#connect">Connect (OAuth)</a>
          <a href="#mcp">Remote MCP</a>
          <a href="#cli">Command line and MCP</a>
        </nav>

        <section id="keys">
          <h2>API keys</h2>
          <p>
            Make a key with a name, only the permissions it needs, and an
            expiry. It is shown once; store it in your app&apos;s secret
            settings. Make one key per app so you can revoke it alone.
            Production keys start <code>sxk_live_</code> and work only on
            production.
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
        </section>

        <section id="api">
          <h2>API</h2>
          <p>
            Base address <code>{API}</code>. Send the key as{" "}
            <code>Authorization: Bearer sxk_live_…</code>, or a Connect access
            token (<code>sxa_…</code>). A key, or an app an organisation
            connected, sees what an organisation owner sees. An app a person
            connected for themself sees only what that person sees: their own
            calls and leads, or their team&apos;s when they are an owner or
            admin, checked on every request. Sensitive parts of calls always
            stay withheld.
          </p>
          <table className={styles.table}>
            <caption>Endpoints</caption>
            <thead>
              <tr>
                <th scope="col">Request</th>
                <th scope="col">Scope</th>
                <th scope="col">Returns</th>
              </tr>
            </thead>
            <tbody>
              {ENDPOINTS.map(([method, path, scope, text]) => (
                <tr key={method + path}>
                  <td>
                    <code>
                      {method} {path}
                    </code>
                  </td>
                  <td>
                    <code>{scope}</code>
                  </td>
                  <td>{text}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Code label="Example request">{`curl ${API}/calls -H "Authorization: Bearer $SX_API_KEY"`}</Code>
          <p>
            Errors are JSON: <code>{`{"error": {"code", "message"}}`}</code>.
            401 means the key is wrong, expired or revoked; 403 that it lacks
            the scope; 429 that it sent more than 120 requests in a minute (wait
            for <code>Retry-After</code> seconds).
          </p>
        </section>

        <section id="webhooks">
          <h2>Webhooks</h2>
          <p>
            Add your app&apos;s https address and pick events. Sales X-Ray shows
            the signing secret (<code>whsec_…</code>) once. Each event is a JSON{" "}
            <code>POST</code> with <code>X-SX-Event-Id</code>,{" "}
            <code>X-SX-Event-Type</code> and{" "}
            <code>X-SX-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code>, where v1
            is HMAC-SHA256 of <code>&lt;t&gt;.</code> followed by the raw body.
            Reject requests more than 5 minutes old, and use the event id to
            ignore repeats. While you change secrets, requests carry two v1
            values; accept either.
          </p>
          <ul>
            {EVENTS.map(([event, text]) => (
              <li key={event}>
                <code>{event}</code>: {text}
              </li>
            ))}
          </ul>
          <p>
            Any 2xx answer counts as delivered. Otherwise Sales X-Ray retries
            from 10 seconds, doubling up to an hour, 25 times; you can send a
            stopped event again from the delivery log. <b>Send test event</b>{" "}
            sends a signed fictional event straight away.
          </p>
          <Code label="Verify a signature in Node.js">{NODE_VERIFY}</Code>
          <Code label="Verify a signature in Python">{PYTHON_VERIFY}</Code>
        </section>

        <section id="handover">
          <h2>Hand-over</h2>
          <p>
            When a lead is won, Sales X-Ray can send the customer to your app:{" "}
            <code>POST &lt;your app&gt;/api/v1/service/customers/handover</code>{" "}
            with your app&apos;s service key as the bearer and an{" "}
            <code>Idempotency-Key</code>. Paste the key and choose what is sent
            in Integrations; the key is kept sealed and never shown again.
          </p>
        </section>

        <section id="connect">
          <h2>Connect (OAuth 2.0)</h2>
          <p>
            Connect signs people in with their Sales X-Ray account, with PKCE
            (S256) on every request. There are two kinds of app:
          </p>
          <ul>
            <li>
              <b>Your organisation&apos;s own app.</b> Register it in
              Integrations → Register your own app. An owner or admin approves
              it for the whole organisation.
            </li>
            <li>
              <b>An app anyone can use.</b> It registers itself (RFC 7591), with
              no step on our side. Each person who connects it approves it for
              their own account, in the workspace they have open (Personal or an
              organisation), and it sees what they see. The consent screen shows
              the address it returns to, so people can check whose app it is.
            </li>
          </ul>
          <Code label="Register an app">{REGISTER}</Code>
          <p>
            Every address is in the server metadata at{" "}
            <code>{`${HOST}/.well-known/oauth-authorization-server`}</code> (RFC
            8414). Send people to the consent screen; they come back to your
            address with a one-time code.
          </p>
          <Code label="Consent screen address">{CONNECT_URL}</Code>
          <Code label="Swap the code for tokens">{TOKEN}</Code>
          <p>
            Access tokens (<code>sxa_…</code>) last an hour and work on the same
            API within the approved scopes. Refresh tokens (<code>sxr_…</code>)
            last 30 days and are replaced each time you use one (
            <code>grant_type=refresh_token</code>); using an old one again ends
            the connection. Revoke with <code>POST /v1/oauth/revoke</code>;
            people can also remove an app they connected from their account.
          </p>
        </section>

        <section id="mcp">
          <h2>Remote MCP</h2>
          <p>
            AI assistants and agents can use Sales X-Ray as an MCP server at{" "}
            <code>{MCP_URL}</code> (Streamable HTTP). Add the address to your
            assistant; it finds Connect by itself (RFC 9728), registers, and
            asks the person to sign in. The assistant then reads as that person,
            within the scopes they approved.
          </p>
          <Code label="Remote MCP with sign-in">{REMOTE_MCP}</Code>
          <p>For a server of your own, an API key works too:</p>
          <Code label="Remote MCP with an API key">{REMOTE_MCP_KEY}</Code>
          <table className={styles.table}>
            <caption>Tools</caption>
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col">Scope</th>
                <th scope="col">Does</th>
              </tr>
            </thead>
            <tbody>
              {TOOLS.map(([tool, scope, text]) => (
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
        </section>

        <section id="cli">
          <h2>Command line and MCP</h2>
          <p>
            <a href="/developers/sx.py" download>
              sx.py
            </a>{" "}
            is one file (Python 3.10 or newer, nothing to install). It reads
            your key from <code>SX_API_KEY</code>.
          </p>
          <Code label="Command line">{`export SX_API_KEY=sxk_live_...
python3 sx.py me
python3 sx.py calls
python3 sx.py facts <call id>
python3 sx.py add-lead --name "Asha Rao" --phone +919800000000 --external-id crm-42`}</Code>
          <p>
            <code>sx.py mcp</code> runs the same tools on your own computer
            (stdio), for assistants that can&apos;t reach a remote server. Add
            it to your assistant&apos;s MCP settings:
          </p>
          <Code label="MCP settings">{MCP}</Code>
        </section>
      </article>
      <PolicyFooter />
    </main>
  );
}
