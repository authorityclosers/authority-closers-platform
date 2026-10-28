import { BookOpen, CircleUser, Sun, Target } from "lucide-react";

export const places = [
  { title: "Today", href: "/home", icon: Sun },
  { title: "Learn", href: "/learning", icon: BookOpen },
  { title: "Practice", href: "/practice", icon: Target },
  { title: "Me", href: "/profile", icon: CircleUser },
] as const;
const under = (path: string, root: string) =>
  path === root || path.startsWith(`${root}/`);
export function activePlace(path: string) {
  if (
    ["/learning", "/learn", "/activity", "/discover"].some((root) =>
      under(path, root),
    )
  )
    return "/learning";
  if (under(path, "/practice")) return "/practice";
  if (
    [
      "/profile",
      "/progress",
      "/settings",
      "/certificates",
      "/notifications",
      "/calendar",
      "/leaderboard",
      "/consent",
    ].some((root) => under(path, root))
  )
    return "/profile";
  return "/home";
}
export function routeTitle(path: string) {
  const root = path.split("/")[1];
  return (
    (
      {
        home: "Today",
        learning: "Learn",
        learn: "Course",
        activity: "Lesson",
        practice: "Practice",
        profile: "Me",
        progress: "Progress",
        settings: "Settings",
        certificates: "Certificate",
        notifications: "Notifications",
        calendar: "Calendar",
        leaderboard: "Leaderboard",
        discover: "Discover",
        consent: "Your consent",
      } as Record<string, string>
    )[root] ?? "Reflex"
  );
}

/** Reverse of Sales X-Ray's learner-auth map; unknown hosts never guess. */
export function salesXrayForHost(hostname: string): string | null {
  const origins = new Map([
    ["learner.authorityclosers.com", "https://salesxray.authorityclosers.com"],
    [
      "learner-staging.authorityclosers.com",
      "https://salesxray-staging.authorityclosers.com",
    ],
  ]);
  return origins.get(hostname.toLowerCase()) ?? null;
}
