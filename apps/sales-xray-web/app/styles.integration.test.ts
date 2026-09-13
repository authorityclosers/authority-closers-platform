import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appDir = dirname(fileURLToPath(import.meta.url));
const styles = readFileSync(join(appDir, "styles.css"), "utf8");
const route = readFileSync(
  join(appDir, "../../learner-web/app/sales-xray/page.tsx"),
  "utf8",
);
const routeLayout = readFileSync(
  join(appDir, "../../learner-web/app/sales-xray/layout.tsx"),
  "utf8",
);

function withoutComments(value: string): string {
  return value.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("integrated Sales Xray boundary", () => {
  it("keeps generic Sales Xray rules inside the component scope", () => {
    const source = withoutComments(styles);
    const scopeStart = source.indexOf("@scope (.xray-app) {");

    expect(scopeStart).toBeGreaterThanOrEqual(0);
    expect(source.slice(0, scopeStart)).not.toMatch(
      /(?:^|\n)\s*(?:body|h1|h2|h3|p|button|a|input|select|textarea)\s*[,{]/,
    );
    expect(source).not.toMatch(/(?:^|\n)\s*body\s*[,{]/);
    expect(source).toMatch(/:scope\.simple-app\s*\{\s*display:\s*block;\s*\}/);
    expect(source).toContain(':scope[data-theme="dark"] {');
  });

  it("uses the real learner route without query supplied scope", () => {
    expect(route).toContain('<CallStudio homeHref="/home" variant="embedded" />');
    expect(route).not.toMatch(/searchParams|tenantId|workspaceId|scopeId/);
    expect(routeLayout).toContain('"../../../sales-xray-web/app/styles.css"');
  });
});
