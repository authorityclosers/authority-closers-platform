import { useId } from "react";

/** Original lightweight SVG scenes; palette is inherited from the live academy theme. */
export function PracticeArt({ kind }: { kind: string }) {
  const id = useId();
  return (
    <svg
      viewBox="0 0 180 144"
      width="180"
      height="144"
      aria-hidden="true"
      focusable="false"
      data-practice-art={kind}
    >
      <defs>
        <linearGradient id={`${id}-face`} x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="var(--practice-ink, var(--theme-action))" />
          <stop
            offset="1"
            stopColor="var(--practice-depth, var(--theme-text))"
          />
        </linearGradient>
      </defs>
      <ellipse
        cx="90"
        cy="132"
        rx="58"
        ry="8"
        fill="var(--practice-ink, var(--theme-action))"
        opacity=".12"
      />
      <path
        d="m27 100 62-23 65 23v16l-65 23-62-23Z"
        fill="var(--practice-ink, var(--theme-action))"
        opacity=".22"
      />
      <path
        d="m27 100 62-23 65 23-65 24Z"
        fill="var(--practice-ink, var(--theme-action))"
        opacity=".15"
      />
      <g
        fill={`url(#${id}-face)`}
        stroke="var(--theme-action-text)"
        strokeWidth="3"
        strokeLinejoin="round"
        strokeLinecap="round"
      >
        {kind === "audio" ? (
          <>
            <path
              d="M52 70V55a38 38 0 0 1 76 0v15"
              fill="none"
              stroke={`url(#${id}-face)`}
              strokeWidth="13"
            />
            <rect
              x="40"
              y="60"
              width="25"
              height="43"
              rx="12"
              transform="rotate(-8 40 60)"
            />
            <rect
              x="118"
              y="58"
              width="25"
              height="43"
              rx="12"
              transform="rotate(8 118 58)"
            />
            <path
              d="M78 70v17m12-25v33m12-25v17"
              stroke="var(--practice-ink, var(--theme-action))"
              strokeWidth="5"
            />
          </>
        ) : kind === "branch" ? (
          <>
            <path d="M70 58h61a10 10 0 0 1 10 10v29a10 10 0 0 1-10 10h-7v13l-17-13H70a10 10 0 0 1-10-10V68a10 10 0 0 1 10-10Z" />
            <path d="M45 28h64a11 11 0 0 1 11 11v28a11 11 0 0 1-11 11H71L51 91V78h-6a11 11 0 0 1-11-11V39a11 11 0 0 1 11-11Z" />
            <path d="M53 47h45M53 60h28M92 89h27" fill="none" strokeWidth="5" />
          </>
        ) : kind === "match" ? (
          <>
            <rect
              x="35"
              y="26"
              width="53"
              height="66"
              rx="13"
              transform="rotate(-12 61 59)"
            />
            <rect
              x="91"
              y="46"
              width="53"
              height="66"
              rx="13"
              transform="rotate(12 117 79)"
            />
            <path
              d="m47 57 9 9 17-21m31 34 9 9 17-21"
              fill="none"
              strokeWidth="6"
            />
          </>
        ) : kind === "build" || kind === "order" ? (
          <>
            <path d="M36 79h33v33H36ZM74 55h33v57H74ZM112 28h33v84h-33Z" />
            <path
              d="m43 54 34-28 26 3 29-19m-12 0h12v12"
              fill="none"
              stroke="var(--practice-ink, var(--theme-action))"
              strokeWidth="5"
            />
            <path d="M46 96h12m26-17h13m25-27h13" fill="none" strokeWidth="4" />
          </>
        ) : kind === "gap" ? (
          <>
            <path d="M48 29h30v8a12 12 0 1 0 24 0v-8h30v30h-8a12 12 0 1 0 0 24h8v30h-30v-8a12 12 0 1 0-24 0v8H48V83h-8a12 12 0 1 1 0-24h8Z" />
            <path d="m69 72 12 12 28-31" fill="none" strokeWidth="6" />
          </>
        ) : (
          <>
            <circle cx="90" cy="65" r="47" />
            <circle cx="90" cy="65" r="36" fill="none" opacity=".6" />
            <path d="m109 37-10 39-29 17 10-39Z" />
            <path
              d="m90 25 0 5m0 70v5m-40-40h5m70 0h5"
              fill="none"
              strokeWidth="4"
            />
          </>
        )}
      </g>
      <g fill="var(--practice-ink, var(--theme-action))">
        <path d="m150 25 2 6 6 2-6 2-2 6-2-6-6-2 6-2Z" />
        <circle cx="27" cy="52" r="3" opacity=".5" />
        <circle cx="149" cy="76" r="2" opacity=".5" />
      </g>
    </svg>
  );
}
