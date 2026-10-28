"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart2,
  Bell,
  Calendar,
  ExternalLink,
  HelpCircle,
  Settings,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { Sheet } from "@ac/ui/kit";
import { tick } from "@ac/ui/kit/haptics";
import { SignOutControl } from "../components/sign-out-control";
import { initialsForDisplayName } from "../lib/profile-identity";
import { AccountContext, useAccountStore } from "./account-store";
import { activePlace, places, routeTitle, salesXrayForHost } from "./places";
import { ReflexMark } from "./reflex-mark";
import { RouteLoading } from "./route-loading";
import { ScreenTitleContext } from "./screen-title";
import { useGlide } from "./screen-transition";
import styles from "./reflex-shell.module.css";

function Avatar({ name, url }: { name: string; url: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <span className={styles.avatar}>
      {url && failed !== url ? (
        // Signed, self-scoped profile photo; keep the provider's delivery URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="" onError={() => setFailed(url)} />
      ) : (
        initialsForDisplayName(name)
      )}
    </span>
  );
}

// The host decides which Sales X-Ray address the Account sheet offers; it never changes in a tab.
const subscribeHost = () => () => {};
const clientHost = () => window.location.hostname;
const serverHost = () => "";

export function ReflexShell({
  children,
  practiceEnabled = false,
}: {
  children: ReactNode;
  practiceEnabled?: boolean;
}) {
  const pathname = usePathname() ?? "/home";
  const router = useRouter();
  const account = useAccountStore();
  const [open, setOpen] = useState(false);
  const hostname = useSyncExternalStore(subscribeHost, clientHost, serverHost);
  const [pageTitle, setPageTitle] = useState<string | null>(null);
  const [going, setGoing] = useState<{ from: string; to: string } | null>(null);
  const pressed = useRef<string | null>(null);
  const phone = useRef<HTMLElement>(null),
    rail = useRef<HTMLElement>(null);
  const standing = going?.from === pathname ? going.to : null;
  const current = activePlace(standing ?? pathname);
  const title = standing
    ? routeTitle(standing)
    : (pageTitle ?? routeTitle(pathname));
  useGlide(phone, current);
  useGlide(rail, current);
  // A finished move clears the stand-in and closes the Account sheet, during render (no effect).
  const [seenPath, setSeenPath] = useState(pathname);
  if (seenPath !== pathname) {
    setSeenPath(pathname);
    setGoing(null);
    setOpen(false);
  }
  useEffect(() => {
    if (!going) return;
    const timer = window.setTimeout(() => setGoing(null), 12000);
    return () => window.clearTimeout(timer);
  }, [going]);
  const availablePlaces = places.filter(
    (place) => place.href !== "/practice" || practiceEnabled,
  );
  const name = account.me?.display_name?.trim() || "Your account";
  const salesXray = salesXrayForHost(hostname);

  const accountButton = (
    <button
      type="button"
      className={styles.accountButton}
      aria-label="Open Account"
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={() => {
        tick();
        setOpen(true);
      }}
    >
      <Avatar name={name} url={account.avatarUrl} />
      <span className={styles.accountName}>{name}</span>
    </button>
  );
  function navigation(kind: "rail" | "tabs") {
    return (
      <nav
        ref={kind === "rail" ? rail : phone}
        className={kind === "rail" ? styles.places : styles.tabs}
        aria-label={kind === "rail" ? "Reflex places" : "Phone places"}
      >
        {availablePlaces.map(({ title, href, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            prefetch={false}
            className={styles.place}
            aria-current={current === href ? "page" : undefined}
            onPointerDown={(event) => {
              if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              tick();
              pressed.current = href;
              router.prefetch(href);
              if (href !== pathname) setGoing({ from: pathname, to: href });
            }}
            onPointerCancel={() => {
              pressed.current = null;
              setGoing(null);
            }}
            onPointerLeave={(event) => {
              if (event.pointerType === "mouse" && event.buttons === 1) {
                pressed.current = null;
                setGoing(null);
              }
            }}
            onNavigate={() => {
              if (pressed.current !== href) tick();
              pressed.current = null;
              if (href !== pathname) setGoing({ from: pathname, to: href });
            }}
          >
            {current === href ? (
              <span data-capsule className={styles.capsule} />
            ) : null}
            <Icon size={22} aria-hidden="true" />
            <span>{title}</span>
          </Link>
        ))}
      </nav>
    );
  }
  return (
    <AccountContext.Provider value={account}>
      <ScreenTitleContext.Provider value={setPageTitle}>
        <div className={`${styles.shell} site-frame--learner`}>
          <a className={styles.skip} href="#main-content">
            Skip to content
          </a>
          <aside className={styles.rail}>
            <Link
              className={styles.wordmark}
              href="/home"
              aria-label="Reflex home"
            >
              <ReflexMark size={40} />
              <span>
                Reflex<small>by Authority Closers</small>
              </span>
            </Link>
            {navigation("rail")}
            {accountButton}
          </aside>
          <header className={styles.topbar}>
            <h1>{title}</h1>
            {accountButton}
          </header>
          <div className={styles.content} aria-busy={!!standing}>
            {standing ? (
              <div className={styles.loading}>
                <RouteLoading path={standing} />
              </div>
            ) : null}
            <div hidden={!!standing}>{children}</div>
          </div>
          {navigation("tabs")}
        </div>
        <Sheet
          open={open}
          onClose={() => setOpen(false)}
          title="Account"
          className={styles.accountSheet}
        >
          <div className={styles.identity}>
            <Avatar name={name} url={account.avatarUrl} />
            <div>
              <strong>{name}</strong>
              <p>{account.me?.email}</p>
              {account.workspaceName ? <p>{account.workspaceName}</p> : null}
            </div>
          </div>
          <nav className={styles.accountRows} aria-label="Account">
            {[
              { title: "Progress", href: "/progress", icon: BarChart2 },
              { title: "Calendar", href: "/calendar", icon: Calendar },
              { title: "Notifications", href: "/notifications", icon: Bell },
              { title: "Settings", href: "/settings", icon: Settings },
            ].map(({ title, href, icon: Icon }) => (
              <Link key={href} href={href} onClick={() => setOpen(false)}>
                <Icon size={20} aria-hidden="true" />
                {title}
              </Link>
            ))}
            <a href="mailto:admin@authorityclosers.com?subject=Authority%20Closers%20Learner%20Support">
              <HelpCircle size={20} aria-hidden="true" />
              Help
            </a>
            {salesXray ? (
              <a href={salesXray} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={20} aria-hidden="true" />
                Open Sales X-Ray
              </a>
            ) : null}
            <SignOutControl className={styles.signOut} />
          </nav>
        </Sheet>
      </ScreenTitleContext.Provider>
    </AccountContext.Provider>
  );
}
