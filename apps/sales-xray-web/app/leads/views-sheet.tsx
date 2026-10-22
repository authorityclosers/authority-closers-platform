"use client";

/**
 * Leads → Views: the stage, pipeline, whose leads and search in use, saved under a name,
 * and every saved view one tap away (the ease-of-use wave, 22 Oct 2026). The chip sits
 * on the list and names the view in use; the sheet lists the views and saves this one.
 */

import { Bookmark, BookmarkCheck, Trash2 } from "lucide-react";
import { useState } from "react";

import { notify } from "../notice-center";
import { ActionList, ActionRow, Badge, Button, Field } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  findView,
  NAME_LIMIT,
  useSavedViews,
  VIEWS_LIMIT,
  withoutView,
  withView,
  type SavedView,
  type ViewSpec,
} from "./saved-views";
import styles from "./leads.module.css";

const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

export function ViewsChip({
  owner,
  current,
  describe,
  onApply,
}: {
  /** Whose views: "person:tenant". */
  owner: string;
  /** What the list shows now. */
  current: ViewSpec;
  /** A view in words: "Open · Mine · “pune”". */
  describe: (spec: ViewSpec) => string;
  onApply: (view: SavedView) => void;
}) {
  const [views, save] = useSavedViews(owner);
  // A fresh sheet each time, so its name field starts from the view in use.
  const [sheet, setSheet] = useState<{ round: number; open: boolean } | null>(
    null,
  );
  const active = findView(views, current);
  const close = () => setSheet((value) => value && { ...value, open: false });
  return (
    <>
      <button
        type="button"
        className={`${styles.statusChip} ${styles.viewChip}`}
        data-view={active ? "" : undefined}
        aria-haspopup="dialog"
        aria-label={active ? `Saved view: ${active.name}` : "Saved views"}
        onClick={() =>
          setSheet((value) => ({ round: (value?.round ?? 0) + 1, open: true }))
        }
      >
        {active ? (
          <BookmarkCheck size={14} aria-hidden="true" />
        ) : (
          <Bookmark size={14} aria-hidden="true" />
        )}
        <span className={styles.viewName}>
          {active ? active.name : "Views"}
        </span>
      </button>
      {sheet ? (
        <ViewsSheet
          key={sheet.round}
          open={sheet.open}
          onClose={close}
          views={views}
          active={active}
          current={current}
          describe={describe}
          onApply={(view) => {
            close();
            onApply(view);
          }}
          save={save}
        />
      ) : null}
    </>
  );
}

function ViewsSheet({
  open,
  onClose,
  views,
  active,
  current,
  describe,
  onApply,
  save,
}: {
  open: boolean;
  onClose: () => void;
  views: SavedView[];
  active: SavedView | null;
  current: ViewSpec;
  describe: (spec: ViewSpec) => string;
  onApply: (view: SavedView) => void;
  save: (views: SavedView[]) => boolean;
}) {
  const [name, setName] = useState(() =>
    describe(current).slice(0, NAME_LIMIT),
  );
  const full = views.length >= VIEWS_LIMIT;
  const replaces = views.find(
    (view) => view.name.toLowerCase() === name.trim().toLowerCase(),
  );
  const canSave = !active && !!name.trim() && (!full || !!replaces);

  const kept = (ok: boolean) => {
    if (!ok)
      notify({
        id: "saved-views",
        tone: "error",
        title: "This browser keeps nothing",
        message:
          "Views are kept on this device. Allow site data and try again.",
      });
    return ok;
  };

  const add = () => {
    if (!canSave) return;
    if (!kept(save(withView(views, current, name, newId())))) return;
    notify({
      id: "saved-views",
      tone: "success",
      title: `Saved “${name.trim().slice(0, NAME_LIMIT)}”`,
      message: "It's under Views on Leads.",
      timeout: 4000,
    });
    onClose();
  };

  const remove = (view: SavedView) => {
    if (!kept(save(withoutView(views, view.id)))) return;
    notify({
      id: "saved-views",
      tone: "info",
      title: `Removed “${view.name}”`,
      timeout: 6000,
      action: { label: "Undo", run: () => void save(views) },
    });
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Saved views"
      wide="center"
      footer={
        active ? undefined : (
          <Button
            variant="primary"
            disabled={!canSave}
            onClick={add}
            className={styles.viewSave}
          >
            {replaces ? `Update “${replaces.name}”` : "Save this view"}
          </Button>
        )
      }
    >
      <div className={styles.views}>
        {views.length ? (
          <ActionList label="Your saved views">
            {views.map((view) => (
              <ActionRow
                key={view.id}
                icon={
                  view.id === active?.id ? (
                    <BookmarkCheck size={20} />
                  ) : (
                    <Bookmark size={20} />
                  )
                }
                title={view.name}
                // A view named as it reads says it once.
                note={describe(view) === view.name ? undefined : describe(view)}
                end={
                  view.id === active?.id ? (
                    <Badge tone="good">In use</Badge>
                  ) : undefined
                }
                chevron={false}
                onClick={() => onApply(view)}
                trailing={
                  <button
                    type="button"
                    className={styles.viewRemove}
                    aria-label={`Remove ${view.name}`}
                    onClick={() => remove(view)}
                  >
                    <Trash2 size={18} aria-hidden="true" />
                  </button>
                }
              />
            ))}
          </ActionList>
        ) : (
          <p className={styles.hint}>
            Save the stage, pipeline, owner and search you use most. It comes
            back in one tap.
          </p>
        )}
        {active ? (
          <p className={styles.hint}>
            This is your saved view <strong>{active.name}</strong>. Change the
            stage, owner or search to save another.
          </p>
        ) : (
          <Field
            label="Name this view"
            hint={
              full && !replaces
                ? `You have ${VIEWS_LIMIT} views. Remove one to save this.`
                : name.trim() === describe(current)
                  ? "Keep it, or give it a name you'll know."
                  : `Saves ${describe(current)}`
            }
          >
            <input
              value={name}
              maxLength={NAME_LIMIT}
              enterKeyHint="done"
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") add();
              }}
            />
          </Field>
        )}
      </div>
    </Sheet>
  );
}
