/**
 * The phone tab bar's own icons (owner, 15 Nov 2026; his ChatGPT pass,
 * navigation-icons.json): one family on a 24 px box, 1.8 stroke, round ends.
 * Home is filled when it is the page; Ask Dipak is a speech bubble holding a D.
 * Each sits beside its visible label, so each is hidden from screen readers.
 */

import type { ReactNode, SVGProps } from "react";

type GlyphProps = { size?: number } & Omit<SVGProps<SVGSVGElement>, "children">;

function Glyph({
  size = 24,
  children,
  ...rest
}: GlyphProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function HomeGlyph({
  selected = false,
  ...rest
}: GlyphProps & { selected?: boolean }) {
  return (
    <Glyph {...rest}>
      {selected ? (
        <path
          d="M3 10.5 12 3l9 7.5-2.5.1V21h-4.3v-6.2H9.8V21H5.5V10.6Z"
          fill="currentColor"
        />
      ) : (
        <>
          <path d="M3 10.5 12 3l9 7.5" />
          <path d="M5.5 9.5V21h4.3v-6.2h4.4V21h4.3V9.5" />
        </>
      )}
    </Glyph>
  );
}

export function LeadsGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M8 5H5a1.5 1.5 0 0 0-1.5 1.5v14H21v-14A1.5 1.5 0 0 0 19.5 5H16" />
      <path d="M8 3h8v4H8Z" />
      <path d="M6.5 16.5c.5-2.5 4.5-2.5 5 0" />
      <path d="M14.5 11h3.5" />
      <path d="M14.5 15h3.5" />
      <circle cx="9" cy="11.4" r="1.7" />
    </Glyph>
  );
}

export function AskDipakGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M7 3.5h10a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4H9l-5 3 1.1-4.1A4 4 0 0 1 3 14.5v-7a4 4 0 0 1 4-4Z" />
      <path d="M9 7.5h2.5a3.5 3.5 0 0 1 0 7H9v-7Z" />
    </Glyph>
  );
}

export function ReportsGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M4 3v18h17" />
      <path d="M8.5 16.5v-5" />
      <path d="M13 16.5V7" />
      <path d="M17.5 16.5v-8" />
    </Glyph>
  );
}

export function GrowthGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M3 18.5 9 12.5l4.5 4.5L21 7.5" />
      <path d="M14.5 7.5H21V14" />
    </Glyph>
  );
}
