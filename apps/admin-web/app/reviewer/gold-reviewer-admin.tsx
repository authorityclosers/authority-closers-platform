"use client";

import { useEffect, useState } from "react";
import { z } from "zod";

import { goldRequest } from "./review/gold-review-api";
import styles from "./review/gold-review-workspace.module.css";

const reviewers = z.object({
  items: z.array(
    z.object({
      person_id: z.uuid(),
      email: z.string().nullable(),
      active: z.boolean(),
      verified: z.boolean(),
    }),
  ),
});

export function GoldReviewerAdmin() {
  const [people, setPeople] = useState<z.infer<typeof reviewers>["items"]>([]);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load() {
    setPeople(
      reviewers.parse(
        await goldRequest("/v1/admin/conversation/gold-reviewers"),
      ).items,
    );
  }
  useEffect(() => {
    let active = true;
    void goldRequest("/v1/admin/conversation/gold-reviewers")
      .then((body) => {
        if (active) setPeople(reviewers.parse(body).items);
      })
      .catch(() => {
        if (active) setError("Gold reviewers could not be loaded. Try again.");
      });
    return () => {
      active = false;
    };
  }, []);
  async function change(address: string, active: boolean) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await goldRequest("/v1/admin/conversation/gold-reviewers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: address, active }),
      });
      setMessage(
        active
          ? "Gold reviewer added. New real reports will appear in their review queue."
          : "Gold reviewer removed. Their gold assignments are now closed.",
      );
      await load();
      setEmail("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "This change did not save.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className={`${styles.main} ${styles.panel}`}
      aria-labelledby="gold-reviewers-heading"
    >
      <div>
        <h2 id="gold-reviewers-heading">Gold reviewers</h2>
        <p>
          Each new real call is assigned once after its AI report is saved.
          Sandbox calls are excluded. Reviewers use their separate reviewer
          sign-in.
        </p>
      </div>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void change(email, true);
        }}
      >
        <label>
          Reviewer email
          <textarea
            rows={1}
            required
            value={email}
            placeholder="reviewer@example.com"
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <div className={styles.save}>
          <button disabled={busy || !email.trim()}>
            {busy ? "Saving…" : "Add gold reviewer"}
          </button>
          <span>No learner access is added.</span>
        </div>
      </form>
      {people.map((person) => (
        <div className={styles.progress} key={person.person_id}>
          <div>
            <strong>{person.email}</strong>
            <p>
              {person.active ? "Active gold reviewer" : "Removed"}
              {person.verified ? "" : " · waiting for email verification"}
            </p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void change(person.email ?? "", !person.active)}
          >
            {person.active ? "Remove" : "Add again"}
          </button>
        </div>
      ))}
      {message ? <p role="status">{message}</p> : null}
      {error ? (
        <div className={styles.error}>
          <p role="alert">{error}</p>
          <button
            type="button"
            onClick={() => {
              setError("");
              void load().catch(() =>
                setError("Gold reviewers could not be loaded."),
              );
            }}
          >
            Try again
          </button>
        </div>
      ) : null}
    </section>
  );
}
