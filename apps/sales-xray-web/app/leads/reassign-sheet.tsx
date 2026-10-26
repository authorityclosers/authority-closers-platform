"use client";

/**
 * Reassign a lead (owner, #33, 26 Oct 2026): one sheet, not a list that opened
 * inside the lead. Search, each person with their photo or character, the
 * person who has it now ticked, and a tap that moves it, felt in the hand.
 * "Let the lead rules pick" gives it to whoever the organisation's rules say.
 */

import { Check, Search, Shuffle } from "lucide-react";
import { useState } from "react";

import { PersonAvatar } from "../people/person-avatar";
import { haptic } from "../ui/haptics";
import { Sheet } from "../ui/sheet";
import { LeadsError, reassign, type LeadDetail } from "./leads-client";
import styles from "./leads.module.css";

export function ReassignSheet({
  open,
  detail,
  onClose,
  onMoved,
}: {
  open: boolean;
  detail: LeadDetail;
  onClose: () => void;
  onMoved: (next: LeadDetail) => void;
}) {
  const { lead } = detail;
  const [find, setFind] = useState("");
  const [moving, setMoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const owner = lead.owner_person_id;
  // The person who has it now comes first, ticked (even when they take no
  // leads themselves); then everyone else.
  const current =
    detail.reps.find((rep) => rep.person_id === owner) ??
    (owner && lead.owner_name
      ? {
          person_id: owner,
          name: lead.owner_name,
          open_leads: 0,
          available: true,
          photo_url: lead.owner_photo_url,
        }
      : null);
  const people = [
    ...(current ? [current] : []),
    ...detail.reps.filter((rep) => rep.person_id !== owner),
  ];
  const needle = find.trim().toLocaleLowerCase();
  const shown = needle
    ? people.filter((rep) => rep.name.toLocaleLowerCase().includes(needle))
    : people;

  const move = async (personId: string | null, key: string) => {
    haptic("tap");
    setMoving(key);
    setError(null);
    try {
      onMoved(await reassign(lead, personId));
      haptic("success");
      setFind("");
      onClose();
    } catch (reason) {
      haptic("error");
      setError(
        reason instanceof LeadsError ? reason.message : "Not moved. Try again.",
      );
    } finally {
      setMoving(null);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={lead.owner_name ? "Reassign" : "Assign"}
      description={`Who calls ${lead.name.split(" ")[0]} from now on.`}
    >
      <div className={styles.reassignSheet}>
        {people.length > 4 ? (
          <label className={styles.reassignFind}>
            <Search size={20} aria-hidden="true" />
            <input
              type="search"
              value={find}
              placeholder="Find a person"
              aria-label="Find a person"
              onChange={(event) => setFind(event.target.value)}
            />
          </label>
        ) : null}
        <button
          type="button"
          className={styles.repPick}
          disabled={moving !== null}
          aria-busy={moving === "rules" || undefined}
          onClick={() => void move(null, "rules")}
        >
          <span className={styles.repPickIcon} aria-hidden="true">
            <Shuffle size={20} />
          </span>
          <span>
            <strong>Let the lead rules pick</strong>
            <small>
              Whoever is free, fits this lead and has the fewest open leads
            </small>
          </span>
        </button>
        <ul className={styles.reassignPeople} aria-label="People">
          {shown.map((rep) => {
            const has = rep.person_id === owner;
            return (
              <li key={rep.person_id}>
                <button
                  type="button"
                  className={styles.repPick}
                  aria-current={has || undefined}
                  disabled={has || moving !== null}
                  aria-busy={moving === rep.person_id || undefined}
                  onClick={() => void move(rep.person_id, rep.person_id)}
                >
                  <PersonAvatar
                    personId={rep.person_id}
                    name={rep.name}
                    photoUrl={rep.photo_url}
                    size={40}
                  />
                  <span>
                    <strong>{rep.name}</strong>
                    <small>
                      {has
                        ? "Has this lead now"
                        : `${rep.open_leads} open lead${rep.open_leads === 1 ? "" : "s"}${rep.available ? "" : " · away now"}`}
                    </small>
                  </span>
                  {has ? (
                    <Check
                      className={styles.repTick}
                      size={20}
                      aria-label="Current owner"
                    />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
        {shown.length ? null : (
          <p className={styles.hint}>Nobody by that name.</p>
        )}
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Sheet>
  );
}
