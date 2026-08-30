import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Authority Closers Learning",
    short_name: "AC Learning",
    description: "Evidence-backed sales practice for deliberate professionals.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f2f0e8",
    theme_color: "#11140f",
    orientation: "portrait-primary",
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
