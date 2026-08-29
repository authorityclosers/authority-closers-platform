import type { SVGProps } from "react";

export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" viewBox="0 0 48 48" fill="none" {...props}>
      <path
        d="M8 35.5 20.4 8h7.2L40 35.5h-8.1l-2.2-5.6H18.2L16 35.5H8Z"
        fill="currentColor"
      />
      <path
        d="M20.7 23.4h6.6L24 14.8l-3.3 8.6Z"
        fill="var(--ac-mark-cut, #10120f)"
      />
    </svg>
  );
}
