import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Authority Closers Learning",
    short_name: "AC Learning",
    description: "Evidence-backed sales practice for deliberate professionals.",
    lang: "en",
    dir: "ltr",
    start_url: "/",
    scope: "/",
    display: "standalone",
    // Keep future display-mode additions from changing the installed shell.
    // Browsers that do not support display_override use `display` above.
    display_override: ["standalone"],
    background_color: "#f7f8fa",
    theme_color: "#f7f8fa",
    orientation: "any",
    // Explicitly opt out of related native-app promotion. This keeps the
    // install path web/PWA-first on Chromium without claiming a native app.
    prefer_related_applications: false,
    categories: ["education", "business"],
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
