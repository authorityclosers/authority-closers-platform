import type { MetadataRoute } from "next";

// Installable Sales X-Ray: name, colours and the brand B icons (owner's pick, 23 Oct 2026).
export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Sales X-Ray",
    short_name: "Sales X-Ray",
    description: "Calls, leads and AI coaching for Indian sales teams.",
    start_url: "/",
    display: "standalone",
    background_color: "#0B4A44",
    theme_color: "#0B4A44",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
