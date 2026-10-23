// The Sales X-Ray mark's own colours (brand B "Insight", owner's pick, 23 Oct 2026). They are fixed artwork,
// the same in every theme and the same as the app icon, so they live here rather than in the theme tokens.
// Themed screens use the --lx tokens; only the mark's art reads these.
export const MARK_ART = {
  ground: ["#0F6157", "#0B4A44", "#073B36"],
  light: "#FFFFFF",
  bars: ["#7CF7CF", "#18C08C"],
  i: ["#FFFFFF", "#D3F7EA"],
  halo: "#3DEBB0",
} as const;
