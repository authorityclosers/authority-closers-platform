import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const repositoryRoot = path.resolve(__dirname, "../../../..");

function readJson(relativePath: string) {
  return JSON.parse(
    readFileSync(path.join(repositoryRoot, relativePath), "utf8"),
  ) as {
    dependencies?: Record<string, string>;
    devDependencies?: Record<string, string>;
    peerDependencies?: Record<string, string>;
  };
}

describe("patched image runtime dependency policy", () => {
  it("pins the reviewed Next and ESLint releases across every web app", () => {
    for (const manifestPath of [
      "apps/learner-web/package.json",
      "apps/admin-web/package.json",
      "apps/coach-web/package.json",
    ]) {
      const manifest = readJson(manifestPath);
      expect(manifest.dependencies?.next).toBe("16.3.3");
      expect(manifest.devDependencies?.["eslint-config-next"]).toBe("16.3.3");
    }

    const operations = readJson(
      "packages/typescript/operations-web/package.json",
    );
    expect(operations.peerDependencies?.next).toBe("16.3.3");
  });

  it("keeps the vulnerable Next and sharp releases out of the lockfile", () => {
    const workspace = readFileSync(
      path.join(repositoryRoot, "pnpm-workspace.yaml"),
      "utf8",
    );
    const lockfile = readFileSync(
      path.join(repositoryRoot, "pnpm-lock.yaml"),
      "utf8",
    );

    expect(workspace).toMatch(/^  sharp: 0\.35\.4$/m);
    expect(lockfile).toMatch(/^  next@16\.3\.3:$/m);
    expect(lockfile).toMatch(/^  sharp@0\.35\.4:$/m);
    expect(lockfile).not.toContain("next@16.2.11");
    expect(lockfile).not.toContain("sharp@0.35.0");
  });
});
