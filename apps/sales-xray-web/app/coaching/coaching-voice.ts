"use client";

import { createContext, useContext } from "react";

/**
 * True on another rep's coaching (a fictional AC Sandbox rep, or a rep who
 * shared theirs), so the shared cards say "their", not "your".
 */
export const TheirCoaching = createContext(false);

export const useTheirCoaching = () => useContext(TheirCoaching);
