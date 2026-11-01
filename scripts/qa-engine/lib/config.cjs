// Engine (b) settings. Dev only: the proxy, the matrix and the folders are all on ac, and nothing here reaches
// production. Secrets never appear: sign-in goes through persona-qa's proxy (it holds the sandbox passwords).
const path = require("path");

const ROOT = process.env.QA_ENGINE_DIR || path.resolve(__dirname, "..");
const MATRIX_DIR = process.env.QA_MATRIX_DIR || "/home/acdev/qa-matrix";
const PLAYWRIGHT = process.env.PLAYWRIGHT_PATH || "/home/acdev/src/dev-live/authority-closers-platform/node_modules/playwright";

module.exports = {
  ROOT,
  MATRIX_DIR,
  PLAYWRIGHT,
  PROXY: process.env.QA_PROXY || "http://localhost:3098", // persona-qa's pass-through + /__as/<alias> sign-in
  OUT: process.env.QA_OUT || path.join(ROOT, "out"),
  STATE: process.env.QA_STATE || path.join(ROOT, "state"),
  BASELINES: process.env.QA_BASELINES || path.join(ROOT, "baselines"),
  CUT_FLAG: "/run/ac-release-cut.active",
  // The four sizes the matrix maps to headless contexts; the Redmi rows belong to adb (one driver per phone).
  DEVICES: {
    "390 px": { key: "390", viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, phone: true },
    "360 px": { key: "360", viewport: { width: 360, height: 740 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, phone: true },
    "1440": { key: "1440", viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, isMobile: false, hasTouch: false, phone: false },
    "1920": { key: "1920", viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, isMobile: false, hasTouch: false, phone: false },
  },
  ANDROID_UA:
    "Mozilla/5.0 (Linux; Android 10; M1906F9SI) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
  // Politeness on a host shared with production (memory: feedback-agent-jobs-capped, project-dev-box-contention).
  LIMITS: {
    cpuPressureMax: Number(process.env.QA_CPU_PSI_MAX || 97), // /proc/pressure/cpu some avg10 above this: wait
    memPressureMax: Number(process.env.QA_MEM_PSI_MAX || 12), // /proc/pressure/memory some avg10
    memAvailableMinMb: Number(process.env.QA_MEM_MIN_MB || 1800),
    swapFreeMinMb: Number(process.env.QA_SWAP_MIN_MB || 0), // swap is already near full on ac; only memory pressure matters
    loadMax: Number(process.env.QA_LOAD_MAX || 14),
    cutCpuPsiMax: Number(process.env.QA_CUT_CPU_PSI || 97), // while a release cut runs, wait above this
    cutLoadMax: Number(process.env.QA_CUT_LOAD || 10),
    contexts: Number(process.env.QA_CONTEXTS || 1),
    reportsPerPersonaPerHour: 40, // the reporter allows 60 per person per hour
    refileHours: 12, // a repeat inside this window is counted, not filed again
  },
  REPORT_AREAS: {
    // the matrix's area -> builder session that owns it (orchestrator's routing, 31 Oct 2026)
    Home: "seller-home-calls",
    Tasks: "seller-home-calls",
    Growth: "seller-home-calls",
    "Owner controls": "seller-home-calls",
    Performance: "seller-home-calls",
    Notifications: "seller-home-calls",
    "Ask Dipak": "seller-home-calls",
    Leads: "leads-cold-load",
    "Prospect's Information": "leads-cold-load",
    Reports: "leads-cold-load",
    "Follow-ups": "leads-cold-load",
    "After-Call": "leads-cold-load",
    "Lead import": "leads-cold-load",
    "Stage editor": "ux-audit",
    "Bug reporter": "ux-audit",
    "Capture setup": "required-call-capture-se",
    "Sign-in": "shell",
    Settings: "shell",
  },
};
