"use client";

import Link from "next/link";
import type { ComponentProps, PointerEvent } from "react";

import { useAppRouter } from "./app-router";
import { prefetchPlace } from "./route-prefetch";
import { moveScreen } from "./screen-transition";

type ScreenLinkProps = Omit<ComponentProps<typeof Link>, "href"> & {
  href: string;
};

/**
 * A link to another place in the app (tabs, rail): pressing it starts the
 * page's code and first reads, and the move runs as a screen transition
 * (screen-transition.ts). Everything else is Next's Link.
 */
export function ScreenLink({
  href,
  replace,
  scroll,
  onNavigate,
  onPointerDown,
  ...props
}: ScreenLinkProps) {
  const router = useAppRouter();
  if (!router)
    return (
      <Link
        {...props}
        href={href}
        replace={replace}
        scroll={scroll}
        onNavigate={onNavigate}
        onPointerDown={onPointerDown}
      />
    );
  return (
    <Link
      {...props}
      href={href}
      replace={replace}
      scroll={scroll}
      onPointerDown={(event: PointerEvent<HTMLAnchorElement>) => {
        onPointerDown?.(event);
        if (event.button === 0) prefetchPlace(router, href, true);
      }}
      onNavigate={(event) => {
        let prevented = false;
        onNavigate?.({
          preventDefault: () => {
            prevented = true;
            event.preventDefault();
          },
        });
        if (prevented) return;
        const to = new URL(href, window.location.href).pathname;
        const options = scroll === false ? { scroll: false } : undefined;
        const moved = moveScreen(
          () =>
            replace ? router.replace(href, options) : router.push(href, options),
          window.location.pathname,
          to,
        );
        if (moved) event.preventDefault();
      }}
    />
  );
}
