/**
 * Phone setup's pictures (owner, 20 Nov 2026, style C "See what to tap"):
 * a small drawing of the exact phone screen that comes next, with the button
 * to press ringed and a "Tap here" bubble. Drawn as SVG from the app's own
 * tokens, never a raster image, so light and dark come for free and the words
 * follow the phone (its maker's battery page, its recordings folder).
 *
 * Each picture is one image for a screen reader: its label says what the
 * phone will show and what to tap. Its text sizes are the drawing's own
 * units (fontSize on each <text>), scaled with the picture, not the app's
 * type scale.
 */

import type { ReactNode } from "react";

import art from "./walk-art.module.css";

export type ArtKind =
  | "alerts"
  | "alerts-settings"
  | "calls"
  | "calls-settings"
  | "recordings"
  | "recordings-private"
  | "battery"
  | "autostart"
  | "test-call";

const W = 260;
const H = 250;

/** Text that fits: long words are cut with an ellipsis, as a phone would. */
const fit = (text: string, max: number) =>
  text.length > max ? `${text.slice(0, max - 1)}…` : text;

/** The phone: body, screen, status bar and Android's three buttons. */
function Phone({ children }: { children: ReactNode }) {
  return (
    <>
      <rect
        className={art.body}
        x={34}
        y={4}
        width={180}
        height={242}
        rx={26}
      />
      <rect
        className={art.screen}
        x={40}
        y={10}
        width={168}
        height={230}
        rx={20}
      />
      <text className={art.status} fontSize={9} x={56} y={28}>
        9:30
      </text>
      <circle className={art.camera} cx={124} cy={24} r={3.5} />
      {/* Wi-Fi, signal and battery */}
      <path className={art.glyph} d="M168 22.5a8 8 0 0 1 10 0l-5 5.5z" />
      <path className={art.glyph} d="M182 28h7v-8z" />
      <rect className={art.glyph} x={192} y={20} width={5} height={8} rx={1} />
      {children}
      <path className={art.nav} d="M90 222l-6 4.5 6 4.5z" />
      <circle className={art.nav} cx={124} cy={226.5} r={4.5} />
      <rect className={art.nav} x={154} y={222} width={9} height={9} rx={1.5} />
    </>
  );
}

/** The ring round what to tap. */
function Ring(props: { x: number; y: number; width: number; height: number }) {
  return (
    <rect className={art.ring} {...props} rx={Math.min(props.height / 2, 14)} />
  );
}

/** "Tap here", pointing down-left (or up-left) at the ring. */
function Bubble({ x, y, up = false }: { x: number; y: number; up?: boolean }) {
  const tail = up
    ? `M${x + 10} ${y} l-6 -9 l16 9z`
    : `M${x + 10} ${y + 22} l-6 9 l16 -9z`;
  return (
    <g className={art.bubble}>
      <path className={art.bubbleFill} d={tail} />
      <rect
        className={art.bubbleFill}
        x={x}
        y={y}
        width={64}
        height={22}
        rx={11}
      />
      <text
        className={art.bubbleText}
        fontSize={10}
        x={x + 32}
        y={y + 15}
        textAnchor="middle"
      >
        Tap here
      </text>
    </g>
  );
}

/** Android's own question: a dimmed screen, the card, Allow ringed. */
function Dialog({
  y,
  lines,
  icon,
  compact = false,
  bubble = true,
}: {
  y: number;
  lines: readonly string[];
  icon: ReactNode;
  compact?: boolean;
  bubble?: boolean;
}) {
  const h = compact ? 90 : 122;
  const textY = y + (compact ? 34 : 46);
  const allowY = y + (compact ? 52 : 70);
  const button = compact ? 16 : 20;
  return (
    <g>
      <rect className={art.card} x={50} y={y} width={148} height={h} rx={14} />
      <g transform={`translate(124 ${y + (compact ? 15 : 22)})`}>{icon}</g>
      {lines.map((line, at) => (
        <text
          key={line}
          className={compact ? art.dialogSmall : art.dialogText}
          fontSize={compact ? 7.6 : 9.5}
          x={124}
          y={textY + at * (compact ? 9.5 : 12.5)}
          textAnchor="middle"
        >
          {line}
        </text>
      ))}
      <rect
        className={art.allow}
        x={60}
        y={allowY}
        width={128}
        height={button}
        rx={button / 2}
      />
      <text
        className={art.allowText}
        fontSize={9}
        x={124}
        y={allowY + button / 2 + 3.5}
        textAnchor="middle"
      >
        Allow
      </text>
      <Ring x={55} y={allowY - 4} width={138} height={button + 8} />
      <text
        className={art.quiet}
        fontSize={8}
        x={124}
        y={allowY + button + (compact ? 13 : 16)}
        textAnchor="middle"
      >
        Don&apos;t allow
      </text>
      {bubble ? <Bubble x={176} y={allowY - 34} /> : null}
    </g>
  );
}

const Bell = (
  <path
    className={art.iconLine}
    d="M-6 4h12l-2-3v-5a4 4 0 0 0-8 0v5zM-2 6.5a2 2 0 0 0 4 0"
  />
);
const Handset = (
  <path
    className={art.iconLine}
    d="M-6-5c0 7 4 11 11 11l1.5-3-3.5-1.5-1.5 1.5c-2-1-3.5-2.5-4.5-4.5l1.5-1.5-1.5-3.5z"
  />
);
const List = <path className={art.iconLine} d="M-5-4h10M-5 0h10M-5 4h10" />;
const Person = (
  <path
    className={art.iconLine}
    d="M0-1a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM-6 6a6 6 0 0 1 12 0"
  />
);

/** A settings page: its title under a back arrow. */
function Header({ title }: { title: string }) {
  return (
    <>
      <path className={art.iconLine} d="M58 46h-8m4-4-4 4 4 4" />
      <text className={art.header} fontSize={10.5} x={66} y={50}>
        {fit(title, 24)}
      </text>
    </>
  );
}

/** A switch, on. */
function Toggle({ x, y }: { x: number; y: number }) {
  return (
    <>
      <rect className={art.toggle} x={x} y={y} width={26} height={14} rx={7} />
      <circle className={art.knob} cx={x + 19} cy={y + 7} r={5} />
    </>
  );
}

/** Placeholder rows: the rest of the page, out of focus. */
function Rows({ from, count }: { from: number; count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, at) => (
        <g key={at}>
          <circle className={art.well} cx={60} cy={from + at * 22 + 6} r={6} />
          <rect
            className={art.well}
            x={72}
            y={from + at * 22 + 2}
            width={at % 2 ? 80 : 108}
            height={8}
            rx={4}
          />
        </g>
      ))}
    </>
  );
}

export type ArtProps = Readonly<{
  kind: ArtKind;
  /** The calls screen: Android's questions, in order (one or two shown). */
  questions?: readonly string[];
  /** The recordings folder, at most three deep. */
  path?: readonly string[];
  /** The battery page's title and the option to choose. */
  page?: string;
  choose?: string;
  /** The battery page also lists Autostart (this maker needs it). */
  autostart?: string;
  /** The maker's other battery choices, to choose against. */
  others?: readonly string[];
}>;

/** What a screen reader hears for each picture. */
export function artLabel(props: ArtProps): string {
  switch (props.kind) {
    case "alerts":
      return "Your phone asks: Allow Sales X-Ray to send you notifications? Tap Allow.";
    case "alerts-settings":
      return "Sales X-Ray's notification settings: switch on All Sales X-Ray notifications.";
    case "calls":
      return `Your phone asks: ${(props.questions ?? []).join(" Then: ")} Tap Allow each time.`;
    case "calls-settings":
      return "Sales X-Ray's app settings, Permissions, Phone: tap Allow.";
    case "recordings":
      return `The folder picker opens at ${(props.path ?? []).join(", ")}. Tap Use this folder.`;
    case "recordings-private":
      return "Your Phone app keeps its call recordings to itself.";
    case "battery":
      return `${props.page ?? "Battery"}: choose ${props.choose ?? "Unrestricted"}.${props.autostart ? ` Then ${props.autostart}: On.` : ""}`;
    case "autostart":
      return `${props.page ?? "Autostart"}: switch Sales X-Ray on.`;
    case "test-call":
      return "Your test call appears with Recording found.";
  }
}

function Picture(props: ArtProps): ReactNode {
  switch (props.kind) {
    case "alerts":
      return (
        <Phone>
          <rect
            className={art.dim}
            x={40}
            y={10}
            width={168}
            height={230}
            rx={20}
          />
          <Dialog
            y={62}
            icon={Bell}
            lines={["Allow Sales X-Ray to", "send you notifications?"]}
          />
        </Phone>
      );
    case "alerts-settings":
      return (
        <Phone>
          <Header title="Notifications" />
          <rect
            className={art.card}
            x={48}
            y={64}
            width={152}
            height={42}
            rx={10}
          />
          <text className={art.rowStrong} fontSize={9.5} x={58} y={82}>
            All Sales X-Ray
          </text>
          <text className={art.rowStrong} fontSize={9.5} x={58} y={94}>
            notifications
          </text>
          <Toggle x={162} y={78} />
          <Ring x={156} y={72} width={38} height={26} />
          <Bubble x={170} y={110} up />
          <Rows from={146} count={3} />
        </Phone>
      );
    case "calls": {
      const [first = "", second] = props.questions ?? [];
      const lines = (question: string) => {
        const words = question.split(" ");
        const half = Math.ceil(words.length / 2);
        return [words.slice(0, half).join(" "), words.slice(half).join(" ")];
      };
      if (!second)
        return (
          <Phone>
            <rect
              className={art.dim}
              x={40}
              y={10}
              width={168}
              height={230}
              rx={20}
            />
            <Dialog y={62} icon={Handset} lines={lines(first)} />
          </Phone>
        );
      return (
        <Phone>
          <rect
            className={art.dim}
            x={40}
            y={10}
            width={168}
            height={230}
            rx={20}
          />
          <Dialog y={34} icon={Handset} lines={lines(first)} compact />
          <Dialog
            y={128}
            icon={/contact/i.test(second) ? Person : List}
            lines={lines(second)}
            compact
            bubble={false}
          />
          <circle className={art.badge} cx={30} cy={48} r={10} />
          <text
            className={art.badgeText}
            fontSize={11}
            x={30}
            y={52}
            textAnchor="middle"
          >
            1
          </text>
          <circle className={art.badge} cx={30} cy={142} r={10} />
          <text
            className={art.badgeText}
            fontSize={11}
            x={30}
            y={146}
            textAnchor="middle"
          >
            2
          </text>
        </Phone>
      );
    }
    case "calls-settings":
      return (
        <Phone>
          <Header title="Phone permission" />
          {["Allow", "Ask every time", "Don't allow"].map((label, at) => (
            <g key={label}>
              <circle
                className={at === 0 ? art.radioOn : art.radio}
                cx={60}
                cy={78 + at * 28}
                r={6}
              />
              <text className={art.row} fontSize={9} x={74} y={82 + at * 28}>
                {label}
              </text>
            </g>
          ))}
          <Ring x={48} y={66} width={150} height={24} />
          <Bubble x={150} y={96} up />
          <Rows from={170} count={2} />
        </Phone>
      );
    case "recordings": {
      const path = props.path?.length ? props.path : ["Recordings"];
      const last = path.at(-1) ?? "";
      const crumbs = path.slice(0, -1).map((part) => fit(part, 16));
      return (
        <Phone>
          <path className={art.iconLine} d="M58 46h-8m4-4-4 4 4 4" />
          <text className={art.crumbs} fontSize={7} x={64} y={49}>
            {crumbs.map((part) => `${part} › `).join("")}
            <tspan className={art.crumbLast}>{fit(last, 14)}</tspan>
          </text>
          <rect
            className={art.picked}
            x={46}
            y={62}
            width={156}
            height={28}
            rx={8}
          />
          <path
            className={art.folder}
            d="M56 70h7l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5h-16.5a1.5 1.5 0 0 1-1.5-1.5v-10.5a1.5 1.5 0 0 1 1.5-1.5z"
          />
          <text className={art.rowStrong} fontSize={9.5} x={84} y={80}>
            {fit(last, 16)}
          </text>
          <Rows from={104} count={2} />
          <rect
            className={art.use}
            x={56}
            y={184}
            width={136}
            height={24}
            rx={12}
          />
          <text
            className={art.useText}
            fontSize={9.5}
            x={124}
            y={200}
            textAnchor="middle"
          >
            Use this folder
          </text>
          <Ring x={51} y={179} width={146} height={34} />
          <Bubble x={168} y={142} />
        </Phone>
      );
    }
    case "recordings-private":
      return (
        <Phone>
          <circle className={art.callsSoft} cx={124} cy={100} r={30} />
          <g transform="translate(124 100) scale(2.2)">{Handset}</g>
          <rect
            className={art.lock}
            x={138}
            y={114}
            width={16}
            height={13}
            rx={3}
          />
          <path className={art.lockLoop} d="M141 114v-3a5 5 0 0 1 10 0v3" />
          <text
            className={art.rowStrong}
            fontSize={9.5}
            x={124}
            y={160}
            textAnchor="middle"
          >
            Recordings stay
          </text>
          <text
            className={art.rowStrong}
            fontSize={9.5}
            x={124}
            y={173}
            textAnchor="middle"
          >
            in the Phone app
          </text>
        </Phone>
      );
    case "battery": {
      const options = [props.choose ?? "Unrestricted", ...(props.others ?? [])];
      return (
        <Phone>
          <Header title={props.page ?? "Battery"} />
          <rect
            className={art.card}
            x={46}
            y={62}
            width={156}
            height={86}
            rx={10}
          />
          {options.slice(0, 3).map((label, at) => (
            <g key={label}>
              <circle
                className={at === 0 ? art.radioOn : art.radio}
                cx={58}
                cy={76 + at * 26}
                r={5.5}
              />
              <text
                className={at === 0 ? art.rowStrong : art.row}
                fontSize={at === 0 ? 9.5 : 9}
                x={70}
                y={80 + at * 26}
              >
                {fit(label, 22)}
              </text>
            </g>
          ))}
          <Ring x={44} y={64} width={160} height={24} />
          <Bubble x={168} y={36} />
          {props.autostart ? (
            <>
              <rect
                className={art.card}
                x={46}
                y={160}
                width={156}
                height={30}
                rx={10}
              />
              <text className={art.rowStrong} fontSize={9.5} x={58} y={179}>
                {fit(props.autostart, 18)}
              </text>
              <Toggle x={164} y={168} />
            </>
          ) : (
            <Rows from={166} count={2} />
          )}
        </Phone>
      );
    }
    case "autostart":
      return (
        <Phone>
          <Header title={props.page ?? "Autostart"} />
          <rect
            className={art.card}
            x={46}
            y={62}
            width={156}
            height={34}
            rx={10}
          />
          <circle className={art.appMark} cx={60} cy={79} r={7} />
          <text className={art.rowStrong} fontSize={9.5} x={74} y={83}>
            Sales X-Ray
          </text>
          <Toggle x={164} y={72} />
          <Ring x={158} y={66} width={38} height={26} />
          <Bubble x={168} y={102} up />
          <Rows from={140} count={3} />
        </Phone>
      );
    case "test-call":
      return (
        <Phone>
          <text className={art.header} fontSize={10.5} x={52} y={50}>
            Recents
          </text>
          <rect
            className={art.card}
            x={46}
            y={62}
            width={156}
            height={40}
            rx={10}
          />
          <circle className={art.done} cx={62} cy={82} r={8} />
          <path className={art.doneTick} d="M58 82l3 3 5-6" />
          <text className={art.rowStrong} fontSize={9.5} x={76} y={79}>
            Test call · 0:20
          </text>
          <text className={art.found} fontSize={8.5} x={76} y={92}>
            Recording found
          </text>
          <Ring x={42} y={58} width={164} height={48} />
          <Bubble x={168} y={32} />
          <Rows from={120} count={4} />
        </Phone>
      );
  }
}

/** One step's picture, sized to the screen. */
export function WalkArt(props: ArtProps) {
  return (
    <svg
      className={art.art}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={artLabel(props)}
      data-walk-art={props.kind}
    >
      <Picture {...props} />
    </svg>
  );
}

/** The consent's shield: no phone screen, the words are the point. */
export function ShieldArt() {
  return (
    <svg className={art.shield} viewBox="0 0 96 96" aria-hidden="true">
      <circle className={art.shieldBack} cx={48} cy={48} r={46} />
      <path
        className={art.shieldLine}
        d="M48 22l20 7v15c0 13-8.5 23-20 28-11.5-5-20-15-20-28v-15z"
      />
      <path className={art.shieldLine} d="M39 48l6.5 6.5 12-13" />
    </svg>
  );
}

/** All set: one big tick. */
export function DoneArt() {
  return (
    <svg className={art.tick} viewBox="0 0 120 120" aria-hidden="true">
      <circle className={art.tickBack} cx={60} cy={60} r={56} />
      <path className={art.tickLine} d="M36 62l16 16 32-34" />
    </svg>
  );
}
