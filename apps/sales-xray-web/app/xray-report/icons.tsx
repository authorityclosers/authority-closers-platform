import type { SVGProps } from "react";

/** Line marks the doc uses that lucide has no match for. */
type Props = SVGProps<SVGSVGElement>;

const line = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

/** A money bag with a rupee sign (Deal Value). */
export function MoneyBag(props: Props) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="M9 3.5h6l-1.6 3h-2.8z"
        fill="currentColor"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <path
        d="M10.2 6.6C6.4 8.6 4 12.2 4 15.6 4 19 6.6 21 12 21s8-2 8-5.4c0-3.4-2.4-7-6.2-9z"
        fill="currentColor"
      />
      <path
        d="M9.6 11.4h4.8M9.6 13.3h4.8M11 11.4c1.6 0 2.6.7 2.6 1.9s-1 1.9-2.6 1.9h-1.1l3.3 3"
        fill="none"
        stroke="var(--xr-card, #fff)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.4"
      />
    </svg>
  );
}

/** A target with an arrow in its centre (Deal Outcome, Final Call Outcome). */
export function TargetArrow(props: Props) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path {...line} d="M20.2 9.4A8.5 8.5 0 1 1 14.6 3.8" />
      <path {...line} d="M16.3 11.2a4.4 4.4 0 1 1-3.5-3.5" />
      <path {...line} d="M12 12l7.2-7.2" />
      <path {...line} d="M16.4 4.6l.4 2.6 2.6.4 2-2-2.6-.4-.4-2.6z" />
    </svg>
  );
}

/** A heavy opening quote mark (Evidence from the Call). */
export function QuoteMark(props: Props) {
  return (
    <svg viewBox="0 0 34 28" aria-hidden="true" {...props}>
      <path
        fill="currentColor"
        d="M7.4 27.2c-4 0-6.6-3.1-6.6-7.4C.8 11.6 6.3 4 14.4.8l1.7 3C11 6.3 8.5 9.8 8 13.4c3.6-.2 6.4 2.6 6.4 6.6 0 4.1-2.9 7.2-7 7.2zm17.7 0c-4 0-6.6-3.1-6.6-7.4C18.5 11.6 24 4 32.1.8l1.7 3c-5.1 2.5-7.6 6-8.1 9.6 3.6-.2 6.4 2.6 6.4 6.6 0 4.1-2.9 7.2-7 7.2z"
      />
    </svg>
  );
}

/** Status marks as image6 draws them: a filled tone disc with a cut-out sign. */
function Disc({ children, ...props }: Props) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" {...props}>
      <circle cx="10" cy="10" r="9" fill="currentColor" />
      <g
        fill="none"
        stroke="var(--xr-card, #fff)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      >
        {children}
      </g>
    </svg>
  );
}

export function StatusCheck(props: Props) {
  return (
    <Disc {...props}>
      <path d="M6 10.4l2.6 2.6L14 7.6" />
    </Disc>
  );
}

export function StatusMinus(props: Props) {
  return (
    <Disc {...props}>
      <path d="M6 10h8" />
    </Disc>
  );
}

export function StatusQuestion(props: Props) {
  return (
    <Disc {...props}>
      <path d="M7.7 7.6a2.4 2.4 0 1 1 3.3 2.2c-.6.3-1 .8-1 1.5v.3" />
      <path d="M10 14.4h.01" strokeWidth="2.4" />
    </Disc>
  );
}

export function StatusGauge(props: Props) {
  return (
    <Disc {...props}>
      <path d="M6 12.5a4 4 0 0 1 8 0" />
      <path d="M10 12.5l2-3" />
    </Disc>
  );
}

/** A filled warning triangle with a cut-out mark (Needs improvement). */
export function StatusAlert(props: Props) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" {...props}>
      <path
        d="M8.3 2.6a2 2 0 0 1 3.4 0l7 12.2a2 2 0 0 1-1.7 3H3a2 2 0 0 1-1.7-3z"
        fill="currentColor"
      />
      <path
        d="M10 7.2v4.4M10 14.6h.01"
        fill="none"
        stroke="var(--xr-card, #fff)"
        strokeLinecap="round"
        strokeWidth="2"
      />
    </svg>
  );
}
