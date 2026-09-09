/** Runtime presentation gate only. The canonical Practice API authorizes every action. */
export function isPracticeUiEnabled(
  environment: Readonly<Record<string, string | undefined>>,
): boolean {
  const pilot = environment.AC_PRACTICE_PILOT_ENABLED === "true";
  const local = environment.AC_DEV_LOCAL_SANDBOX_ENABLED === "true";
  if (
    pilot &&
    (local || environment.AC_PRACTICE_ARCADE_PREVIEW_ENABLED === "true")
  )
    return false;
  if (!pilot)
    return (
      environment.NODE_ENV === "development" &&
      local &&
      (!environment.AC_ENVIRONMENT ||
        ["local", "test"].includes(environment.AC_ENVIRONMENT))
    );
  const uuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const tenant = environment.AC_PRACTICE_PILOT_TENANT_ID;
  const publicTenant = environment.AC_PUBLIC_LEARNER_TENANT_ID;
  const operations = environment.AC_OPERATIONS_TENANT_ID;
  return (
    environment.NODE_ENV === "production" &&
    ["staging", "production"].includes(environment.AC_ENVIRONMENT ?? "") &&
    typeof tenant === "string" &&
    uuid.test(tenant) &&
    typeof publicTenant === "string" &&
    uuid.test(publicTenant) &&
    tenant.toLowerCase() === publicTenant.toLowerCase() &&
    typeof operations === "string" &&
    uuid.test(operations) &&
    tenant.toLowerCase() !== operations.toLowerCase()
  );
}
