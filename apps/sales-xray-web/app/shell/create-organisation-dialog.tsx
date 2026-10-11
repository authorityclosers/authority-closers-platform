"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import {
  createOrganisation,
  OrgApiError,
} from "../organisation/organisation-api";
import { Button, Dialog, Field } from "../ui/kit";

/**
 * "Create an organisation" from the workspace menu. The creator becomes its
 * owner; the shell then opens the new workspace on its Members tab.
 */
export function CreateOrganisationDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (tenantId: string) => void;
}) {
  const formId = useId();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // One key per name: sending the same name again can't create two.
  const request = useRef<{ name: string; key: string } | null>(null);

  const close = () => {
    if (busy) return;
    setError("");
    onClose();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const clean = name.trim().replace(/\s+/g, " ");
    if (clean.length < 2 || clean.length > 80) {
      setError("Use 2 to 80 characters.");
      return;
    }
    if (request.current?.name !== clean)
      request.current = { name: clean, key: crypto.randomUUID() };
    setBusy(true);
    setError("");
    try {
      const created = await createOrganisation(clean, request.current.key);
      // Busy stays on: the page moves into the new workspace.
      onCreated(created.tenantId);
    } catch (failure) {
      setBusy(false);
      setError(
        failure instanceof OrgApiError
          ? failure.message
          : "Check your connection and try again.",
      );
    }
  };

  return (
    <Dialog
      open={open}
      title="Create an organisation"
      description="Bring your sales team together: their calls and reports in one place."
      onClose={close}
      actions={
        <>
          <Button variant="ghost" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form={formId} disabled={busy}>
            {busy ? "Creating…" : "Create organisation"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate>
        <Field
          label="Organisation name"
          error={error || undefined}
          hint="You’ll be its owner. It starts with no seats or analysis minutes of its own."
        >
          <input
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setError("");
            }}
            maxLength={80}
            autoComplete="organization"
            autoFocus
            aria-invalid={error ? true : undefined}
            disabled={busy}
          />
        </Field>
      </form>
    </Dialog>
  );
}
