import {
  ACCOUNT_PROFILE_PATH,
  readAccountProfile,
} from "../../account-profile-client";
import { OrgApiError } from "../organisation-api";

/** Existing self-service permission only. Preserve the phone and revision. */
export async function saveOwnDisplayName(displayName: string) {
  const name = displayName.trim();
  if (!name || [...name].length > 40)
    throw new OrgApiError(422, "Use 1–40 characters for your display name.");
  const current = await readAccountProfile();
  const response = await fetch(ACCOUNT_PROFILE_PATH, {
    method: "PUT",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      full_name: name,
      phone_number_e164: current.phone_number_e164,
      expected_revision: current.revision,
    }),
  });
  if (!response.ok)
    throw new OrgApiError(
      response.status,
      response.status === 409
        ? "Your profile changed. Try saving again."
        : "Your display name was not saved. Try again.",
    );
}
