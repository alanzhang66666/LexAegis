import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

const apiPort = "28775";
const gatewayPort = "28776";

export default defineConfig({
  ...base,
  metadata: { ...base.metadata, runtimeProfile: "production" },
  grep: /technical reviewer can prepare a production rule draft|formal DOCX upload|production formal intake/,
  grepInvert: undefined,
  outputDir: "test-results/production",
  reporter: [["list"], ["html", { outputFolder: "playwright-report/production", open: "never" }]],
  use: { ...base.use, baseURL: `http://127.0.0.1:${apiPort}` },
  projects: [{ name: "desktop-1440", use: {
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.platform === "darwin" && !process.env.CI
      ? { executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" }
      : {},
  } }],
  webServer: {
    ...base.webServer,
    url: `http://127.0.0.1:${apiPort}/api/v1/health`,
    reuseExistingServer: false,
    env: { ...base.webServer?.env, LEX_API_PORT:apiPort, LEX_GATEWAY_PORT:gatewayPort,
      LEX_GATEWAY_URL:`http://127.0.0.1:${gatewayPort}`, LEX_RUN_PROFILE: "production" },
  },
});
