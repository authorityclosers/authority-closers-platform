import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DevelopmentMediaBridgeProvider,
  useDevelopmentMediaTransport,
} from "./development-media-bridge";

const origin = "http://learner.localhost:3100";
const source =
  "https://staging.authorityclosers.com/v1/media/playback/tenants%2Ft%2Fmedia%2Fvideo%2Fa%2Fv%2Foriginal?token=AC-MEDIA.fixture." +
  "s".repeat(43);
function Probe() {
  const transport = useDevelopmentMediaTransport([source]);
  return (
    <output data-enabled={transport.enabled}>
      {transport.resolveUrl(source) ?? "WITHHELD"}
    </output>
  );
}
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("development media context", () => {
  it("defaults off and preserves the original source outside the bridge", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(renderToStaticMarkup(<Probe />)).toContain('data-enabled="false"');
    expect(renderToStaticMarkup(<Probe />)).toContain(source);
  });
  it("cannot activate in production even with a provider value", () => {
    vi.stubEnv("NODE_ENV", "production");
    const html = renderToStaticMarkup(
      <DevelopmentMediaBridgeProvider browserOrigin={origin}>
        <Probe />
      </DevelopmentMediaBridgeProvider>,
    );
    expect(html).toContain('data-enabled="false"');
    expect(html).toContain(source);
  });
  it("remains enabled but withholds transport during SSR rather than falling back remotely", () => {
    vi.stubEnv("NODE_ENV", "development");
    const html = renderToStaticMarkup(
      <DevelopmentMediaBridgeProvider browserOrigin={origin}>
        <Probe />
      </DevelopmentMediaBridgeProvider>,
    );
    expect(html).toContain('data-enabled="true"');
    expect(html).toContain("WITHHELD");
    expect(html).not.toContain(source);
  });
  it("withholds even an exact-origin source until its asynchronous registration completes", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubGlobal("window", { location: { origin } });
    const render = (configured: string) =>
      renderToStaticMarkup(
        <DevelopmentMediaBridgeProvider browserOrigin={configured}>
          <Probe />
        </DevelopmentMediaBridgeProvider>,
      );
    expect(render(origin)).toContain("WITHHELD");
    expect(render("http://localhost:3100")).toContain("WITHHELD");
    expect(render("not-an-origin")).toContain("WITHHELD");
  });
});
