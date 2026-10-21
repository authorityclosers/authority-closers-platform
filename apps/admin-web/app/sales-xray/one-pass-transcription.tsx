"use client";

/**
 * C2 transcription on Gemini 3.1 Flash-Lite, the Flex routes and one pass in the
 * plan (owner, 21 Oct 2026: "So at least get this on prod now!!!", then "build B
 * ... one-pass in the sealed plan"). Four configurations, all derived from today's
 * Scribe one: standard (only C2 on Flash-Lite), Flex (C2, C4 and C5 on Gemini Flex,
 * half price, standard after five minutes of queueing), and each of those with C4
 * as the one-pass request (one read gives the facts, call data and pointer review).
 * Three steps each, all audited:
 * 1. Prepare: the configuration is saved as a provider revision (nothing changes).
 * 2. Root seals that revision's digest (docs/ops/ONE-PASS-PRODUCTION.md).
 * 3. The owner switches: type the confirm word and give the reason (signed in
 *    within ten minutes). Back to Scribe, or from Flex to standard, is one click.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import type { GeminiTier, Transcription } from "./one-pass-data";
import styles from "./one-pass.module.css";

const ACTIVATE = "/v1/admin/conversation/providers/activate";
const PREPARE = "/v1/admin/analysis-pipeline/transcription/prepare";

function key(): string {
  return `one-pass-c2-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

type TierId =
  | "standard"
  | "flex"
  | "one_pass"
  | "one_pass_flex"
  | "luna"
  | "luna_flex";
type Tier = { id: TierId; label: string; state: GeminiTier };

export function TranscriptionSwitch({ view }: { view: Transcription }) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [chosen, setChosen] = useState<TierId | null>(null);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  const onGemini = view.active?.provider === "gemini";
  const onFlex = Boolean(view.active?.flex);
  const onOnePass = Boolean(view.active?.onePass);
  const onOpenAI = Boolean(view.active?.openai);
  const isLuna = (id: TierId | null) => id === "luna" || id === "luna_flex";
  // The owner's action is needed only to add what the active configuration lacks
  // (Flash-Lite, Flex, one pass or OpenAI); dropping one is a click, as on the server.
  const needsOwner = (id: TierId) =>
    !onGemini ||
    (id.endsWith("flex") && !onFlex) ||
    ((id.startsWith("one_pass") || isLuna(id)) && !onOnePass) ||
    (isLuna(id) && !onOpenAI);
  // Onto OpenAI, the owner confirms its DPA is signed; otherwise the one-pass word.
  const word = isLuna(chosen) && !onOpenAI ? view.openaiConfirm : view.confirm;
  const tiers: Tier[] = [
    {
      id: "standard",
      label: "Gemini 3.1 Flash-Lite transcription (standard)",
      state: view.gemini,
    },
    {
      id: "flex",
      label: "Gemini Flex: transcription, facts and report at half price",
      state: view.geminiFlex,
    },
    {
      id: "one_pass",
      label: "One pass: facts, call data and pointer review in one read",
      state: view.onePass,
    },
    {
      id: "one_pass_flex",
      label: "One pass on Gemini Flex",
      state: view.onePassFlex,
    },
    {
      id: "luna",
      label: "One pass and report on OpenAI GPT-6 Luna (the cheapest)",
      state: view.luna,
    },
    {
      id: "luna_flex",
      label: "Luna on OpenAI Flex",
      state: view.lunaFlex,
    },
  ];

  async function run(
    path: string,
    body: unknown,
    idempotent: boolean,
    done: string,
  ) {
    setBusy(true);
    setSaid(null);
    const result = await send("POST", path, body, idempotent ? key() : null);
    setBusy(false);
    if (!result.ok) {
      setSaid({ ok: false, text: result.message });
      return;
    }
    setSaid({ ok: true, text: done });
    setReason("");
    setConfirm("");
    setChosen(null);
    router.refresh();
  }

  const activate = (target: number | null, owner: boolean, done: string) =>
    void run(
      ACTIVATE,
      {
        expected_revision: view.latestRevision,
        target_revision: target,
        ...(owner ? { confirm: confirm.trim(), reason: reason.trim() } : {}),
      },
      true,
      done,
    );

  const inUse = view.active
    ? `${view.active.provider ?? "unknown"} · ${view.active.model ?? "unknown"}${
        onFlex ? " (Flex)" : ""
      }${view.active.onePass ? " · one pass" : ""} (revision ${view.active.revision})`
    : "No provider configuration is active here.";
  const ready = confirm.trim() === word && reason.trim().length >= 10;

  return (
    <div className={styles.switch}>
      <p className={styles.note}>Transcription in use: {inUse}</p>
      {tiers.map((tier) => {
        const active =
          view.active !== null &&
          tier.state.savedRevision === view.active.revision;
        return (
          <div key={tier.id} className={styles.reason}>
            <strong>{tier.label}</strong>
            {active ? (
              <small className={styles.note}>In use.</small>
            ) : tier.state.savedRevision === null && tier.state.unavailable ? (
              <small className={styles.note}>
                {tier.state.unavailable ===
                "configuration_has_no_openai_luna_provider"
                  ? "Add OpenAI GPT-6 Luna in Providers first (its DPA references)."
                  : "Not available from today's configuration."}
              </small>
            ) : tier.state.savedRevision === null ? (
              <span className={styles.actions}>
                <button
                  type="button"
                  className={kitStyles.button}
                  disabled={busy || tier.state.configurationSha256 === null}
                  onClick={() =>
                    void run(
                      PREPARE,
                      { tier: tier.id },
                      false,
                      "Saved. Root seals its digest next; nothing changes until the owner switches.",
                    )
                  }
                >
                  Prepare
                </button>
              </span>
            ) : !tier.state.approved ? (
              <small className={styles.note}>
                Saved as revision {tier.state.savedRevision} (
                {tier.state.configurationSha256?.slice(0, 12)}…). Waiting for
                Root to seal it.
              </small>
            ) : !needsOwner(tier.id) ? (
              <span className={styles.actions}>
                <button
                  type="button"
                  className={kitStyles.button}
                  disabled={busy}
                  onClick={() =>
                    activate(
                      tier.state.savedRevision,
                      false,
                      "Switched. New calls follow it.",
                    )
                  }
                >
                  Switch back to this
                </button>
              </span>
            ) : (
              <span className={styles.actions}>
                <button
                  type="button"
                  className={kitStyles.button}
                  data-variant="primary"
                  disabled={busy || chosen === tier.id}
                  onClick={() => setChosen(tier.id)}
                >
                  Switch to this
                </button>
              </span>
            )}
          </div>
        );
      })}
      {chosen !== null ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const tier = tiers.find((item) => item.id === chosen);
            activate(
              tier?.state.savedRevision ?? null,
              true,
              "Switched. New calls follow it.",
            );
          }}
        >
          <label className={styles.reason}>
            Reason, in the owner&apos;s words
            <input
              value={reason}
              maxLength={200}
              required
              onChange={(event) => setReason(event.target.value)}
              placeholder="Owner, 21 Oct: So at least get this on prod now"
            />
          </label>
          <label className={styles.reason}>
            Type {word} to confirm
            {word === view.openaiConfirm ? " the OpenAI DPA is signed" : ""}
            <input
              value={confirm}
              maxLength={32}
              required
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </label>
          <span className={styles.actions}>
            <button
              type="submit"
              className={kitStyles.button}
              data-variant="primary"
              disabled={busy || !ready}
            >
              Switch
            </button>
            <button
              type="button"
              className={kitStyles.button}
              disabled={busy}
              onClick={() => setChosen(null)}
            >
              Cancel
            </button>
          </span>
        </form>
      ) : null}
      {onGemini ? (
        <span className={styles.actions}>
          <button
            type="button"
            className={kitStyles.button}
            disabled={busy || view.classicRevision === null}
            onClick={() =>
              activate(
                view.classicRevision,
                false,
                "Back on Scribe. New calls follow it at once.",
              )
            }
          >
            Back to Scribe
          </button>
        </span>
      ) : null}
      {said ? (
        <small
          className={said.ok ? styles.note : kitStyles.fieldError}
          role={said.ok ? "status" : "alert"}
        >
          {said.text}
        </small>
      ) : null}
    </div>
  );
}
