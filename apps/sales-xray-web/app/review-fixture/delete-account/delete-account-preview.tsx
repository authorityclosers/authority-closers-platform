"use client";

/**
 * Settings → Security → Delete account, open, with fictional answers, for
 * screenshots on GitHub (wb-ci --visual). Nothing leaves the browser.
 * `?state=ready|transfer|fresh|staff`.
 */

import { useState, useSyncExternalStore } from "react";

import { DeleteAccountRow } from "../../account-delete";
import styles from "./delete-account-preview.module.css";

const READY = {
  confirm_word: "DELETE",
  fresh_sign_in: true,
  fresh_minutes: 10,
  staff: false,
  transfer_first: [],
  closes_with_account: [],
};
const STATES: Record<string, Record<string, unknown>> = {
  ready: {
    ...READY,
    closes_with_account: [
      { id: "00000000-0000-4000-8000-000000000011", name: "Fictional Desk" },
    ],
  },
  transfer: {
    ...READY,
    transfer_first: [
      {
        id: "00000000-0000-4000-8000-000000000012",
        name: "Fictional Homes",
        other_members: 3,
      },
    ],
  },
  fresh: { ...READY, fresh_sign_in: false },
  staff: { ...READY, staff: true },
};

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (!url.includes("/v1/me/account-deletion")) return real(input, init);
    // Read at answer time: the address is only known after hydration.
    const state = new URLSearchParams(window.location.search).get("state");
    return new Response(JSON.stringify(STATES[state ?? ""] ?? STATES.ready), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return true;
}

const noSubscription = () => () => {};
const readSearch = () => window.location.search;

export function DeleteAccountPreview() {
  const search = useSyncExternalStore(noSubscription, readSearch, () => null);
  useState(install);
  if (search === null) return null;
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Security</h1>
      <DeleteAccountRow defaultOpen />
    </main>
  );
}
