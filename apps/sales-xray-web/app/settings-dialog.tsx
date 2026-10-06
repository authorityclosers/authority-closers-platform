"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import dynamic from "next/dynamic";

import { FeatureLoading } from "./feature-loading";
import {
  SETTINGS_CHANGE_EVENT,
  SETTINGS_HASH_PREFIX,
  closeSettings,
  forgetSettingsEntry,
  opensInPlace,
  settingsHashOpen,
} from "./settings-open";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./settings-dialog.module.css";

const AccountSettings = dynamic(
  () => import("./account-settings").then((module) => module.AccountSettings),
  { loading: FeatureLoading },
);

/**
 * Floats account settings over whatever screen is open: a centred window on
 * a computer, a full-screen sheet on a phone. Mounted once by the app frame.
 */
export function SettingsDialogHost() {
  const access = useWorkspaceAccess();
  const [hashOpen, setHashOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const show = hashOpen && access?.authenticated === true;
  const identityKey = access?.context
    ? JSON.stringify([
        access.context.personId,
        access.context.sessionId,
        access.context.tenantId,
      ])
    : "signed-in";

  useEffect(() => {
    const sync = () => {
      forgetSettingsEntry();
      setHashOpen(settingsHashOpen(window.location.hash));
    };
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    window.addEventListener(SETTINGS_CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      window.removeEventListener(SETTINGS_CHANGE_EVENT, sync);
    };
  }, []);

  useEffect(() => {
    const node = dialog.current;
    if (!show || !node) return;
    const previous = document.activeElement as HTMLElement | null;
    if (!node.open) {
      if (typeof node.showModal === "function") node.showModal();
      else node.setAttribute("open", "");
    }
    const root = document.documentElement;
    const overflow = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = overflow;
      if (node.open && typeof node.close === "function") node.close();
      previous?.focus?.({ preventScroll: true });
    };
  }, [show]);

  if (!show) return null;

  const onClick = (event: MouseEvent<HTMLDialogElement>) => {
    // A click on the backdrop lands on the dialog element itself.
    if (event.target === event.currentTarget) {
      closeSettings();
      return;
    }
    const link = (event.target as HTMLElement).closest?.<HTMLAnchorElement>(
      "a[href]",
    );
    const href = link?.getAttribute("href") ?? "";
    if (
      link &&
      opensInPlace(event) &&
      href.startsWith("/") &&
      !href.startsWith("//") &&
      (!link.target || link.target === "_self") &&
      !link.hasAttribute("download")
    )
      closeSettings("replace");
  };

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-label="Settings"
      onCancel={(event) => {
        event.preventDefault();
        closeSettings();
      }}
      onClickCapture={onClick}
    >
      <AccountSettings
        key={identityKey}
        variant="dialog"
        hashPrefix={SETTINGS_HASH_PREFIX}
        onClose={() => closeSettings()}
      />
    </dialog>
  );
}
