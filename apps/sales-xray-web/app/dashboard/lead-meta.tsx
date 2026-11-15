"use client";

/**
 * A lead's where-from and what-happened as small icon chips (owner, 15 Nov
 * 2026: "File: … · Try again · did not pick · 1 try" read as a wall of words).
 * The source gets its kind's icon (a sheet for a file, a globe for the
 * website, a play button for YouTube, a megaphone for ads); each step of the
 * story gets its own (try again, didn't pick, tries).
 */

import {
  CircleDashed,
  FileSpreadsheet,
  FileText,
  Globe,
  Megaphone,
  PhoneIncoming,
  PhoneMissed,
  PlayCircle,
  Repeat,
  RotateCw,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import styles from "./lead-meta.module.css";

type Chip = { icon: LucideIcon; text: string; tone: string; title?: string };

function sourceChip(label: string): Chip {
  const [kind, ...rest] = label.split(":");
  const name = rest.join(":").trim();
  const k = kind.trim().toLowerCase();
  if (k === "file") {
    const sheet = /\.(xlsx?|csv)$/i.test(name);
    const short = name.replace(/\.(xlsx?|csv)$/i, "");
    return {
      icon: sheet ? FileSpreadsheet : FileText,
      text: short || "File",
      tone: sheet ? "sheet" : "file",
      title: name,
    };
  }
  if (k.startsWith("website") || k === "web")
    return { icon: Globe, text: name || "Website", tone: "web", title: label };
  if (k.startsWith("youtube"))
    return {
      icon: PlayCircle,
      text: name || "YouTube",
      tone: "yt",
      title: label,
    };
  if (
    k.includes("meta") ||
    k.includes("facebook") ||
    k.includes("instagram") ||
    k.includes("ads")
  )
    return {
      icon: Megaphone,
      text: name || kind.trim(),
      tone: "ads",
      title: label,
    };
  if (k.includes("call"))
    return { icon: PhoneIncoming, text: label, tone: "web" };
  if (k.includes("referr") || k.includes("manual"))
    return {
      icon: UserPlus,
      text: name || kind.trim(),
      tone: "web",
      title: label,
    };
  return { icon: Globe, text: label, tone: "web" };
}

function storyChip(part: string): Chip {
  const p = part.trim();
  const l = p.toLowerCase();
  if (l.includes("try again"))
    return { icon: RotateCw, text: "Try again", tone: "warn" };
  if (
    l.includes("did not pick") ||
    l.includes("didn't pick") ||
    l.includes("not connected") ||
    l.includes("missed")
  )
    return {
      icon: PhoneMissed,
      text: p.replace(/^./, (c) => c.toUpperCase()),
      tone: "bad",
    };
  if (/^\d+\s+tr(y|ies)$/.test(l))
    return { icon: Repeat, text: p, tone: "quiet" };
  if (l === "new lead")
    return { icon: Sparkles, text: "New lead", tone: "good" };
  if (l === "unworked")
    return { icon: CircleDashed, text: "Not called yet", tone: "quiet" };
  return { icon: CircleDashed, text: p, tone: "quiet" };
}

/** "Website: /programme" and "Try again · did not pick · 1 try" as chips. */
export function LeadMeta({
  source,
  why,
  className,
}: {
  source: string | null | undefined;
  why: string | null | undefined;
  className?: string;
}) {
  const chips: Chip[] = [];
  if (source) chips.push(sourceChip(source));
  for (const part of (why ?? "").split("·"))
    if (part.trim()) chips.push(storyChip(part));
  if (!chips.length) return null;
  return (
    <ul className={className ? `${styles.meta} ${className}` : styles.meta}>
      {chips.map((chip, n) => {
        const Icon = chip.icon;
        return (
          <li
            key={`${chip.text}-${n}`}
            data-tone={chip.tone}
            title={chip.title}
            style={{ animationDelay: `${n * 50}ms` }}
          >
            <Icon size={14} strokeWidth={2.2} aria-hidden="true" />
            <span>{chip.text}</span>
          </li>
        );
      })}
    </ul>
  );
}
