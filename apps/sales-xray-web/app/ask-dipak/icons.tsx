/**
 * The line icons of Dipak's sample (24 px grid, 1.8 stroke), drawn with the
 * text colour so they follow the light and dark themes.
 */
import type { ReactNode } from "react";

const ART: Readonly<Record<string, ReactNode>> = {
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  bookmark: <path d="M5 3h14v18l-7-4-7 4z" />,
  right: <path d="m9 18 6-6-6-6" />,
  left: <path d="m15 18-6-6 6-6" />,
  check: <path d="m4 12 5 5L20 6" />,
  message: (
    <>
      <path d="M20 11v6a2 2 0 0 1-2 2H8l-4 3V6a2 2 0 0 1 2-2h9" />
      <path d="M10 9h9M10 13h7" />
    </>
  ),
  find: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="m15 15 6 6M7 10l2 2 4-4" />
    </>
  ),
  tag: (
    <>
      <path d="M4 4h9l8 8-9 9-8-8z" />
      <circle cx="9" cy="9" r="1.5" />
    </>
  ),
  target: (
    <>
      <circle cx="11" cy="12" r="8" />
      <circle cx="11" cy="12" r="3" />
      <path d="m14 9 7-7m-5 0h5v5" />
    </>
  ),
  brain: (
    <path d="M12 4c-2-4-8-1-8 3-3 2-3 6 0 8-1 4 3 7 8 4 5 3 9 0 8-4 3-2 3-6 0-8 0-4-6-7-8-3zM12 4v15M5 9l4 1M19 9l-4 1" />
  ),
  handshake: (
    <path d="m2 10 5-5 4 2 2-1 4 0 5 5-5 5-2-2-2 2-2-2-2 1-7-5zM8 10l4 3" />
  ),
  layers: <path d="m12 2 9 5-9 5-9-5zM3 12l9 5 9-5M3 17l9 5 9-5" />,
  clipboard: (
    <>
      <rect x="5" y="4" width="14" height="18" rx="2" />
      <path d="M9 4V2h6v2M9 11h6M9 16h6" />
    </>
  ),
  presentation: <path d="M3 4h18v13H3zM12 17v5M8 22h8M7 14l4-4 3 2 4-5" />,
  growth: <path d="m3 17 6-6 4 3 8-9M15 5h6v6" />,
};

export function AskIcon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      data-icon={name}
    >
      {ART[name] ?? ART.layers}
    </svg>
  );
}

export const hasIcon = (name: string): boolean =>
  Object.prototype.hasOwnProperty.call(ART, name);
