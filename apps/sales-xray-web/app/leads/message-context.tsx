"use client";

import { createContext } from "react";
import type { MessageTemplate } from "./leads-client";

/** Ready messages and names, without loading the closed message composer. */
export const MessageSetup = createContext<{
  templates: MessageTemplate[];
  myName: string;
  org: string;
}>({ templates: [], myName: "", org: "" });
