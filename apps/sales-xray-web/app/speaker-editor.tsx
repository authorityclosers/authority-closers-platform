"use client";

import { CircleUser, Headset, Search, Target, Users } from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { SpeakerAvatar } from "./speaker-avatar";
import { searchSpeakerIcons } from "./speaker-icons";
import {
  MAX_SPEAKER_NAME,
  voiceStyle,
  type SpeakerProfile,
  type SpeakerRole,
} from "./speaker-profiles";
import styles from "./speaker.module.css";

const ROLES = [
  { key: "you", label: "You", Icon: CircleUser },
  { key: "salesperson", label: "Salesperson", Icon: Headset },
  { key: "prospect", label: "Prospect", Icon: Target },
  { key: "other", label: "Other", Icon: Users },
] as const;

const GAP = 8;
const EDGE = 12;

/**
 * Names one speaker: a name, who they are (you, another salesperson, the
 * prospect or someone else) and an icon from the library. Enter saves, Escape or a click outside
 * cancels. It opens in the browser's top layer, pinned to its chip, so no
 * report text, sticky bar or audio player can cover it; it flips above the
 * chip or scrolls inside itself when the screen is short.
 */
export function SpeakerEditor({
  voice,
  anchor,
  label,
  share,
  sample,
  profile,
  youName,
  suggestedIcon,
  onSave,
  onClose,
}: {
  voice: number;
  /** The chip this editor belongs to. */
  anchor: HTMLElement | null;
  /** The speaker's number label, e.g. "Speaker 2". */
  label: string;
  /** Share of the talking, 0 to 100. */
  share: number;
  /** Something this speaker said, to help tell voices apart. */
  sample: string | null;
  profile: SpeakerProfile | null | undefined;
  youName: string | null;
  suggestedIcon: string;
  onSave: (profile: SpeakerProfile) => void;
  onClose: () => void;
}) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(profile?.name ?? "");
  const [role, setRole] = useState<SpeakerRole | null>(profile?.role ?? null);
  const [icon, setIcon] = useState<string | null>(profile?.icon ?? null);
  const [query, setQuery] = useState("");
  const icons = searchSpeakerIcons(query);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    try {
      element.showPopover?.();
    } catch {
      // Already open, or popovers unsupported: it still renders in place.
    }
    const place = () => {
      const target = anchor?.getBoundingClientRect();
      if (!target) return;
      const width = element.offsetWidth || 340;
      const height = element.scrollHeight;
      const below = window.innerHeight - target.bottom - GAP - EDGE;
      const above = target.top - GAP - EDGE;
      const flip = below < Math.min(height, 360) && above > below;
      const room = Math.max(180, flip ? above : below);
      const shown = Math.min(height, room);
      element.style.left = `${Math.min(
        Math.max(EDGE, target.left),
        window.innerWidth - width - EDGE,
      )}px`;
      element.style.top = `${flip ? target.top - GAP - shown : target.bottom + GAP}px`;
      element.style.maxHeight = `${room}px`;
      element.dataset.side = flip ? "top" : "bottom";
    };
    place();
    let frame = 0;
    const follow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(place);
    };
    window.addEventListener("resize", follow);
    document.addEventListener("scroll", follow, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", follow);
      document.removeEventListener("scroll", follow, true);
      try {
        element.hidePopover?.();
      } catch {
        // Already closed.
      }
    };
  }, [anchor]);

  useEffect(() => {
    nameInput.current?.focus({ preventScroll: true });
    nameInput.current?.select();
  }, []);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (!target || box.current?.contains(target)) return;
      // The chips toggle and switch the editor themselves.
      if (target.closest?.("[data-speaker-chips]")) return;
      onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  function pickRole(next: SpeakerRole) {
    setRole(next);
    if (next === "you" && !name.trim() && youName) setName(youName);
    if (next === "prospect" && !icon) setIcon(suggestedIcon);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onSave({
      name: name.trim(),
      role,
      icon: role === "you" ? null : icon,
    });
  }

  return (
    <div
      ref={box}
      className={styles.editor}
      style={voiceStyle(voice)}
      popover="manual"
      role="dialog"
      aria-label={`Edit ${label}`}
    >
      <form onSubmit={submit}>
        <div className={styles.head}>
          <SpeakerAvatar
            voice={voice}
            profile={{ name, role, icon }}
            youName={youName}
            size={44}
          />
          <div className={styles.nameBlock}>
            <label className={styles.hidden} htmlFor={`${id}-name`}>
              Speaker name
            </label>
            <input
              id={`${id}-name`}
              ref={nameInput}
              className={styles.name}
              value={name}
              maxLength={MAX_SPEAKER_NAME}
              placeholder={label}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
            />
            <small>
              {label} · {share}% of the talking
            </small>
          </div>
        </div>

        {sample ? <q className={styles.sample}>{sample}</q> : null}

        <div className={styles.roles} role="group" aria-label="Who is this?">
          {ROLES.map((option) => (
            <button
              key={option.key}
              type="button"
              aria-pressed={role === option.key}
              onClick={() => pickRole(option.key)}
            >
              <option.Icon size={14} aria-hidden="true" />
              {option.label}
            </button>
          ))}
        </div>

        {role === "you" ? (
          <p className={styles.note}>
            Shows your initials until your profile photo is saved to your
            account.
          </p>
        ) : (
          <div className={styles.library}>
            <div className={styles.libraryHead}>
              <span>Icon</span>
              <label className={styles.search}>
                <Search size={13} aria-hidden="true" />
                <input
                  value={query}
                  placeholder="Search icons"
                  aria-label="Search icons"
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            </div>
            <div className={styles.grid} role="group" aria-label="Icon">
              {icons.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  title={item.label}
                  aria-label={item.label}
                  aria-pressed={icon === item.key}
                  data-suggested={
                    item.key === suggestedIcon ? "true" : undefined
                  }
                  onClick={() =>
                    setIcon((current) =>
                      current === item.key ? null : item.key,
                    )
                  }
                >
                  <item.Icon size={16} aria-hidden="true" />
                </button>
              ))}
              {icons.length === 0 ? (
                <p className={styles.empty}>No icon matches “{query}”.</p>
              ) : null}
            </div>
          </div>
        )}

        <div className={styles.foot}>
          <small>Saved on this device for now</small>
          <button type="button" className={styles.cancel} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={styles.save}>
            Save
          </button>
        </div>
      </form>
    </div>
  );
}
