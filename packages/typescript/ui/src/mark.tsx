import type { SVGProps } from "react";

export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" viewBox="0 0 48 48" fill="none" {...props}>
      <path
        d="M1 38 14.8 7h7.4L36 38h-8.2l-2.5-6.2H11.7L9.1 38H1Z"
        fill="currentColor"
      />
      <path
        d="M14.7 24.5h7.6L18.5 15l-3.8 9.5Z"
        fill="var(--ac-mark-cut, #10120f)"
      />
      <path
        d="M47 13.5C44.5 9.8 40.8 8 36.3 8 28.4 8 22 15 22 23.5S28.4 39 36.3 39c4.5 0 8.4-1.9 10.7-5.4l-5.2-4c-1.3 1.9-3.1 2.8-5.4 2.8-4.4 0-7.6-3.7-7.6-8.9 0-5.3 3.2-9 7.6-9 2.2 0 4 .9 5.4 2.9l5.2-3.9Z"
        fill="currentColor"
      />
    </svg>
  );
}
