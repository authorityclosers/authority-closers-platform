import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Reflex: Sales Training",
    short_name: "Reflex",
    description: "Sales training by Authority Closers",
    lang: "en",
    dir: "ltr",
    start_url: "/",
    scope: "/",
    display: "standalone",
    // Keep future display-mode additions from changing the installed shell.
    // Browsers that do not support display_override use `display` above.
    display_override: ["standalone"],
    background_color: "#f2f3f7",
    theme_color: "#f2f3f7",
    orientation: "any",
    // Explicitly opt out of related native-app promotion. This keeps the
    // install path web/PWA-first on Chromium without claiming a native app.
    prefer_related_applications: false,
    categories: ["education", "business"],
    icons: [
      {
        src: "/brand/closers-academy-v0.1/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/brand/closers-academy-v0.1/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
