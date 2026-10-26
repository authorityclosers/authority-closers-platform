"use client";

/**
 * Choose your character (owner #32, 26 Oct 2026): one of the illustrated
 * animal faces as your photo, wherever your team sees it. The server keeps
 * the choice as the photo itself (option B, no migration); removing the photo
 * goes back to the character picked from your person id. A character that
 * would replace a photo asks first.
 */

import { Check } from "lucide-react";
import { useState } from "react";

import { notify } from "../notice-center";
import { useCharacters, type Character } from "../people/characters";
import { haptic } from "../ui/haptics";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./character-sheet.module.css";
import { chooseCharacter, ProfileDetailsError } from "./profile-details-client";

export function CharacterSheet({
  open,
  current,
  replacesPhoto,
  onClose,
  onChosen,
}: {
  open: boolean;
  /** The character shown now: the chosen one, or the default without a photo. */
  current: string | null;
  /** A photo is there now (an upload or Google's): choosing replaces it. */
  replacesPhoto: boolean;
  onClose: () => void;
  onChosen: (character: Character) => void;
}) {
  const characters = useCharacters(open);
  const [asking, setAsking] = useState<Character | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const close = () => {
    setAsking(null);
    onClose();
  };
  const save = async (character: Character) => {
    haptic("tap");
    setSaving(character.key);
    try {
      await chooseCharacter(character.key);
      haptic("success");
      setAsking(null);
      onChosen(character);
    } catch (error) {
      haptic("error");
      const status = error instanceof ProfileDetailsError ? error.status : 0;
      notify({
        id: "profile-character",
        tone: "error",
        title: "Character not saved",
        message:
          status === 409
            ? "Characters aren't ready yet. Try again later."
            : status === 401
              ? "Your session ended. Sign in again to choose."
              : "Try again in a moment.",
      });
    } finally {
      setSaving(null);
    }
  };
  const pick = (character: Character) => {
    if (saving || character.key === current) return;
    if (replacesPhoto) setAsking(character);
    else void save(character);
  };

  return (
    <Sheet
      open={open}
      onClose={close}
      title="Choose your character"
      description="Your team sees it wherever your photo would show."
      footer={
        asking ? (
          <div className={styles.confirm} role="group" aria-label="Confirm">
            <p>This replaces your current photo.</p>
            <div className={styles.confirmActions}>
              <Button onClick={() => setAsking(null)}>Keep my photo</Button>
              <Button
                variant="primary"
                disabled={saving !== null}
                onClick={() => void save(asking)}
              >
                {saving ? "Saving…" : `Use the ${asking.label.toLowerCase()}`}
              </Button>
            </div>
          </div>
        ) : undefined
      }
    >
      {characters.length ? (
        <ul className={styles.grid} aria-label="Characters">
          {characters.map((character) => {
            const now = character.key === current;
            const chosen = now || character.key === asking?.key;
            return (
              <li key={character.key}>
                <button
                  type="button"
                  className={styles.choice}
                  aria-pressed={chosen}
                  aria-busy={saving === character.key || undefined}
                  disabled={saving !== null}
                  onClick={() => pick(character)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- Small, session-bound pictures, already sized. */}
                  <img src={character.url} alt="" width={64} height={64} />
                  <span>{character.label}</span>
                  {now ? (
                    <Check
                      className={styles.tick}
                      size={16}
                      strokeWidth={2.5}
                      aria-label="Shown now"
                    />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className={styles.waiting} aria-busy="true">
          Getting the characters…
        </p>
      )}
    </Sheet>
  );
}
