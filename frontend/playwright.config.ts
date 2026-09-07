import { defineConfig } from "@playwright/test";

const apiPort = process.env.LEX_API_PORT || "18765";
const gatewayPort = process.env.LEX_GATEWAY_PORT || "18766";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${apiPort}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python ../scripts/dev.py",
    url: `http://127.0.0.1:${apiPort}/api/v1/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
    env: {
      LEX_API_PORT: apiPort,
      LEX_GATEWAY_PORT: gatewayPort,
      LEX_GATEWAY_URL: `http://127.0.0.1:${gatewayPort}`,
      LEX_DATA_DIR: `../.data/playwright-${process.pid}`,
      LEX_GATEWAY_DIR: `../.data/playwright-gateway-${process.pid}`,
      LEX_LOCAL_PASSWORD: "local-acceptance-only",
      LEX_GATEWAY_SECRET: "local-acceptance-gateway-secret-32",
      LEX_OCR_ENABLED: "0",
    },
  },
  projects: [
    { name: "desktop-1440", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "desktop-1280", use: { viewport: { width: 1280, height: 900 } } },
    { name: "compact-900", use: { viewport: { width: 900, height: 900 } } },
    { name: "tablet-650", use: { viewport: { width: 650, height: 900 } } },
    { name: "mobile-390", use: { viewport: { width: 390, height: 844 } } },
  ],
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results",
});
