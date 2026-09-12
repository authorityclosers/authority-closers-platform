import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const traceModule = require.resolve("next/dist/trace");
const threshold = "9007199254740991";

// Exercise the real, pinned Next implementation in fresh processes, not a mock
// that could keep passing after a framework upgrade changes the recording path.
// Files contain only a synthetic invalid marker; they remain available in the
// explicitly labelled temp directory for failed-run investigation, never secrets.
function runInstalledTraceProbe(suppress: boolean) {
  const directory = mkdtempSync(
    path.join(tmpdir(), "ac-synthetic-media-trace-privacy-"),
  );
  const child = spawnSync(
    process.execPath,
    [
      "-e",
      `
        const path = require('node:path');
        const fs = require('node:fs');
        const { spawnSync } = require('node:child_process');
        const trace = require(${JSON.stringify(traceModule)});
        const directory = process.argv[1];
        trace.setGlobal('distDir', directory);
        trace.setGlobal('phase', 'phase-development-server');
        const marker = 'synthetic-invalid-media-trace-probe';
        const attrs = { url: '/v1/media/playback/fixture?token=' + marker };
        (async () => {
          // Cross the JSON reporter's >100 event automatic batch threshold.
          for (let i = 0; i < 110; i++) {
            const span = trace.trace('handle-request', undefined, attrs);
            span.traceChild('memory-usage', attrs).stop();
            span.stop();
          }
          // Include the exact greatest duration accepted by installed Span.stop.
          const largest = new trace.Span({ name: 'largest-valid-span', attrs, startTime: 1000n });
          largest.stop(1000n + BigInt(Number.MAX_SAFE_INTEGER) * 1000n);
          await trace.flushAllTraces({ end: true });
          const file = path.join(directory, 'trace');
          const contents = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
          const inherited = spawnSync(process.execPath, ['-e', 'process.stdout.write(process.env.NEXT_TRACE_SPAN_THRESHOLD_MS || "absent")'], { encoding: 'utf8' });
          process.stdout.write(JSON.stringify({
            markerCount: contents.split(marker).length - 1,
            traceBytes: Buffer.byteLength(contents),
            inheritedThreshold: inherited.stdout,
          }));
        })().catch(() => { process.stderr.write('Synthetic trace probe failed'); process.exitCode = 1; });
      `,
      directory,
    ],
    {
      env: {
        ...process.env,
        NODE_ENV: "development",
        NEXT_TRACE_SPAN_THRESHOLD_MS: suppress ? threshold : "-1",
        NEXT_TELEMETRY_DISABLED: "1",
      },
      encoding: "utf8",
      timeout: 15_000,
      windowsHide: true,
    },
  );
  expect(child.error).toBeUndefined();
  expect(child.status).toBe(0);
  expect(child.stderr).toBe("");
  return JSON.parse(child.stdout) as {
    markerCount: number;
    traceBytes: number;
    inheritedThreshold: string;
  };
}

describe("installed Next pre-bootstrap development trace privacy", () => {
  it("pins the reviewed runtime and proves the cutoff exceeds every valid span", () => {
    expect(require("next/package.json").version).toBe("16.3.3");
    const parsed = Number.parseInt(threshold, 10);
    const cutoffMicroseconds = parsed * 1000;
    expect(Number.isSafeInteger(parsed)).toBe(true);
    expect(Number.isFinite(cutoffMicroseconds)).toBe(true);
    // The multiplied Number need not be a safe integer: only the comparison
    // matters. Even the greatest accepted bigint duration is strictly below it.
    expect(BigInt(cutoffMicroseconds)).toBeGreaterThan(
      BigInt(Number.MAX_SAFE_INTEGER),
    );
  });

  it("negative control persists the synthetic URL when tracing is enabled", () => {
    const report = runInstalledTraceProbe(false);
    expect(report.markerCount).toBe(221);
    expect(report.traceBytes).toBeGreaterThan(0);
    expect(report.inheritedThreshold).toBe("-1");
  });

  it("suppresses real reporter batches and forced flush with inherited startup configuration", () => {
    const report = runInstalledTraceProbe(true);
    expect(report.markerCount).toBe(0);
    expect(report.traceBytes).toBe(0);
    expect(report.inheritedThreshold).toBe(threshold);
  });

  it("the shared launcher sets the guard only on the learner child before launch", () => {
    const launcher = readFileSync(
      path.resolve(
        __dirname,
        "../../../../scripts/Start-LocalStagingBridge.ps1",
      ),
      "utf8",
    );
    const assignment =
      '$LearnerEnvironment["NEXT_TRACE_SPAN_THRESHOLD_MS"] = "9007199254740991"';
    expect(launcher).toContain(assignment);
    expect(launcher.indexOf(assignment)).toBeLessThan(
      launcher.indexOf("$LearnerProcess = Start-Process"),
    );
    expect(launcher).not.toMatch(/\$env:NEXT_TRACE_SPAN_THRESHOLD_MS\s*=/i);
  });
});
