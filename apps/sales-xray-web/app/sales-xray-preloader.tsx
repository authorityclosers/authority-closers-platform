"use client";

import { createElement, useEffect, useRef, useState } from "react";
import Image from "next/image";

import styles from "./sales-xray-preloader.module.css";

type PreloaderPhase =
  | "session"
  | "workspace"
  | "view"
  | "ready"
  | "delayed"
  | "error";
type PreloaderElement = HTMLElement & {
  setState?: (state: {
    brand?: "ac";
    phase?: PreloaderPhase;
    environment?: "production";
  }) => void;
};

let preloaderScript: Promise<void> | null = null;

function loadPreloaderScript() {
  if (typeof window === "undefined" || process.env.NODE_ENV === "test")
    return Promise.reject(new Error("preloader_script_unavailable"));
  if (window.customElements.get("ac-preloader")) return Promise.resolve();
  if (preloaderScript) return preloaderScript;

  preloaderScript = new Promise<void>((resolve, reject) => {
    const current = document.querySelector<HTMLScriptElement>(
      'script[data-sales-xray-preloader="true"]',
    );
    const script = current ?? document.createElement("script");
    const complete = () => resolve();
    const failed = () => reject(new Error("preloader_script_failed"));
    script.addEventListener("load", complete, { once: true });
    script.addEventListener("error", failed, { once: true });
    if (!current) {
      script.dataset.salesXrayPreloader = "true";
      script.src = "/experience-kit/ac-preloader.js";
      script.async = true;
      document.head.appendChild(script);
    }
  }).catch((error) => {
    preloaderScript = null;
    throw error;
  });

  return preloaderScript;
}

export function SalesXrayPreloader({
  phase = "session",
  openingExistingCall = false,
}: {
  phase?: PreloaderPhase;
  openingExistingCall?: boolean;
}) {
  const element = useRef<PreloaderElement>(null);
  const [defined, setDefined] = useState(false);

  useEffect(() => {
    let disposed = false;
    const sync = () => {
      if (disposed) return;
      setDefined(true);
      element.current?.setState?.({
        brand: "ac",
        phase,
        environment: "production",
      });
    };

    if (window.customElements.get("ac-preloader")) sync();
    else {
      void loadPreloaderScript()
        .then(sync)
        .catch(() => {
          // The accessible fallback remains visible if the local kit cannot load.
        });
    }

    return () => {
      disposed = true;
    };
  }, [phase]);

  useEffect(() => {
    if (!defined) return;
    element.current?.setState?.({ phase });
  }, [defined, phase]);

  return (
    <main
      className={styles.preloader}
      aria-busy="true"
      aria-label="Loading Sales Xray"
    >
      <div className={styles.fallback} aria-hidden={defined}>
        <Image
          className={styles.fallbackWave}
          src="/experience-kit/waves-desktop-transparent.svg"
          alt=""
          aria-hidden="true"
          width={1440}
          height={900}
          priority
        />
        <section
          className={styles.fallbackCard}
          aria-labelledby="sales-xray-preloader-heading"
        >
          <div className={styles.fallbackMark} aria-hidden="true">
            <Image
              src="/brand/ac-v0.1/symbol.svg"
              alt=""
              width={42}
              height={42}
              priority
            />
          </div>
          <p className={styles.fallbackEyebrow}>
            AUTHORITY CLOSERS · SALES XRAY
          </p>
          <h1 id="sales-xray-preloader-heading">
            {openingExistingCall
              ? "Opening your saved call"
              : "Getting Sales Xray ready."}
          </h1>
          <p>
            {openingExistingCall
              ? "Checking workspace access before loading this saved call…"
              : "Checking access to your workspace…"}
          </p>
        </section>
      </div>
      {createElement("ac-preloader", {
        ref: element,
        brand: "ac",
        phase,
        environment: "production",
      })}
    </main>
  );
}
