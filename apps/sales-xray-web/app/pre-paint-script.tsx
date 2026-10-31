"use client";

/**
 * An inline script that must run before the first paint (theme, glass,
 * sidebar, in-app, early reads). It is in the server's HTML, where the browser
 * runs it as it reads the page, and hydration keeps that element. A later
 * render from scratch on the client (the root remounting after an error, or a
 * dev reload) leaves it out: a script React writes on the client never runs,
 * and React says so in the console ("Encountered a script tag while rendering
 * React component", QA robot 6fa0427f, 1 Nov 2026).
 */

import { useEffect, useState } from "react";

// Set once this tab's first page has hydrated; never on the server, where no
// effect runs.
let hydrated = false;

export function PrePaintScript({ id, code }: { id: string; code: string }) {
  const [keep] = useState(() => !hydrated);
  useEffect(() => {
    hydrated = true;
  }, []);
  return keep ? (
    <script id={id} dangerouslySetInnerHTML={{ __html: code }} />
  ) : null;
}
