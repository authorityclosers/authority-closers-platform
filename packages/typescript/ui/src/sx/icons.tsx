/**
 * The kit's few icons, drawn inline with Lucide's paths (ISC), so the shared
 * package needs no icon library. Same props as Lucide's: size, strokeWidth.
 */
import type { ComponentType, ReactNode, SVGProps } from "react";

export type IconProps = Omit<SVGProps<SVGSVGElement>, "ref"> & {
  size?: number | string;
  strokeWidth?: number | string;
};

/** Any icon component the kit accepts (Lucide's included). */
export type IconComponent = ComponentType<IconProps>;

function icon(paths: ReactNode) {
  return function Icon({ size = 24, strokeWidth = 2, ...rest }: IconProps) {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        {...rest}
      >
        {paths}
      </svg>
    );
  };
}

export const ArrowUpRight = icon(
  <>
    <path d="M7 7h10v10" />
    <path d="M7 17 17 7" />
  </>,
);
export const ArrowDownRight = icon(
  <>
    <path d="m7 7 10 10" />
    <path d="M17 7v10H7" />
  </>,
);
export const ChevronLeft = icon(<path d="m15 18-6-6 6-6" />);
export const ChevronRight = icon(<path d="m9 18 6-6-6-6" />);
export const Info = icon(
  <>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 16v-4" />
    <path d="M12 8h.01" />
  </>,
);
export const Minus = icon(<path d="M5 12h14" />);
export const Pencil = icon(
  <>
    <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />
    <path d="m15 5 4 4" />
  </>,
);

/** Additional design-system v2 icons; exact Lucide 1.37.0 paths (ISC). */
export const X = icon(
  <>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </>,
);
export const BellRing = icon(
  <>
    <path d="M10.268 21a2 2 0 0 0 3.464 0" />
    <path d="M22 8c0-2.3-.8-4.3-2-6" />
    <path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326" />
    <path d="M4 2C2.8 3.7 2 5.7 2 8" />
  </>,
);
export const Siren = icon(
  <>
    <path d="M7 18v-6a5 5 0 1 1 10 0v6" />
    <path d="M5 21a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2z" />
    <path d="M21 12h1" />
    <path d="M18.5 4.5 18 5" />
    <path d="M2 12h1" />
    <path d="M12 2v1" />
    <path d="m4.929 4.929.707.707" />
    <path d="M12 12v6" />
  </>,
);
