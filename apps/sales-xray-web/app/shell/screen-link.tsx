"use client";

import Link from "next/link";
import type { ComponentProps, PointerEvent } from "react";

import { useAppRouter } from "./app-router";
import { prefetchPlace } from "./route-prefetch";
import {
  moveScreen,
  pressScreen,
  releasePress,
  takePress,
} from "./screen-transition";

type ScreenLinkProps = Omit<ComponentProps<typeof Link>, "href"> & {
  href: string;
};

const pathOf = (href: string) => new URL(href, window.location.href).pathname;

/**
 * A link to another place in the app (tabs, rail). The press itself shows
 * the place's outline and starts its code and first reads; the click then
 * navigates, and the move runs as a screen transition (screen-transition.ts).
 * Everything else is Next's Link.
 */
export function ScreenLink({
  href,
  replace,
  scroll,
  onNavigate,
  onPointerDown,
  onPointerCancel,
  onPointerLeave,
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
        onPointerCancel={onPointerCancel}
        onPointerLeave={onPointerLeave}
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
        if (
          event.button !== 0 ||
          event.ctrlKey ||
          event.metaKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        prefetchPlace(router, href, true);
        pressScreen(window.location.pathname, pathOf(href));
      }}
      onPointerCancel={(event: PointerEvent<HTMLAnchorElement>) => {
        onPointerCancel?.(event);
        releasePress(pathOf(href));
      }}
      onPointerLeave={(event: PointerEvent<HTMLAnchorElement>) => {
        onPointerLeave?.(event);
        // A mouse dragged off the link while held: no click is coming.
        if (event.pointerType === "mouse" && event.buttons === 1)
          releasePress(pathOf(href));
      }}
      onNavigate={(event) => {
        let prevented = false;
        onNavigate?.({
          preventDefault: () => {
            prevented = true;
            event.preventDefault();
          },
        });
        const to = pathOf(href);
        if (prevented) {
          releasePress(to);
          return;
        }
        const options = scroll === false ? { scroll: false } : undefined;
        const navigate = () =>
          replace ? router.replace(href, options) : router.push(href, options);
        // The press already moved the screen: only the router is left.
        if (takePress(to)) {
          event.preventDefault();
          navigate();
          return;
        }
        if (moveScreen(navigate, window.location.pathname, to))
          event.preventDefault();
      }}
    />
  );
}
