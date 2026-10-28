/** Reflex's geometric R, with a returning arc at the foot. */
export function ReflexMark({ size = 28 }: { size?: 20 | 28 | 40 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
    >
      <rect width="64" height="64" rx="17" fill="var(--sx-accent)" />
      <path
        d="M20 47V17H33C45 17 45 34 33 34H20M32 34L40 45Q44 51 50 45"
        stroke="var(--lx-film-text)"
        strokeWidth="7"
        strokeLinejoin="round"
      />
    </svg>
  );
}
