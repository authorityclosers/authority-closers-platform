"use client";

import { useWrites } from "../sync/write-queue";
import { unsentLine } from "./play";

/**
 * Beside "uninstall the downloaded app": changes on this phone that the
 * server doesn't have yet, which an uninstall would delete (orchestrator,
 * 24 Oct 2026). Nothing when there are none.
 */
export function UnsentBeforeSwitch() {
  const { deviceTotal } = useWrites();
  return deviceTotal ? <strong> {unsentLine(deviceTotal)}</strong> : null;
}
