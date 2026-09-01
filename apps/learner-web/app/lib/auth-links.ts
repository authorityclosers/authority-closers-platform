type GoogleAuthAction = "authenticate" | "register";

export const GOOGLE_REGISTRATION_RETURN_PATH = "/onboarding";

export function googleAuthStartUrl(action: GoogleAuthAction): string {
  const parameters = new URLSearchParams({
    action,
    surface: "learner",
    return_path:
      action === "register" ? GOOGLE_REGISTRATION_RETURN_PATH : "/home",
  });
  return `/v1/auth/google/start?${parameters.toString()}`;
}
