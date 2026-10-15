import { defineConfig } from "vitest/config";

export default defineConfig({
  oxc: {
    jsx: {
      runtime: "automatic",
    },
  },
  // The Sales Xray studio is imported from ../sales-xray-web, which may pin a
  // newer Next patch. One Next copy for tests, as Next's own build does, so
  // vi.mock("next/navigation") reaches those files too.
  resolve: {
    dedupe: ["next"],
  },
  test: {
    environment: "node",
  },
});
