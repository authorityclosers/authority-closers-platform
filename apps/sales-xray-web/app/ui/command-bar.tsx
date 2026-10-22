"use client";

/**
 * The command bar (slice 9 of the new map, owner, 22 Oct 2026: "Approved:
 * the new map"): one search for places, actions, leads and calls. Ctrl K or
 * ⌘K on a computer, the search button in a phone's top bar.
 *
 * It sits on the kit Sheet, so Back, Escape, a tap outside and a swipe down
 * close it: a glass sheet on phones, a centred glass panel on computers.
 * Arrow keys move through the results, Enter opens one. With no words typed
 * it lists the places and actions; typing filters them and, from two
 * letters, asks for matching leads (the page that opens the bar supplies the
 * search, so this file knows nothing about leads).
 */

import { CornerDownLeft, Search } from "lucide-react";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Sheet } from "./sheet";
import styles from "./command-bar.module.css";

export type Command = {
  id: string;
  group: string;
  label: string;
  /** One line under the label: a stage, a section's purpose. */
  hint?: string;
  /** Other words that should find it ("dashboard" finds Home). */
  keywords?: string;
  icon: ReactNode;
  run: () => void;
};

/** Words found as they are typed, in any case, at the start of a word first. */
export function matchCommands(
  commands: readonly Command[],
  text: string,
): Command[] {
  const words = text.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [...commands];
  const scored = commands.flatMap((command) => {
    const haystack =
      `${command.label} ${command.hint ?? ""} ${command.keywords ?? ""}`.toLocaleLowerCase();
    if (!words.every((word) => haystack.includes(word))) return [];
    const label = command.label.toLocaleLowerCase();
    const score = label.startsWith(words[0])
      ? 0
      : label.includes(` ${words[0]}`)
        ? 1
        : 2;
    return [{ command, score }];
  });
  return scored.sort((a, b) => a.score - b.score).map(({ command }) => command);
}

export const COMMAND_SEARCH_DELAY_MS = 200;

export function CommandBar({
  open,
  onClose,
  commands,
  search,
  placeholder = "Search leads, calls and places",
}: {
  open: boolean;
  onClose: () => void;
  /** Places and actions this person can use, in the order to show them. */
  commands: readonly Command[];
  /**
   * Results for the words typed (leads; a "search calls for …" step), read
   * after a short pause; a failed read shows nothing.
   */
  search?: (text: string, signal: AbortSignal) => Promise<Command[]>;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [found, setFound] = useState<Command[]>([]);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  // Each opening starts empty, with the cursor in the box.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setText("");
      setFound([]);
      setActive(0);
    }
  }
  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() =>
      inputRef.current?.focus({ preventScroll: true }),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  const words = text.trim();
  useEffect(() => {
    if (!open || !search || words.length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      search(words, controller.signal).then(
        (results) => {
          if (!controller.signal.aborted) setFound(results);
        },
        () => {
          if (!controller.signal.aborted) setFound([]);
        },
      );
    }, COMMAND_SEARCH_DELAY_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, search, words]);

  const results = useMemo(
    () => [
      ...matchCommands(commands, words),
      ...(words.length >= 2 ? found : []),
    ],
    [commands, found, words],
  );
  const shown = Math.min(active, Math.max(results.length - 1, 0));

  const run = (command: Command) => {
    onClose();
    command.run();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!results.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((shown + step + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      run(results[shown]);
    }
  };

  const groups: { name: string; items: { command: Command; at: number }[] }[] =
    [];
  results.forEach((command, at) => {
    const group = groups.find((item) => item.name === command.group);
    if (group) group.items.push({ command, at });
    else groups.push({ name: command.group, items: [{ command, at }] });
  });
  const optionId = (at: number) => `${listId}-${at}`;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Search"
      hideTitle
      closeButton={false}
      wide="center"
    >
      <div className={styles.field} data-sheet-no-drag="">
        <Search size={18} className={styles.fieldIcon} aria-hidden="true" />
        <input
          ref={inputRef}
          type="search"
          className={styles.input}
          value={text}
          placeholder={placeholder}
          aria-label="Search"
          role="combobox"
          aria-expanded={results.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={results.length ? optionId(shown) : undefined}
          enterKeyHint="go"
          autoComplete="off"
          onChange={(event) => {
            setText(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        <kbd className={styles.esc} aria-hidden="true">
          Esc
        </kbd>
      </div>
      <div
        id={listId}
        role="listbox"
        aria-label="Results"
        className={styles.results}
        data-sheet-no-drag=""
      >
        {groups.map((group) => (
          <div key={group.name} role="group" aria-label={group.name}>
            <div className={styles.group} aria-hidden="true">
              {group.name}
            </div>
            {group.items.map(({ command, at }) => (
              <div
                key={command.id}
                id={optionId(at)}
                role="option"
                aria-selected={at === shown}
                className={styles.option}
                onPointerMove={() => {
                  if (at !== shown) setActive(at);
                }}
                onClick={() => run(command)}
              >
                <span className={styles.icon} aria-hidden="true">
                  {command.icon}
                </span>
                <span className={styles.words}>
                  <span className={styles.label}>{command.label}</span>
                  {command.hint ? (
                    <span className={styles.hint}>{command.hint}</span>
                  ) : null}
                </span>
                {at === shown ? (
                  <CornerDownLeft
                    size={15}
                    className={styles.enter}
                    aria-hidden="true"
                  />
                ) : null}
              </div>
            ))}
          </div>
        ))}
        {words && !results.length ? (
          <p className={styles.none}>Nothing matches “{words}”.</p>
        ) : null}
      </div>
    </Sheet>
  );
}
