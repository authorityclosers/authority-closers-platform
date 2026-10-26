"use client";

/**
 * Pulse's own app tile (Estate Autopilots' work app), for Sign in with Pulse,
 * Settings → Sign-in methods and Organisation → Connections → Pulse. Decorative:
 * every use names Pulse in text.
 */
import { useId } from "react";

export function PulseTile({ size = 36 }: { size?: number }) {
  const gradient = `sx-pulse-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      style={{ flex: "none", display: "block" }}
    >
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7c5cff" />
          <stop offset="1" stopColor="#4f37d0" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${gradient})`} />
      <path
        d="M8.9 13.2A9.9 9.9 0 0 1 18.8 23.1M8.9 6.2A16.9 16.9 0 0 1 25.8 23.1"
        fill="none"
        stroke="#ffffff"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="8.9" cy="23.1" r="4.4" fill="#ffffff" />
    </svg>
  );
}
