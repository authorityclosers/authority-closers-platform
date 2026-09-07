import type { SVGProps } from "react";

function MarkFrame({ children, ...props }: SVGProps<SVGSVGElement>) {
  const hasAccessibleName = Boolean(
    props["aria-label"] || props["aria-labelledby"],
  );

  return (
    <svg
      aria-hidden={hasAccessibleName ? undefined : true}
      role={hasAccessibleName ? "img" : undefined}
      focusable="false"
      viewBox="0 0 512 512"
      fill="currentColor"
      {...props}
    >
      {children}
    </svg>
  );
}

/** Authority Closers company mark: the supplied Open A geometry. */
export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <MarkFrame {...props}>
      <polygon points="32.0,432.0 192.0,48.0 280.0,48.0 120.0,432.0" />
      <polygon points="308.0,112.0 440.0,432.0 144.0,432.0 184.0,328.0 296.0,328.0 260.0,224.0" />
    </MarkFrame>
  );
}

/** Closers Academy identity; choosing this artwork does not select a tenant. */
export function AcademyMark(props: SVGProps<SVGSVGElement>) {
  return (
    <MarkFrame {...props}>
      <polygon points="48.0,104.0 232.0,176.0 232.0,408.0 48.0,336.0" />
      <polygon points="272.0,176.0 456.0,104.0 456.0,336.0 272.0,408.0" />
      <polygon points="112.0,432.0 392.0,432.0 392.0,480.0 112.0,480.0" />
    </MarkFrame>
  );
}

/** Cohorva's provisional platform identity, independent of academy artwork. */
export function PlatformMark(props: SVGProps<SVGSVGElement>) {
  return (
    <MarkFrame {...props}>
      <polygon points="72.0,80.0 224.0,80.0 224.0,176.0 168.0,176.0 168.0,352.0 72.0,352.0" />
      <polygon points="256.0,80.0 432.0,80.0 432.0,352.0 336.0,352.0 336.0,176.0 256.0,176.0" />
      <polygon points="168.0,384.0 336.0,384.0 336.0,448.0 168.0,448.0" />
    </MarkFrame>
  );
}
