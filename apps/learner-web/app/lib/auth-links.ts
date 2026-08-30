type GoogleAuthAction = "authenticate" | "register";

export function googleAuthStartUrl(action: GoogleAuthAction): string {
  const parameters = new URLSearchParams({
    action,
    surface: "learner",
    return_path: "/home",
  });
  return `/v1/auth/google/start?${parameters.toString()}`;
}
