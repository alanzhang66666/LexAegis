import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  outputDir: "test-results/human-veto",
  reporter: [["list"], ["html", { outputFolder: "playwright-report/human-veto", open: "never" }]],
  grep: /human veto is visibly paused/,
  projects: [{ name: "desktop-1440", use: {
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.platform === "darwin" && !process.env.CI
      ? { executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" }
      : {},
  } }],
  webServer: {
    ...base.webServer,
    env: { ...base.webServer?.env, LEX_RUN_PROFILE: "demo" },
  },
});
