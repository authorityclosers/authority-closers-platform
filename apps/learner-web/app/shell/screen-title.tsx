"use client";

import { createContext, useContext, useEffect } from "react";
export const ScreenTitleContext = createContext<(title: string | null) => void>(
  () => undefined,
);

/** Pages declare their own title without mounting another shell. */
export function ScreenTitle({ title }: { title: string }) {
  const setTitle = useContext(ScreenTitleContext);
  useEffect(() => {
    setTitle(title);
    return () => setTitle(null);
  }, [setTitle, title]);
  return null;
}
